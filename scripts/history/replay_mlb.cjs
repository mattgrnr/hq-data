// Replay Moonshot's own board for every day of a saved MLB season (mlb/raw, from mlb_season.py).
// The site's build() runs unchanged; its API calls are answered from the saved season as of that
// morning: stats through the day before, the day's starting pitchers and lineups, and the weather.
// usage: node scripts/history/replay_mlb.cjs [from YYYY-MM-DD] [to YYYY-MM-DD]
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const RAW = path.join(ROOT, "mlb", "raw");
const OUTDIR = path.join(ROOT, "mlb", "history", "picks");
const [FROM, TO] = process.argv.slice(2);

function csvRows(file) {
  const lines = zlib.gunzipSync(fs.readFileSync(path.join(RAW, file))).toString().trim().split("\n");
  const head = lines.shift().split(",");
  return lines.map(l => { const v = l.split(","), o = {}; head.forEach((h, i) => (o[h] = v[i])); return o; });
}
const games = JSON.parse(fs.readFileSync(path.join(RAW, "games.json"), "utf8"));
const people = JSON.parse(fs.readFileSync(path.join(RAW, "people.json"), "utf8"));
const pa = csvRows("pa.csv.gz");
const pitch = csvRows("pitch.csv.gz");
const wx = {};
for (const f of fs.existsSync(path.join(RAW, "wx")) ? fs.readdirSync(path.join(RAW, "wx")) : [])
  wx[f.replace(".json", "")] = JSON.parse(fs.readFileSync(path.join(RAW, "wx", f), "utf8"));

// indexes
const byBatter = {}, byPitcherPA = {}, pitchLog = {};
for (const r of pa) {
  r.hit = +r.hit; r.ab = +r.ab;
  (byBatter[r.b] ||= []).push(r);
}
for (const r of pitch) (pitchLog[r.p] ||= []).push(r);
const byDate = {};
for (const g of games) (byDate[g.date] ||= []).push(g);

function line(rows) {
  const st = { plateAppearances: rows.length, atBats: 0, hits: 0, doubles: 0, triples: 0, homeRuns: 0, totalBases: 0 };
  for (const r of rows) {
    st.atBats += r.ab;
    if (r.hit) { st.hits++; st.totalBases += r.hit; }
    if (r.hit === 2) st.doubles++;
    if (r.hit === 3) st.triples++;
    if (r.hit === 4) st.homeRuns++;
  }
  return st;
}
const outs = ip => { const [w, f] = String(ip).split("."); return 3 * (+w || 0) + (+f || 0); };
const ipStr = o => Math.floor(o / 3) + "." + (o % 3);

let TODAY = "";
function api(url) {
  const u = new URL(url, "https://x");
  const q = u.searchParams, p = u.pathname;
  if (p.endsWith("/schedule")) {
    const d = q.get("date");
    if (!d) return { dates: [] };
    return { dates: [{ games: (byDate[d] || []).map(g => ({
      gamePk: g.pk, gameDate: g.t, gameNumber: g.gn,
      teams: Object.fromEntries(["home", "away"].map(s => [s, { team: { id: g[s].id, abbreviation: g[s].abbr },
        probablePitcher: g[s].sp ? { id: g[s].sp, fullName: (people[g[s].sp] || {}).n } : undefined }])),
      lineups: { homePlayers: g.home.lineup.map(id => ({ id, fullName: (people[id] || {}).n })),
                 awayPlayers: g.away.lineup.map(id => ({ id, fullName: (people[id] || {}).n })) },
    })) }] };
  }
  if (p.endsWith("/people")) {
    return { people: q.get("personIds").split(",").map(id => {
      const x = people[id] || {};
      return { id: +id, fullName: x.n, batSide: { code: x.b || "R" }, pitchHand: { code: x.p || "R" } };
    }) };
  }
  let m = p.match(/\/people\/(\d+)\/stats$/);
  if (m && q.get("group") === "hitting" && q.get("stats") === "vsPlayerTotal") {
    const rows = (byBatter[m[1]] || []).filter(r => r.date < TODAY && r.p === q.get("opposingPlayerId"));
    return { stats: rows.length ? [{ splits: [{ stat: line(rows) }] }] : [] };
  }
  if (m && q.get("group") === "hitting") {
    const before = (byBatter[m[1]] || []).filter(r => r.date < TODAY);
    if (!before.length) return { stats: [] };
    const recent = before.filter(r => r.date >= q.get("startDate") && r.date <= q.get("endDate"));
    const out = [{ type: { displayName: "season" }, splits: [{ stat: line(before) }] }];
    if (recent.length) out.push({ type: { displayName: "byDateRange" }, splits: [{ stat: line(recent) }] });
    out.push({ type: { displayName: "statSplits" }, splits: ["L", "R"].map(h => {
      const rows = before.filter(r => r.ph === h);
      return rows.length ? { split: { code: "v" + h.toLowerCase() }, stat: line(rows) } : null;
    }).filter(Boolean) });
    return { stats: out };
  }
  if (m && q.get("group") === "pitching") {
    const log = (pitchLog[m[1]] || []).filter(r => r.date < TODAY);
    if (!log.length) return { stats: [] };
    const o = log.reduce((a, r) => a + outs(r.ip), 0), hr = log.reduce((a, r) => a + +r.hr, 0);
    return { stats: [
      { type: { displayName: "season" }, splits: [{ stat: { inningsPitched: ipStr(o), homeRuns: hr } }] },
      { type: { displayName: "gameLog" }, splits: log.map(r => ({ date: r.date, stat: { inningsPitched: r.ip, homeRuns: +r.hr } })) },
    ] };
  }
  if (/\/game\/\d+\/boxscore$/.test(p)) return { teams: {} };   // nothing has happened yet
  if (p.includes("/meteo/")) {
    const team = PARK_BY_LAT[q.get("latitude")];
    const h = wx[team];
    if (!h) throw new Error("no weather");
    const a = q.get("start_date"), b = q.get("end_date") + "T23";
    const keep = h.time.map((t, i) => (t >= a && t <= b ? i : -1)).filter(i => i >= 0);
    const hourly = {};
    for (const k of Object.keys(h)) hourly[k] = keep.map(i => h[k][i]);
    return { hourly };
  }
  throw new Error("unhandled " + url);
}

