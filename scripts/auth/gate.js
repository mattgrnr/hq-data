// ==== HQ ACCOUNTS (scripts/auth/gate.js, injected by scripts/auth/inject.py) ====
// Every HQ page needs a signed-in account. Total HQ owns sign-in; each sport site keeps its own
// session cookie, handed over from Total HQ with a one-time pass. Accounts live in the hq-accounts
// D1 database (binding ACCOUNTS). The lock is on for preview links, and on the real domains once GATE = "on".
const HQA_SITES = ["total-hq", "slam-hq", "slapshot-hq", "touchdown-hq", "futbol-hq", "moonshot-hq"];
const HQA_DAYS = 90;
const HQA_OPEN = /^\/(guide|privacy|login|signup|forgot|logout|auth\/.*|og[^/]*\.png|favicon\.(png|ico)|apple-touch-icon\.png|robots\.txt|registry\.json)$/;
// link previews (X, iMessage, Slack, Discord...) still see each page's title and image
const HQA_BOTS = /bot\b|crawler|spider|facebookexternalhit|twitterbot|slackbot|discordbot|whatsapp|telegrambot|linkedinbot|embedly|pinterest|skypeuripreview/i;

function hqaHex(buf) { return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join(""); }
async function hqaHash(s) { return hqaHex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s))); }
function hqaToken() { return hqaHex(crypto.getRandomValues(new Uint8Array(24))); }
function hqaCookies(request) {
  const out = {};
  for (const part of (request.headers.get("Cookie") || "").split(";")) {
    const i = part.indexOf("=");
    if (i > 0) out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
  }
  return out;
}
function hqaCookie(name, value, maxAge, sameSite) {
  return name + "=" + encodeURIComponent(value) + "; Path=/; Max-Age=" + maxAge + "; HttpOnly; Secure; SameSite=" + (sameSite || "Lax");
}
function hqaDay(t) { return new Date(t - 6 * 3600e3).toISOString().slice(0, 10); }   // Central-ish day
function hqaOn(url, env) { return env.GATE === "on" || url.hostname.endsWith(".workers.dev"); }
// where Total HQ lives for this host: the matching preview link, or total-hq.com
function hqaTotal(url, site) {
  const h = url.hostname;
  if (h.endsWith(".workers.dev")) {
    const i = h.indexOf(site + ".");
    if (i >= 0) return "https://" + h.slice(0, i) + "total-hq." + h.slice(i + site.length + 1);
  }
  return "https://total-hq.com";
}
function hqaRedirect(to, cookies) {
  const headers = new Headers({ Location: to, "Cache-Control": "no-store" });
  for (const c of cookies || []) headers.append("Set-Cookie", c);
  return new Response(null, { status: 302, headers });
}
// the signed-in account for this request, or null
async function hqaSession(request, env) {
  const tok = hqaCookies(request).hq_s;
  if (!tok || !env.ACCOUNTS) return null;
  return await env.ACCOUNTS.prepare(
    "SELECT u.id, u.email, u.method, u.opt_in, u.admin, u.free_until, u.pw_hash IS NOT NULL has_pw, u.created_at, s.token_hash, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?"
  ).bind(await hqaHash(tok), Date.now()).first();
}
async function hqaStartSession(env, userId, site) {
  const tok = hqaToken(), now = Date.now();
  await env.ACCOUNTS.batch([
    env.ACCOUNTS.prepare("INSERT INTO sessions (token_hash, user_id, site, expires_at) VALUES (?, ?, ?, ?)").bind(await hqaHash(tok), userId, site, now + HQA_DAYS * 864e5),
    env.ACCOUNTS.prepare("INSERT OR IGNORE INTO visits (user_id, site, day) VALUES (?, ?, ?)").bind(userId, site, hqaDay(now)),
    env.ACCOUNTS.prepare("UPDATE users SET last_seen = ? WHERE id = ?").bind(now, userId),
  ]);
  return [hqaCookie("hq_s", tok, HQA_DAYS * 86400), hqaCookie("hq_v", hqaDay(now), 86400)];
}

// a sport site picking up the pass Total HQ just made for it
async function hqaHandoff(url, env, site) {
  const code = url.searchParams.get("code") || "";
  let next = url.searchParams.get("next") || "/";
  if (!next.startsWith("/") || next.startsWith("//")) next = "/";
  const h = await hqaHash(code);
  const row = await env.ACCOUNTS.prepare("SELECT user_id, origin, expires_at FROM handoffs WHERE code_hash = ?").bind(h).first();
  await env.ACCOUNTS.prepare("DELETE FROM handoffs WHERE code_hash = ? OR expires_at < ?").bind(h, Date.now()).run();
  if (!row || row.origin !== url.origin || row.expires_at < Date.now()) {
    return hqaRedirect(hqaTotal(url, site) + "/login?next=" + encodeURIComponent(url.origin + next));
  }
  return hqaRedirect(next, await hqaStartSession(env, row.user_id, site));
}

// Wraps a site's Worker: sign-in pages on Total HQ, the lock everywhere, and a daily visit count.
function hqaWrap(app, site, auth) {
  return {
    ...app,
    async fetch(request, env, ctx) {
      const url = new URL(request.url);
      if (!env.ACCOUNTS || !hqaOn(url, env)) return app.fetch(request, env, ctx);
      if (url.pathname === "/auth/handoff" && site !== "total-hq") return hqaHandoff(url, env, site);
      if (auth) {
        const r = await auth(request, env, ctx, url);
        if (r) return r;
      }
      const page = (request.method === "GET" || request.method === "HEAD") && (request.headers.get("Accept") || "").includes("text/html");
      if (!page || HQA_OPEN.test(url.pathname) || HQA_BOTS.test(request.headers.get("User-Agent") || "")) return app.fetch(request, env, ctx);

      const me = await hqaSession(request, env);
      if (!me) {
        const back = site === "total-hq" ? url.pathname + url.search : url.href;
        return hqaRedirect(hqaTotal(url, site) + "/login?next=" + encodeURIComponent(back));
      }
      const res = await app.fetch(request, env, ctx);
      const today = hqaDay(Date.now());
      if (hqaCookies(request).hq_v === today) return res;
      // once a day per site: count the visit and push the 90-day sign-in out again
      const now = Date.now();
      ctx.waitUntil(env.ACCOUNTS.batch([
        env.ACCOUNTS.prepare("INSERT OR IGNORE INTO visits (user_id, site, day) VALUES (?, ?, ?)").bind(me.id, site, today),
        env.ACCOUNTS.prepare("UPDATE users SET last_seen = ? WHERE id = ?").bind(now, me.id),
        env.ACCOUNTS.prepare("UPDATE sessions SET expires_at = ? WHERE token_hash = ?").bind(now + HQA_DAYS * 864e5, me.token_hash),
      ]));
      const out = new Response(res.body, res);
      out.headers.append("Set-Cookie", hqaCookie("hq_s", hqaCookies(request).hq_s, HQA_DAYS * 86400));
      out.headers.append("Set-Cookie", hqaCookie("hq_v", today, 86400));
      return out;
    },
  };
}
// ==== /HQ ACCOUNTS ====
