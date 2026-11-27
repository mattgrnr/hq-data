// ==== HQ SIGN-IN (scripts/auth/total.js, Total HQ only, injected by scripts/auth/inject.py) ====
// Sign in with Apple, Google or a six-digit email code. No passwords anywhere.
// Secrets MG sets on the total-hq Worker: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, APPLE_SERVICES_ID,
// APPLE_TEAM_ID, APPLE_KEY_ID, APPLE_PRIVATE_KEY, RESEND_API_KEY. Admins are marked in the database (users.admin = 1).
const HQA_MIN = 60e3;

function hqaEsc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]); }
function hqaHtml(body, status, cookies) {
  const headers = new Headers({ "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
  for (const c of cookies || []) headers.append("Set-Cookie", c);
  return new Response(body, { status: status || 200, headers });
}
function hqaB64url(s) { return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); }
function hqaJwtBody(jwt) {
  try {
    const p = jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(decodeURIComponent(escape(atob(p + "=".repeat((4 - p.length % 4) % 4)))));
  } catch (e) { return null; }
}
// a sign-in may only send people on to one of the HQ sites (or their matching preview links)
function hqaSafeNext(next, url) {
  if (!next) return "/";
  if (next.startsWith("/") && !next.startsWith("//")) return next;
  try {
    const n = new URL(next), h = url.hostname;
    if (n.protocol !== "https:") return "/";
    if (h.endsWith(".workers.dev")) {
      const i = h.indexOf("total-hq.");
      const pre = h.slice(0, i), post = h.slice(i + 9);
      if (HQA_SITES.some(s => n.hostname === pre + s + "." + post)) return n.href;
    } else if (HQA_SITES.some(s => n.hostname === s + ".com" || n.hostname === "www." + s + ".com")) {
      return n.href;
    }
  } catch (e) {}
  return "/";
}
// after sign-in: straight back to the page they wanted, carrying the sign-in to a sport site if needed
async function hqaContinue(env, url, userId, next, cookies) {
  const to = hqaSafeNext(next, url);
  if (to.startsWith("/")) return hqaRedirect(to, cookies);
  const t = new URL(to);
  if (t.origin === url.origin) return hqaRedirect(t.pathname + t.search, cookies);
  const code = hqaToken();
  await env.ACCOUNTS.prepare("INSERT INTO handoffs (code_hash, user_id, origin, expires_at) VALUES (?, ?, ?, ?)")
    .bind(await hqaHash(code), userId, t.origin, Date.now() + HQA_MIN).run();
  return hqaRedirect(t.origin + "/auth/handoff?code=" + code + "&next=" + encodeURIComponent(t.pathname + t.search), cookies);
}
// a person Apple, Google or an email code has vouched for: existing account, or the 21+ step
async function hqaSignedIn(env, url, who, next) {
  const db = env.ACCOUNTS, email = (who.email || "").toLowerCase();
  let user = null;
  if (who.method === "apple") user = await db.prepare("SELECT id FROM users WHERE apple_sub = ?").bind(who.sub).first();
  if (who.method === "google") user = await db.prepare("SELECT id FROM users WHERE google_sub = ?").bind(who.sub).first();
  if (!user && email) {
    user = await db.prepare("SELECT id FROM users WHERE email = ?").bind(email).first();
    if (user && who.method !== "email") await db.prepare("UPDATE users SET " + who.method + "_sub = ? WHERE id = ?").bind(who.sub, user.id).run();
  }
  if (user) return hqaContinue(env, url, user.id, next, await hqaStartSession(env, user.id, "total-hq"));
  if (!email) return hqaLogin(url, next, "We couldn't get an email address from that sign-in. Try another option.");
  const tok = hqaToken();
  await db.prepare("INSERT INTO pending (token_hash, email, method, sub, next, expires_at) VALUES (?, ?, ?, ?, ?, ?)")
    .bind(await hqaHash(tok), email, who.method, who.sub || null, next || "/", Date.now() + 15 * HQA_MIN).run();
  return hqaRedirect("/auth/welcome", [hqaCookie("hq_p", tok, 900)]);
}

// ---------- pages ----------
const HQA_CSS = `:root{--void:#08090C;--hq:#FF4D3D;--paper:#EDEAE3;--mute:#8A909A;--dim:#454B55;--rule:rgba(255,255,255,.075);--lift:rgba(255,255,255,.035);--open:#4ADE80}
*{box-sizing:border-box;margin:0;padding:0}
html{background:var(--void)}
body{background:radial-gradient(1300px 680px at 50% -18%,rgba(237,234,227,.075),transparent 64%),var(--void);background-attachment:fixed;
  color:var(--paper);font-family:'Space Grotesk',system-ui,sans-serif;-webkit-font-smoothing:antialiased;min-height:100vh}
.wrap{max-width:440px;margin:0 auto;padding:44px 20px 40px}
.wide{max-width:760px}
a{color:inherit}
h1{font-family:'Big Shoulders Display',sans-serif;font-weight:800;font-size:clamp(52px,15vw,76px);line-height:.9;letter-spacing:.005em}
h1 span{color:var(--hq)}
h2{font-family:'Big Shoulders Display',sans-serif;font-weight:700;font-size:28px;line-height:1.05;margin:30px 0 10px}
.lede{margin:14px 0 26px;color:var(--mute);font-size:15px;line-height:1.55}
.lede b{color:var(--paper);font-weight:500}
.btn{display:flex;align-items:center;justify-content:center;width:100%;min-height:50px;border-radius:12px;font:600 16px 'Space Grotesk',system-ui,sans-serif;
  text-decoration:none;cursor:pointer;border:1px solid var(--rule);background:var(--lift);color:var(--paper);margin-top:10px}
.btn:hover{border-color:rgba(255,255,255,.22)}
.btn:focus-visible,input:focus-visible{outline:2px solid var(--paper);outline-offset:2px}
.btn.apple{background:var(--paper);color:#000;border-color:var(--paper)}
.btn.go{background:var(--hq);color:#fff;border-color:var(--hq)}
.btn.quiet{background:none;color:var(--mute);min-height:40px;font-weight:500;font-size:14px}
.btn[disabled]{opacity:.45;cursor:default}
.or{display:flex;align-items:center;gap:12px;color:var(--dim);font-size:12px;margin:22px 0 12px}
.or:before,.or:after{content:"";flex:1;height:1px;background:var(--rule)}
label.f{display:block;font-size:13px;color:var(--mute);margin-bottom:6px}
input[type=email],input[type=text]{width:100%;height:50px;border-radius:12px;border:1px solid var(--rule);background:var(--lift);color:var(--paper);
  font:500 16px 'Space Grotesk',system-ui,sans-serif;padding:0 14px}
input.code{font-size:26px;letter-spacing:.35em;text-align:center}
.check{display:flex;gap:12px;align-items:flex-start;padding:14px;border:1px solid var(--rule);border-radius:12px;margin-top:10px;cursor:pointer;font-size:15px;line-height:1.45}
.check input{width:20px;height:20px;margin-top:1px;accent-color:var(--hq);flex:none}
.check small{display:block;color:var(--mute);font-size:13px}
.note{margin-top:14px;padding:12px 14px;border-radius:12px;background:rgba(255,77,61,.1);border:1px solid rgba(255,77,61,.35);font-size:14px;line-height:1.45}
.note.ok{background:rgba(74,222,128,.08);border-color:rgba(74,222,128,.35)}
.fine{margin-top:26px;color:var(--mute);font-size:12.5px;line-height:1.55}
.fine a{color:var(--paper)}
.prose p,.prose li{color:var(--mute);font-size:15px;line-height:1.6;margin-top:8px}
.prose ul{padding-left:18px}
.prose b{color:var(--paper);font-weight:500}
dl.me{display:grid;grid-template-columns:auto 1fr;gap:10px 18px;margin:20px 0;font-size:15px}
dl.me dt{color:var(--mute)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:18px}
.stat{padding:14px;border:1px solid var(--rule);border-radius:12px;background:var(--lift)}
.stat b{display:block;font-family:'Big Shoulders Display',sans-serif;font-size:40px;line-height:1}
.stat span{color:var(--mute);font-size:13px}
table{width:100%;border-collapse:collapse;margin-top:10px;font-size:14px;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:8px 6px;border-bottom:1px solid var(--rule)}
th:first-child,td:first-child{text-align:left}
th{color:var(--mute);font-weight:500;font-size:12.5px}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:22px;font-size:13px;color:var(--mute)}
.top a{text-decoration:none}.top a:hover{color:var(--paper)}`;

function hqaPage(title, body, wide) {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>${hqaEsc(title)}</title><meta name="theme-color" content="#08090C"><meta name="robots" content="noindex">
<link rel="icon" type="image/png" href="/favicon.png"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@600;700;800&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>${HQA_CSS}</style></head><body><main class="wrap${wide ? " wide" : ""}">${body}</main></body></html>`;
}
const HQA_FINE = `<p class="fine">21+ only. By continuing you agree to our <a href="/privacy">privacy policy</a>. Gambling problem? Call <a href="tel:18004264537">1-800-GAMBLER</a>.</p>`;

function hqaLogin(url, next, error) {
  const n = encodeURIComponent(next || "/");
  return hqaHtml(hqaPage("Sign in · Total HQ", `
<h1>TOTAL <span>HQ</span></h1>
<p class="lede">Sign in to use the boards. <b>No password to remember</b>: pick an account you already have, or get a one-time code by email.</p>
${error ? `<p class="note" role="alert">${hqaEsc(error)}</p>` : ""}
<a class="btn apple" href="/auth/apple?next=${n}">Continue with Apple</a>
<a class="btn" href="/auth/google?next=${n}">Continue with Google</a>
<div class="or">or</div>
<form method="post" action="/auth/email">
  <input type="hidden" name="next" value="${hqaEsc(next || "/")}">
  <label class="f" for="email">Email</label>
  <input id="email" type="email" name="email" autocomplete="email" inputmode="email" required placeholder="you@example.com">
  <button class="btn go" type="submit">Email me a code</button>
</form>
<p class="fine"><a href="/guide">New here? See how HQ works</a></p>
${HQA_FINE}`), error ? 400 : 200);
}

function hqaCodePage(email, next, error, shown) {
  return hqaHtml(hqaPage("Check your email · Total HQ", `
<h1>CHECK YOUR <span>EMAIL</span></h1>
<p class="lede">We sent a six-digit code to <b>${hqaEsc(email)}</b>. It works for 10 minutes.</p>
${shown ? `<p class="note ok">Preview only, because email isn't connected yet. Your code is <b>${shown}</b>.</p>` : ""}
${error ? `<p class="note" role="alert">${hqaEsc(error)}</p>` : ""}
<form method="post" action="/auth/email/verify">
  <input type="hidden" name="email" value="${hqaEsc(email)}"><input type="hidden" name="next" value="${hqaEsc(next)}">
  <label class="f" for="code">Code</label>
  <input id="code" class="code" type="text" name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required autofocus>
  <button class="btn go" type="submit">Sign in</button>
</form>
<a class="btn quiet" href="/login?next=${encodeURIComponent(next)}">Use a different email</a>`), error ? 400 : 200);
}

// ---------- email codes ----------
async function hqaForm(request) {
  try { return await request.formData(); } catch (e) { return new FormData(); }
}
async function hqaEmailStart(request, env, url) {
  const f = await hqaForm(request);
  const email = String(f.get("email") || "").trim().toLowerCase(), next = String(f.get("next") || "/");
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 200) return hqaLogin(url, next, "That email address doesn't look right.");
  const preview = !env.RESEND_API_KEY && url.hostname.endsWith(".workers.dev");
  if (!env.RESEND_API_KEY && !preview) return hqaLogin(url, next, "Email sign-in isn't switched on yet. Use Apple or Google for now.");
  const now = Date.now(), db = env.ACCOUNTS;
  const prev = await db.prepare("SELECT sent, window_start FROM codes WHERE email = ?").bind(email).first();
  const fresh = !prev || now - prev.window_start > 3600e3;
  if (!fresh && prev.sent >= 5) return hqaLogin(url, next, "Too many codes for this email in the last hour. Try again later, or use Apple or Google.");
  const code = String(100000 + crypto.getRandomValues(new Uint32Array(1))[0] % 900000);
  await db.prepare("INSERT OR REPLACE INTO codes (email, code_hash, expires_at, tries, sent, window_start) VALUES (?, ?, ?, 0, ?, ?)")
    .bind(email, await hqaHash(email + ":" + code), now + 10 * HQA_MIN, fresh ? 1 : prev.sent + 1, fresh ? now : prev.window_start).run();
  if (preview) return hqaCodePage(email, next, "", code);
  const sent = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: "Bearer " + env.RESEND_API_KEY, "Content-Type": "application/json" },
    body: JSON.stringify({
      from: "Total HQ <noreply@total-hq.com>", to: [email], subject: "Your Total HQ code: " + code,
      text: "Your Total HQ sign-in code is " + code + ". It works for 10 minutes.\n\nIf you didn't ask for this, you can ignore this email.",
      html: `<div style="font-family:system-ui,sans-serif;font-size:16px;color:#111"><p>Your Total HQ sign-in code is</p><p style="font-size:32px;font-weight:700;letter-spacing:6px">${code}</p><p>It works for 10 minutes. If you didn't ask for this, you can ignore this email.</p></div>`,
    }),
  }).catch(() => null);
  if (!sent || !sent.ok) return hqaLogin(url, next, "We couldn't send the email just now. Try again in a minute, or use Apple or Google.");
  return hqaCodePage(email, next);
}
async function hqaEmailVerify(request, env, url) {
  const f = await hqaForm(request);
  const email = String(f.get("email") || "").trim().toLowerCase(), next = String(f.get("next") || "/"), code = String(f.get("code") || "").trim();
  const db = env.ACCOUNTS, row = await db.prepare("SELECT code_hash, expires_at, tries FROM codes WHERE email = ?").bind(email).first();
  if (!row || row.expires_at < Date.now() || row.tries >= 5) return hqaCodePage(email, next, "That code has expired. Go back and get a new one.");
  if (row.code_hash !== await hqaHash(email + ":" + code)) {
    await db.prepare("UPDATE codes SET tries = tries + 1 WHERE email = ?").bind(email).run();
    return hqaCodePage(email, next, "That code isn't right. Check the email and try again.");
  }
  await db.prepare("UPDATE codes SET expires_at = 0 WHERE email = ?").bind(email).run();
  return hqaSignedIn(env, url, { method: "email", email }, next);
}