// the site's page script, run as-is with fetch and the clock pointed at the saved season
const PARK_BY_LAT = {};
async function loadModel() {
  const mod = await import(path.join(ROOT, "sites", "moonshot", "worker.js"));
  const html = await (await mod.default.fetch(new Request("https://local/"), {}, {})).text();
  const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
  const code = scripts.find(c => c.includes("async function build(")).replace(/\ninitLang\(\)\.then\([^\n]*\n?\s*$/, "\n");
  const stub = new Proxy(function () { return stub; }, { get: (t, k) => (k === Symbol.toPrimitive ? () => "" : stub) });
  const RealDate = Date;
  class FakeDate extends RealDate {
    constructor(...a) { if (a.length) super(...a); else super(TODAY + "T16:00:00Z"); }
    static now() { return new RealDate(TODAY + "T16:00:00Z").getTime(); }
  }
  const ctx = { document: stub, window: stub, localStorage: { getItem: () => null, setItem() {}, removeItem() {}, key: () => null, length: 0 },
    navigator: { language: "en" }, location: { search: "", hostname: "local" },
    setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {}, requestAnimationFrame: () => 0,
    console, Math, JSON, Date: FakeDate, URLSearchParams, Promise,
    fetch: async url => {
      if (String(url).includes("/savant")) return { ok: true, text: async () => "" };
      try { const body = api(url); return { ok: true, json: async () => body }; }
      catch (e) { return { ok: false, status: 404, json: async () => ({}) }; }
    } };
  vm.createContext(ctx);
  vm.runInContext(code + "\n;globalThis.__build = build; globalThis.__parks = PARKS; globalThis.__lg = LG; globalThis.__cfg = CONFIG;", ctx);
  ctx.__cfg.BOARD_CACHE = false;
  for (const [team, p] of Object.entries(ctx.__parks)) PARK_BY_LAT[String(p.lat)] = team;
  return ctx;
}

(async () => {
  const ctx = await loadModel();
  const LG = ctx.__lg;
  fs.mkdirSync(OUTDIR, { recursive: true });
  const dates = Object.keys(byDate).sort().filter(d => (!FROM || d >= FROM) && (!TO || d <= TO));
  for (const d of dates) {
    TODAY = d;
    const sched = api("/api/v1/schedule?sportId=1&date=" + d).dates[0].games;
    const board = await ctx.__build(sched, d, () => {});
    if (!board.results.length) { console.log(d + ": no scored hitters"); continue; }
    if (process.env.DUMP) fs.writeFileSync(process.env.DUMP, JSON.stringify(board));
    if (process.env.DEBUG) console.log(JSON.stringify(board.results.slice(0, 3).map(r => [r.name, r.ix, r.wx && r.wx.index])));
    const out = { key: d, stats: ["HR"], games: {}, picks: {}, scored: new Date(Math.min(...byDate[d].map(g => Date.parse(g.t))) - 3600e3).toISOString(), replay: true };
    for (const g of byDate[d]) {
      out.games[String(g.pk)] = { home: g.home.abbr, away: g.away.abbr, start: g.t };
      out.picks[String(g.pk)] = [];
    }
    for (const r of board.results) {
      // expected homers: league rate per PA, times plate appearances for his lineup spot, times the board's index
      const pas = 4.65 - 0.11 * (r.spot - 1);
      const pj = Math.round(LG.HR_PER_PA * pas * (r.score / 50) * 1000) / 1000;
      (out.picks[String(r.gameId)] ||= []).push({ id: r.id, n: r.name, t: r.teamAbbr, pos: "", g: String(r.gameId), s: { HR: r.score }, pj: { HR: pj } });
    }
    fs.writeFileSync(path.join(OUTDIR, d + ".json"), JSON.stringify(out));
    console.log(`${d}: ${board.games} games, ${board.results.length} hitters`);
  }
})().catch(e => { console.error(e); process.exit(1); });
