// Score a saved board with the site's own model and fold the picks into that day's history file.
// A game's picks are only taken while it hasn't started, so each game keeps its last pregame snapshot.
// usage: node scripts/history/score.cjs <site> <board.json> <history dir> [--now ISO]
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const [site, boardPath, outDir, flag, nowArg] = process.argv.slice(2);
const NOW = flag === "--now" ? Date.parse(nowArg) : Date.now();
const CT = "America/Chicago";
const ctDate = ms => new Date(ms).toLocaleDateString("en-CA", { timeZone: CT });

// each site: how to build its rows, and how to read stats, projections and games from them
const SITES = {
  slapshot: {
    stats: ["G", "A", "P", "S"],
    run: `BOARD = bd; SEASON = bd.season; DEFRANK = defRanks(bd.teams, bd.lg); POSRANK = posRanks(bd.teams);
      GAMES = parseSlate(bd); buildRows();
      ROWS.map(r => ({ id: r.p.id, n: r.p.name, t: r.p.team, pos: r.p.pos, g: String(r.gm.gid),
        s: { G: r.score, A: r.scoreA, P: r.scoreP, S: r.scoreS }, pj: { G: r.projG, A: r.projA, P: r.projP, S: r.projS } }))`,
    games: bd => bd.games.map(g => ({ key: String(g.id), start: Date.parse(String(g.start).replace("Z", ":00Z")), home: g.home, away: g.away })),
    file: (bd, g) => bd.date,
  },
  slam: {
    stats: ["PTS", "PRA", "REB", "AST", "3PM", "BLK", "STL"],
    run: `BOARD = bd; INJ = {}; SEASON = bd.season; DEFRANK = defRanks(bd.teams); GAMES = parseSlate(bd); buildRows();
      ROWS.map(r => { const s = {}, pj = {};
        for(const k of STATS){ s[k] = r.score[KEY[k]]; pj[k] = Math.round(r.proj[KEY[k]]*10)/10; }
        return { id: r.p.id, n: r.p.name, t: r.p.team, pos: r.p.pos, g: String(r.gm.gid), s, pj }; })`,
    games: bd => bd.games.map(g => ({ key: String(g.id), start: Date.parse(String(g.start).replace("Z", ":00Z")), home: g.home, away: g.away })),
    file: (bd, g) => bd.date,
  },
  touchdown: {
    stats: ["TD", "CYD", "RYD", "REC", "PYD", "PTD"],
    run: `PRO = { players: bd.players, dvp: bd.dvp }; AVG = computeAverages(PRO.players);
      DVPBASE = dvpBaselines(PRO.dvp); DVPRANK = dvpRanks(PRO.dvp, DVPBASE);
      TBASE = tabBases(PRO.players); TDBASE = tabDvpBases(PRO.dvp); TRANK = tabRanks(PRO.dvp);
      GAMES = parseSlate(bd); SEASON = bd.season; WEEKNO = bd.week || 1; buildRows();
      ROWS.map(r => { const s = { TD: r.score }, pj = { TD: r.projTD };
        for(const k of ["CYD","RYD","REC","PYD","PTD"]){ const x = r.tab[k]; if(x && TABINFO[k].pos.includes(r.p.pos)){ s[k] = x.score; pj[k] = Math.round(x.proj*10)/10; } }
        return { id: r.p.id, n: r.p.name, t: r.p.team, pos: r.p.pos, g: r.gm.away + "@" + r.gm.home, s, pj }; })`,
    games: bd => bd.games.map(g => ({ key: g.away + "@" + g.home, start: g.ko * 1000, home: g.home, away: g.away })),
    file: (bd, g) => bd.season + "-w" + String(bd.week).padStart(2, "0"),
  },
  futbol: {
    stats: ["G", "T", "S", "A"],
    run: `BOARD = bd; buildRows();
      ROWS.map(r => ({ id: r.p.id, n: r.p.n, t: r.team, pos: r.p.pos, g: String(r.gm.id),
        s: { G: r.sc.G, T: r.sc.T, S: r.sc.S, A: r.sc.A }, pj: { G: r.p.pg, T: r.p.psot, S: r.p.psh, A: r.p.pa } }))`,
    games: bd => bd.games.map(g => ({ key: String(g.id), start: Date.parse(g.t), home: g.h, away: g.a, league: g.league })),
    file: (bd, g) => ctDate(g.start),
  },
};

async function rowsFor(cfg, bd) {
  const mod = await import(path.resolve("sites", site, "worker.js"));
  const html = await (await mod.default.fetch(new Request("https://local/"), {}, {})).text();
  const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
  const code = scripts.find(c => c.includes("function buildRows")).replace(/\nboot\(false\);\s*$/, "\n");
  const stub = new Proxy(function () { return stub; }, { get: (t, k) => (k === Symbol.toPrimitive ? () => "" : stub) });
  const ctx = { document: stub, window: stub, localStorage: stub, navigator: stub, location: stub,
    setTimeout: () => 0, setInterval: () => 0, clearInterval: () => 0, requestAnimationFrame: () => 0,
    console, Math, Date, JSON, bd };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return vm.runInContext(cfg.run, ctx);
}

(async () => {
  const cfg = SITES[site];
  if (!cfg) throw new Error("unknown site " + site);
  const bd = JSON.parse(fs.readFileSync(boardPath, "utf8"));
  if (!bd.games || !bd.games.length || !bd.players || !bd.players.length) { console.log("no games, skipped"); return; }
  const games = cfg.games(bd).filter(g => g.start && NOW < g.start - 5 * 60 * 1000);
  if (!games.length) { console.log("every game under way, kept the earlier snapshots"); return; }
  const picks = await rowsFor(cfg, bd);
  const byFile = {};
  for (const g of games) (byFile[cfg.file(bd, g)] ||= []).push(g);
  fs.mkdirSync(outDir, { recursive: true });
  for (const [key, gs] of Object.entries(byFile)) {
    const f = path.join(outDir, key + ".json");
    const out = fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, "utf8")) : { key, stats: cfg.stats, games: {}, picks: {} };
    for (const g of gs) {
      out.games[g.key] = { home: g.home, away: g.away, start: new Date(g.start).toISOString(), ...(g.league ? { league: g.league } : {}) };
      out.picks[g.key] = picks.filter(p => p.g === g.key);
    }
    out.scored = new Date(NOW).toISOString();
    fs.writeFileSync(f, JSON.stringify(out));
    console.log(`${key}: ${gs.length} games refreshed, ${Object.keys(out.games).length} on file`);
  }
})().catch(e => { console.error(e); process.exit(1); });