// ---------- Google ----------
async function hqaGoogleStart(env, url) {
  const next = url.searchParams.get("next") || "/";
  if (!env.GOOGLE_CLIENT_ID || !env.GOOGLE_CLIENT_SECRET) return hqaLogin(url, next, "Google sign-in isn't switched on yet. Use another option for now.");
  const state = hqaToken();
  const q = new URLSearchParams({ client_id: env.GOOGLE_CLIENT_ID, redirect_uri: url.origin + "/auth/google/callback", response_type: "code",
    scope: "openid email", state, prompt: "select_account" });
  return hqaRedirect("https://accounts.google.com/o/oauth2/v2/auth?" + q, [hqaCookie("hq_o", state + "|" + next, 600)]);
}
async function hqaGoogleBack(request, env, url) {
  const [state, ...rest] = (hqaCookies(request).hq_o || "").split("|"), next = rest.join("|") || "/";
  if (!state || url.searchParams.get("state") !== state || !url.searchParams.get("code")) return hqaLogin(url, next, "Google sign-in didn't finish. Try again.");
  const r = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ code: url.searchParams.get("code"), client_id: env.GOOGLE_CLIENT_ID, client_secret: env.GOOGLE_CLIENT_SECRET,
      redirect_uri: url.origin + "/auth/google/callback", grant_type: "authorization_code" }),
  }).catch(() => null);
  const id = r && r.ok ? hqaJwtBody((await r.json()).id_token || "") : null;
  if (!id || !id.sub || id.email_verified === false) return hqaLogin(url, next, "Google sign-in didn't finish. Try again.");
  const res = await hqaSignedIn(env, url, { method: "google", sub: id.sub, email: id.email }, next);
  res.headers.append("Set-Cookie", hqaCookie("hq_o", "", 0));
  return res;
}

