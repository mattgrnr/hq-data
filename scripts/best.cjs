// Tonight's best bets for one site, worked out by the site's own page code, for Total HQ's cross-sport list.
// usage: node scripts/best.cjs <site> <board.json> <out.json>
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const [site, boardPath, outPath] = process.argv.slice(2);
// how each site sets up its rows from a board (the same steps its page runs on load)
const SETUP = {
  slapshot: `BOARD = bd; SEASON = bd.season; DEFRANK = defRanks(bd.teams, bd.lg); POSRANK = posRanks(bd.teams); GAMES = parseSlate(bd); buildRows();`,
  slam: `BOARD = bd; INJ = {}; SEASON = bd.season; DEFRANK = defRanks(bd.teams); GAMES = parseSlate(bd); buildRows();`,
  touchdown: `PRO = { players: bd.players, dvp: bd.dvp, props: bd.props, evlinks: bd.evlinks, logcols: bd.logcols, cal: bd.cal };
    AVG = computeAverages(PRO.players); DVPBASE = dvpBaselines(PRO.dvp); DVPRANK = dvpRanks(PRO.dvp, DVPBASE);
    TBASE = tabBases(PRO.players); TDBASE = tabDvpBases(PRO.dvp); TRANK = tabRanks(PRO.dvp);
    GAMES = parseSlate(bd); SEASON = bd.season; WEEKNO = bd.week || 1; buildRows();`,
  futbol: `BOARD = bd; F.day = 0; buildRows();`,
};

(async () => {
  const bd = JSON.parse(fs.readFileSync(boardPath, "utf8"));
  const out = { built: new Date().toISOString(), site, bets: [] };
  if (bd.games && bd.games.length && bd.players && bd.players.length) {
    const mod = await import(path.resolve("sites", site, "worker.js"));
    const html = await (await mod.default.fetch(new Request("https://local/"), {}, {})).text();
    const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
    const code = scripts.find(c => c.includes("function buildRows")).replace(/\nboot\(false\);\s*$/, "\n");
    const stub = new Proxy(function () { return stub; }, { get: (t, k) => (k === Symbol.toPrimitive ? () => "" : stub) });
    const store = { getItem: () => null, setItem() {}, removeItem() {} };
    const ctx = { document: stub, window: stub, localStorage: store, navigator: stub, location: { hostname: "local", hash: "", search: "" },
      setTimeout: () => 0, setInterval: () => 0, clearInterval: () => 0, requestAnimationFrame: () => 0, console, Math, Date, JSON, bd };
    vm.createContext(ctx);
    vm.runInContext(code, ctx);
    vm.runInContext(SETUP[site], ctx);
    ctx.__days = [0, 1];
    out.bets = vm.runInContext(`(typeof F !== "undefined" && "day" in F ? __days : [null]).flatMap(d => { if(d != null) F.day = d;
      return gList().flatMap(g => bestBets(g).map(b => ({ leg: legOf((b.name+" "+b.label).trim(), b), ev: Math.round(b.ev*1000)/1000, score: Math.round(b.score*1000)/1000,
        edge: Math.round((b.ours-b.book)*1000)/1000, kind: b.kind }))); })`, ctx);
    const seen = new Set();
    out.bets = out.bets.filter(x => !seen.has(x.leg.i) && seen.add(x.leg.i)).sort((a, b) => b.score - a.score).slice(0, 25);
  }
  fs.writeFileSync(outPath, JSON.stringify(out));
  console.log(site + ": " + out.bets.length + " best bets");
})().catch(e => { console.error(e); process.exit(1); });
