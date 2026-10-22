# hq-data

Data feeds for the HQ boards.

- `nfl/board.json` — Touchdown HQ's weekly board, rebuilt on a schedule by `.github/workflows/nfl.yml`.
- `nhl/board.json` — Slapshot HQ's daily board, rebuilt on a schedule by `.github/workflows/nhl.yml`.

Source data: [nflverse](https://github.com/nflverse) and [sportsdataverse](https://github.com/sportsdataverse).

## Sites

`sites/<name>/` holds each board's Worker. Pushing to `main` deploys changed sites with `.github/workflows/deploy.yml`; pushing to a `preview/<name>` branch posts a preview link instead. Needs repository secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.