// ---------- Apple ----------
// Apple's client secret is a short-lived token signed with the private key from the developer account
async function hqaAppleSecret(env) {
  const pem = env.APPLE_PRIVATE_KEY.replace(/-----[^-]+-----/g, "").replace(/\s+/g, "");
  const der = Uint8Array.from(atob(pem), c => c.charCodeAt(0));
  const key = await crypto.subtle.importKey("pkcs8", der, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
  const now = Math.floor(Date.now() / 1000);
  const head = hqaB64url(JSON.stringify({ alg: "ES256", kid: env.APPLE_KEY_ID }));
  const body = hqaB64url(JSON.stringify({ iss: env.APPLE_TEAM_ID, iat: now, exp: now + 300, aud: "https://appleid.apple.com", sub: env.APPLE_SERVICES_ID }));
  const sig = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, new TextEncoder().encode(head + "." + body));
  return head + "." + body + "." + hqaB64url(String.fromCharCode(...new Uint8Array(sig)));
}
async function hqaAppleStart(env, url) {
  const next = url.searchParams.get("next") || "/";
  if (!env.APPLE_SERVICES_ID || !env.APPLE_TEAM_ID || !env.APPLE_KEY_ID || !env.APPLE_PRIVATE_KEY) return hqaLogin(url, next, "Apple sign-in isn't switched on yet. Use another option for now.");
  const state = hqaToken();
  const q = new URLSearchParams({ client_id: env.APPLE_SERVICES_ID, redirect_uri: url.origin + "/auth/apple/callback", response_type: "code",
    response_mode: "form_post", scope: "email", state });
  // Apple posts back from its own site, so this cookie has to travel on a cross-site request
  return hqaRedirect("https://appleid.apple.com/auth/authorize?" + q, [hqaCookie("hq_o", state + "|" + next, 600, "None")]);
}
async function hqaAppleBack(request, env, url) {
  const f = await hqaForm(request);
  const [state, ...rest] = (hqaCookies(request).hq_o || "").split("|"), next = rest.join("|") || "/";
  if (!state || f.get("state") !== state || !f.get("code")) return hqaLogin(url, next, "Apple sign-in didn't finish. Try again.");
  const r = await fetch("https://appleid.apple.com/auth/token", {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ code: f.get("code"), client_id: env.APPLE_SERVICES_ID, client_secret: await hqaAppleSecret(env),
      redirect_uri: url.origin + "/auth/apple/callback", grant_type: "authorization_code" }),
  }).catch(() => null);
  const id = r && r.ok ? hqaJwtBody((await r.json()).id_token || "") : null;
  if (!id || !id.sub) return hqaLogin(url, next, "Apple sign-in didn't finish. Try again.");
  const res = await hqaSignedIn(env, url, { method: "apple", sub: id.sub, email: id.email }, next);
  res.headers.append("Set-Cookie", hqaCookie("hq_o", "", 0, "None"));
  return res;
}

