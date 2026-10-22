// Reads tonight's top rows straight off the live site, so posts always match the board.
// usage: node top.cjs <nba|nhl|nfl> <count>   -> JSON on stdout
const { chromium } = require("playwright");

const SITES = {
  nba: { url: "https://slam-hq.com/", name: "SLAM", league: "NBA", board: "Points", unit: "pts" },
  nhl: { url: "https://slapshot-hq.com/", name: "SLAPSHOT", league: "NHL", board: "Goals", unit: "sog" },
  nfl: { url: "https://touchdown-hq.com/", name: "TOUCHDOWN", league: "NFL", board: "Touchdowns", unit: "yds" },
};

(async () => {
  const sport = process.argv[2], count = +(process.argv[3] || 5);
  const site = SITES[sport];
  if (!site) throw new Error("unknown sport " + sport);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 430, height: 1200 } });
  await page.goto(site.url, { waitUntil: "networkidle", timeout: 90000 });
  await page.waitForSelector(".row, .status h2", { timeout: 90000 });
  await page.waitForTimeout(1500);
  const out = await page.evaluate((count) => {
    const txt = (el, sel) => { const e = el.querySelector(sel); return e ? e.textContent.trim() : ""; };
    const rows = [...document.querySelectorAll(".row")].slice(0, count).map((r) => {
      const meta = txt(r, ".meta");
      const team = meta.split("·")[0].trim();
      const g = meta.match(/([A-Z]{2,4}) @ ([A-Z]{2,4})/);
      const opp = g ? (g[1] === team ? g[2] : g[1]) : "";
      const name = txt(r, ".pn") || txt(r, ".pname");
      return { name, team, opp, home: g ? g[2] === team : null, score: +txt(r, ".num"), proj: txt(r, ".yproj b"), tier: txt(r, ".tierlabel") };
    });
    const games = (document.querySelector("#f-game") || { options: [] }).options.length - 1;
    return { label: txt(document, ".sub"), rows, games: Math.max(0, games) };
  }, count);
  await browser.close();
  console.log(JSON.stringify({ sport, ...site, ...out }));
})().catch((e) => { console.error(e); process.exit(1); });
