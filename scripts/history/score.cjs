// Score a saved board with the site's own model and write the picks.
// usage: node scripts/history/score.cjs <site> <board.json> <out.json> [--pregame]
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const [site, boardPath, outPath, flag] = process.argv.slice(2);
const SITES = {
  slapshot: {
    stats: ["G", "A", "P", "S"],
    run: `
      BOARD = bd; SEASON = bd.season;
      DEFRANK = defRanks(bd.teams, bd.lg); POSRANK = posRanks(bd.teams);
      GAMES = parseSlate(bd); buildRows();
      ROWS.map(r => ({ id: r.p.id, n: r.p.name, t: r.p.team, pos: r.p.pos, g: r.gm.gid,
        s: { G: r.score, A: r.scoreA, P: r.scoreP, S: r.scoreS },
        pj: { G: r.projG, A: r.projA, P: r.projP, S: r.projS } }))`,
  },
};

(async () => {
  const cfg = SITES[site];
  if (!cfg) throw new Error("unknown site " + site);
  const bd = JSON.parse(fs.readFileSync(boardPath, "utf8"));
  if (!bd.games || !bd.games.length) { console.log("no games, skipped"); return; }
  if (flag === "--pregame") {
    const first = Math.min(...bd.games.map(g => Date.parse(String(g.start).replace("Z", ":00Z")) || Infinity));
    if (Date.now() > first - 5 * 60 * 1000) { console.log("games under way, kept the earlier snapshot"); return; }
  }
  const mod = await import(path.resolve("sites", site, "worker.js"));
  const html = await (await mod.default.fetch(new Request("https://local/"), {}, {})).text();
  const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
  let code = scripts.find(c => c.includes("function buildRows"));
  code = code.replace(/\nboot\(false\);\s*$/, "\n");
  const stub = new Proxy(function () { return stub; }, { get: (t, k) => (k === Symbol.toPrimitive ? () => "" : stub) });
  const ctx = { document: stub, window: stub, localStorage: stub, navigator: stub, location: stub,
    setTimeout: () => 0, requestAnimationFrame: () => 0, setInterval: () => 0, clearInterval: () => 0, console, Math, Date, JSON, bd };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  const picks = vm.runInContext(cfg.run, ctx);
  const out = { date: bd.date, built: bd.built, scored: new Date().toISOString(), stats: cfg.stats,
    games: bd.games.map(g => ({ id: g.id, home: g.home, away: g.away, start: g.start })), picks };
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, JSON.stringify(out));
  console.log(`${bd.date}: ${picks.length} picks`);
})().catch(e => { console.error(e); process.exit(1); });