// ---------- new account: the 21+ step ----------
async function hqaWelcome(request, env, url) {
  const tok = hqaCookies(request).hq_p, db = env.ACCOUNTS;
  const p = tok ? await db.prepare("SELECT * FROM pending WHERE token_hash = ? AND expires_at > ?").bind(await hqaHash(tok), Date.now()).first() : null;
  if (!p) return hqaRedirect("/login");
  if (request.method === "POST") {
    const f = await hqaForm(request);
    if (f.get("age") !== "yes") return hqaHtml(hqaWelcomePage(p, "You need to be 21 or older to use HQ."), 400);
    const id = hqaToken().slice(0, 16), now = Date.now();
    await db.batch([
      db.prepare("INSERT OR IGNORE INTO users (id, email, method, apple_sub, google_sub, opt_in, age_ok, created_at, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
        .bind(id, p.email, p.method, p.method === "apple" ? p.sub : null, p.method === "google" ? p.sub : null, f.get("updates") === "yes" ? 1 : 0, now, now, now),
      db.prepare("DELETE FROM pending WHERE token_hash = ? OR expires_at < ?").bind(p.token_hash, now),
    ]);
    const user = await db.prepare("SELECT id FROM users WHERE email = ?").bind(p.email).first();
    const cookies = await hqaStartSession(env, user.id, "total-hq");
    cookies.push(hqaCookie("hq_p", "", 0));
    return hqaContinue(env, url, user.id, p.next, cookies);
  }
  return hqaHtml(hqaWelcomePage(p));
}
function hqaWelcomePage(p, error) {
  return hqaPage("Welcome · Total HQ", `
<h1>ONE MORE <span>STEP</span></h1>
<p class="lede">You're creating an account for <b>${hqaEsc(p.email)}</b>.</p>
${error ? `<p class="note" role="alert">${hqaEsc(error)}</p>` : ""}
<form method="post" action="/auth/welcome">
  <label class="check"><input type="checkbox" name="age" value="yes" required><span>I'm 21 or older</span></label>
  <label class="check"><input type="checkbox" name="updates" value="yes"><span>Send me occasional updates<small>New features and sports. No spam, and you can turn it off anytime.</small></span></label>
  <button class="btn go" type="submit">Create account</button>
</form>
<a class="btn quiet" href="/login">Cancel</a>
${HQA_FINE}`);
}

// ---------- account, sign out, delete ----------
function hqaAccountPage(me, note) {
  const how = { apple: "Apple", google: "Google", email: "Email code" }[me.method] || me.method;
  return hqaPage("Your account · Total HQ", `
<div class="top"><a href="/">← Total HQ</a><a href="/privacy">Privacy</a></div>
<h1>YOUR <span>ACCOUNT</span></h1>
${note ? `<p class="note ok">${hqaEsc(note)}</p>` : ""}
<dl class="me"><dt>Email</dt><dd>${hqaEsc(me.email)}</dd><dt>Signed up with</dt><dd>${how}</dd>
<dt>Member since</dt><dd>${new Date(me.created_at).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "America/Chicago" })}</dd></dl>
<form method="post" action="/account/updates"><input type="hidden" name="on" value="${me.opt_in ? "0" : "1"}">
  <button class="btn" type="submit">${me.opt_in ? "Stop update emails" : "Send me occasional updates"}</button></form>
<form method="post" action="/logout"><button class="btn" type="submit">Sign out everywhere</button></form>
<h2>Delete account</h2>
<p class="lede" style="margin:0 0 6px">This removes your account and your visit history right away. It can't be undone.</p>
<form method="post" action="/account/delete">
  <label class="check"><input type="checkbox" name="sure" value="yes" required><span>Yes, delete my account</span></label>
  <button class="btn quiet" type="submit" style="color:var(--hq)">Delete my account</button>
</form>`);
}
async function hqaAccount(request, env, url, path) {
  const me = await hqaSession(request, env);
  if (!me) return hqaRedirect("/login?next=" + encodeURIComponent(path));
  const db = env.ACCOUNTS;
  if (path === "/account/updates" && request.method === "POST") {
    const on = (await hqaForm(request)).get("on") === "1" ? 1 : 0;
    await db.prepare("UPDATE users SET opt_in = ? WHERE id = ?").bind(on, me.id).run();
    return hqaHtml(hqaAccountPage({ ...me, opt_in: on }, on ? "You'll get occasional updates." : "Update emails are off."));
  }
  if (path === "/account/delete" && request.method === "POST") {
    if ((await hqaForm(request)).get("sure") !== "yes") return hqaHtml(hqaAccountPage(me));
    await db.batch([
      db.prepare("DELETE FROM sessions WHERE user_id = ?").bind(me.id),
      db.prepare("DELETE FROM visits WHERE user_id = ?").bind(me.id),
      db.prepare("DELETE FROM handoffs WHERE user_id = ?").bind(me.id),
      db.prepare("DELETE FROM codes WHERE email = ?").bind(me.email),
      db.prepare("DELETE FROM users WHERE id = ?").bind(me.id),
    ]);
    return hqaHtml(hqaPage("Account deleted · Total HQ", `<h1>ACCOUNT <span>DELETED</span></h1>
<p class="lede">Your account and visit history are gone. Thanks for trying HQ.</p><a class="btn" href="/login">Back to sign-in</a>`), 200, [hqaCookie("hq_s", "", 0)]);
  }
  return hqaHtml(hqaAccountPage(me));
}

// ---------- privacy ----------
const HQA_PRIVACY = hqaPage("Privacy · Total HQ", `
<div class="top"><a href="/">← Total HQ</a><span>Updated November 27, 2026</span></div>
<h1>PRIVACY</h1>
<div class="prose">
<p>HQ keeps as little about you as it can. Here's all of it, in plain words.</p>
<h2>What we keep</h2>
<ul>
<li><b>Your email address</b>, so you have an account. If you sign in with Apple and choose to hide your email, we only get Apple's relay address.</li>
<li><b>How you signed in</b> (Apple, Google or an email code) and the account ID Apple or Google gives us, so you can sign in again.</li>
<li><b>When you joined and when you last visited</b>, and <b>which HQ sites you opened each day</b>. That's how we count how many people use each board.</li>
<li><b>Whether you want update emails.</b> It's off unless you tick the box.</li>
</ul>
<h2>What we don't keep</h2>
<ul>
<li>No passwords. There aren't any.</li>
<li>No payment details, no sportsbook logins, no location.</li>
<li>No ad trackers. We don't sell or share your information with anyone.</li>
</ul>
<h2>Cookies</h2>
<p>Each HQ site sets one cookie that keeps you signed in for 90 days, plus a small one that stops us counting the same visit twice in a day. Nothing else.</p>
<h2>Emails</h2>
<p>We email you a code when you sign in with email. We only send anything else if you asked for updates, and every update has a way to stop them.</p>
<h2>Deleting your account</h2>
<p>Go to <a href="/account">your account</a> and choose Delete. Your account and visit history are removed right away.</p>
<h2>Age</h2>
<p>HQ is for people 21 and older. Gambling problem? Call <a href="tel:18004264537">1-800-GAMBLER</a>.</p>
<h2>Questions</h2>
<p>Email <a href="mailto:support@total-hq.com">support@total-hq.com</a>.</p>
</div>`);

// ---------- admin: who's using HQ ----------
async function hqaAdmin(request, env, url) {
  const me = await hqaSession(request, env);
  if (!me) return hqaRedirect("/login?next=/admin");
  if (!me.admin) return new Response("Not found", { status: 404 });
  const db = env.ACCOUNTS, now = Date.now(), today = hqaDay(now);
  const since = d => hqaDay(now - d * 864e5);
  const [tot, wk, act, opt, methods, signups, daily, sites] = await db.batch([
    db.prepare("SELECT COUNT(*) n FROM users"),
    db.prepare("SELECT COUNT(*) n FROM users WHERE created_at > ?").bind(now - 7 * 864e5),
    db.prepare("SELECT COUNT(DISTINCT user_id) n FROM visits WHERE day = ?").bind(today),
    db.prepare("SELECT COUNT(*) n FROM users WHERE opt_in = 1"),
    db.prepare("SELECT method, COUNT(*) n FROM users GROUP BY method"),
    db.prepare("SELECT date((created_at - 21600000) / 1000, 'unixepoch') day, COUNT(*) n FROM users WHERE created_at > ? GROUP BY day").bind(now - 14 * 864e5),
    db.prepare("SELECT day, COUNT(DISTINCT user_id) n FROM visits WHERE day >= ? GROUP BY day").bind(since(13)),
    db.prepare("SELECT site, SUM(day = ?) today, COUNT(DISTINCT CASE WHEN day >= ? THEN user_id END) week FROM visits WHERE day >= ? GROUP BY site").bind(today, since(6), since(29)),
  ]);
  const n = r => (r.results[0] || {}).n || 0;
  const by = (r, k) => Object.fromEntries(r.results.map(x => [x[k], x]));
  const su = by(signups, "day"), da = by(daily, "day"), st = by(sites, "site");
  const days = Array.from({ length: 14 }, (_, i) => since(i));
  const name = { "total-hq": "Total HQ", "slam-hq": "Slam", "slapshot-hq": "Slapshot", "touchdown-hq": "Touchdown", "futbol-hq": "Futbol", "moonshot-hq": "Moonshot" };
  const how = Object.fromEntries(methods.results.map(x => [x.method, x.n]));
  return hqaHtml(hqaPage("Admin · Total HQ", `
<div class="top"><a href="/">← Total HQ</a><span>Central time</span></div>
<h1>WHO'S <span>IN</span></h1>
<div class="stats">
  <div class="stat"><b>${n(tot)}</b><span>accounts</span></div>
  <div class="stat"><b>${n(wk)}</b><span>new in the last 7 days</span></div>
  <div class="stat"><b>${n(act)}</b><span>active today</span></div>
  <div class="stat"><b>${n(opt)}</b><span>want updates</span></div>
</div>
<p class="lede" style="margin-top:14px">Signed up with Apple ${how.apple || 0} · Google ${how.google || 0} · email ${how.email || 0}</p>
<h2>By site</h2>
<table><thead><tr><th>Site</th><th>Today</th><th>Last 7 days</th></tr></thead><tbody>
${HQA_SITES.map(s => `<tr><td>${name[s]}</td><td>${(st[s] || {}).today || 0}</td><td>${(st[s] || {}).week || 0}</td></tr>`).join("")}
</tbody></table>
<h2>Last 14 days</h2>
<table><thead><tr><th>Day</th><th>New accounts</th><th>Active people</th></tr></thead><tbody>
${days.map(d => `<tr><td>${new Date(d + "T12:00:00Z").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" })}</td><td>${(su[d] || {}).n || 0}</td><td>${(da[d] || {}).n || 0}</td></tr>`).join("")}
</tbody></table>`, true));
}

// ---------- routes ----------
async function hqaAuth(request, env, ctx, url) {
  const path = url.pathname, post = request.method === "POST";
  // forms only count when they come from this site (Apple's callback is the one cross-site post)
  if (post && path !== "/auth/apple/callback" && request.headers.get("Origin") !== url.origin) {
    if (/^\/(auth|account|logout)/.test(path)) return new Response("Forbidden", { status: 403 });
  }
  if (path === "/login") {
    const next = url.searchParams.get("next") || "/";
    const me = await hqaSession(request, env);
    return me ? hqaContinue(env, url, me.id, next) : hqaLogin(url, next);
  }
  if (path === "/privacy") return hqaHtml(HQA_PRIVACY);
  if (path === "/auth/email" && post) return hqaEmailStart(request, env, url);
  if (path === "/auth/email/verify" && post) return hqaEmailVerify(request, env, url);
  if (path === "/auth/google") return hqaGoogleStart(env, url);
  if (path === "/auth/google/callback") return hqaGoogleBack(request, env, url);
  if (path === "/auth/apple") return hqaAppleStart(env, url);
  if (path === "/auth/apple/callback" && post) return hqaAppleBack(request, env, url);
  if (path === "/auth/welcome") return hqaWelcome(request, env, url);
  if (path === "/account" || path.startsWith("/account/")) return hqaAccount(request, env, url, path);
  if (path === "/admin") return hqaAdmin(request, env, url);
  if (path === "/logout") {
    const me = await hqaSession(request, env);
    if (me && post) await env.ACCOUNTS.prepare("DELETE FROM sessions WHERE user_id = ?").bind(me.id).run();
    return hqaRedirect("/login", [hqaCookie("hq_s", "", 0)]);
  }
  return null;
}
// ==== /HQ SIGN-IN ====
