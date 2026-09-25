#!/usr/bin/env bash
# The whole FlightScout on this computer: the website at http://localhost:3000
# and the engine, every feature (accounts and login, watchlist and price
# tracking, alerts in the page, explore, smart routes), no rate limits, and
# searches from your own IP. Runs until you press Ctrl+C, then stops.
#
#   ./scripts/run-local.sh            your own data, kept on this computer
#   ./scripts/run-local.sh --shared   the same accounts and watchlist as the online site
#
# --shared needs the online site's database address, read from
# ~/.config/flightscout/local.env (DATABASE_URL=...). If it's missing and the
# Vercel CLI is logged in, it's fetched from the Vercel project
# (FLIGHTSCOUT_VERCEL_PROJECT, default "flightscout"; FLIGHTSCOUT_VERCEL_SCOPE
# for a team).
#
# Needs: node 22+, and the flightscout command (scripts/install-runner.sh) or uv.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEB="$ROOT/web"
CONF="$HOME/.config/flightscout"
MODE="own"
[ "${1:-}" = "--shared" ] && MODE="shared"
say() { printf '\033[1m%s\033[0m\n' "$*"; }
pids=()
cleanup() { for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM
mkdir -p "$CONF" && chmod 700 "$CONF"

# 1. Engine: the on demand runner if it's installed, else run it for this session.
if curl -s -m 8 http://127.0.0.1:8787/health | grep -q '"local":true'; then
  say "Engine: local runner on :8787"
else
  say "Engine: starting on :8787 for this session"
  if command -v flightscout >/dev/null 2>&1; then
    flightscout serve & pids+=($!)
  else
    (cd "$ROOT/engine" && FLIGHTSCOUT_LOCAL=1 uv run --extra browser uvicorn flightscout.api:app --app-dir src \
      --host 127.0.0.1 --port 8787 --log-level warning) & pids+=($!)
  fi
  for _ in $(seq 1 60); do curl -s -m 2 http://127.0.0.1:8787/health >/dev/null && break; sleep 1; done
fi

# 2. Settings for this run (environment only; web/.env.local is left alone).
[ -f "$CONF/local-secret" ] || { openssl rand -hex 32 > "$CONF/local-secret"; chmod 600 "$CONF/local-secret"; }
export BETTER_AUTH_SECRET="$(cat "$CONF/local-secret")"
export BETTER_AUTH_URL=http://localhost:3000
export ENGINE_URL=http://127.0.0.1:8787 ENGINE_KEY=local TRACKER_KEY="${TRACKER_KEY:-local-$(cut -c1-16 "$CONF/local-secret")}"
export FLIGHTSCOUT_NO_RATE_LIMIT=1
if [ "$MODE" = "shared" ]; then
  if ! grep -q '^DATABASE_URL=' "$CONF/local.env" 2>/dev/null; then
    say "Fetching the online site's database address from Vercel"
    tmp="$(mktemp)"
    (cd "$WEB" && npx -y vercel env pull "$tmp" --environment=production --yes \
      --project "${FLIGHTSCOUT_VERCEL_PROJECT:-flightscout}" ${FLIGHTSCOUT_VERCEL_SCOPE:+--scope "$FLIGHTSCOUT_VERCEL_SCOPE"} >/dev/null)
    grep -E '^(DATABASE_URL|ALLOWED_SIGNUP_EMAILS)=' "$tmp" > "$CONF/local.env"; rm -f "$tmp"; chmod 600 "$CONF/local.env"
  fi
  set -a; . "$CONF/local.env"; set +a
  export DATABASE_URL="${DATABASE_URL//\"/}" NEXT_PUBLIC_OPEN_SIGNUP=0
  say "Data: the online database (same accounts and watchlist as the website)"
else
  export DATABASE_URL="pglite:$WEB/.pglite" ALLOWED_SIGNUP_EMAILS='*' NEXT_PUBLIC_OPEN_SIGNUP=1
  say "Data: on this computer (web/.pglite), anyone can make an account here"
fi

# 3. Build (first run, after code changes, or when switching mode) and start.
cd "$WEB"
[ -d node_modules ] || { say "Installing website dependencies"; npm ci; }
say "Database"
npm run -s db:migrate
if [ ! -f .next/BUILD_ID ] || [ "$(cat .next/fs-mode 2>/dev/null)" != "$MODE" ] || [ -n "$(find src -newer .next/BUILD_ID -type f | head -1)" ]; then
  say "Building the website"
  npm run -s build
  echo "$MODE" > .next/fs-mode
fi

# 4. Own data: nobody else checks your watches, so do it while this runs
#    (10 minutes after start, then every 12 hours). Shared data is checked
#    by the online site's tracker.
if [ "$MODE" = "own" ] && command -v flightscout >/dev/null 2>&1; then
  (sleep 600; while true; do
     FLIGHTSCOUT_API_URL=http://localhost:3000 FLIGHTSCOUT_TRACKER_KEY="$TRACKER_KEY" flightscout track >/dev/null 2>&1 || true
     sleep 43200
   done) & pids+=($!)
fi

say "FlightScout on http://localhost:3000 (Ctrl+C to stop)"
npx next start -p 3000
