-- HQ accounts (D1 database hq-accounts). Nothing here is a password: sign-in is Apple, Google or a one-time email code.
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  method TEXT NOT NULL,              -- how they first signed up: apple, google, email
  apple_sub TEXT UNIQUE,
  google_sub TEXT UNIQUE,
  opt_in INTEGER NOT NULL DEFAULT 0, -- agreed to occasional updates
  admin INTEGER NOT NULL DEFAULT 0,  -- can open /admin
  age_ok INTEGER NOT NULL,           -- when they confirmed 21+
  created_at INTEGER NOT NULL,
  last_seen INTEGER NOT NULL
);
-- one row per signed-in browser per site; the cookie holds the token, this holds only its hash
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  site TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
-- email sign-in codes: hashed, ten minutes, five tries
CREATE TABLE IF NOT EXISTS codes (
  email TEXT PRIMARY KEY,
  code_hash TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  tries INTEGER NOT NULL DEFAULT 0,
  sent INTEGER NOT NULL DEFAULT 0,   -- codes sent in the current hour
  window_start INTEGER NOT NULL
);
-- a new sign-in waiting for the 21+ step
CREATE TABLE IF NOT EXISTS pending (
  token_hash TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  method TEXT NOT NULL,
  sub TEXT,
  next TEXT,
  expires_at INTEGER NOT NULL
);
-- one-time passes that carry a Total HQ sign-in over to a sport site (60 seconds)
CREATE TABLE IF NOT EXISTS handoffs (
  code_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  origin TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);
-- which sites each account opened, one row per day
CREATE TABLE IF NOT EXISTS visits (
  user_id TEXT NOT NULL,
  site TEXT NOT NULL,
  day TEXT NOT NULL,
  PRIMARY KEY (user_id, site, day)
);
CREATE INDEX IF NOT EXISTS visits_day ON visits(day);
