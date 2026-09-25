#!/usr/bin/env bash
# The whole FlightScout on this computer: the website at http://localhost:3000
# and the engine, with an embedded database (PGlite). No Vercel, no Docker, no
# accounts needed (guest mode, or sign up with an email in ALLOWED_SIGNUP_EMAILS).
# Everything runs until you press Ctrl+C, then stops.
#
#   ./scripts/run-local.sh            # from a clone of the repo
#
# Needs: node 22+, and either the flightscout command (scripts/install-runner.sh)
# or uv (the engine then runs from this checkout).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEB="$ROOT/web"
say() { printf '\033[1m%s\033[0m\n' "$*"; }
pids=()
cleanup() { for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

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

# 2. Website config (first run only): embedded database, local engine.
if [ ! -f "$WEB/.env.local" ]; then
  say "Creating web/.env.local (embedded database, local engine)"
  secret="$(openssl rand -hex 32 2>/dev/null || date +%s%N | shasum | cut -c1-64)"
  cat > "$WEB/.env.local" <<EOF
DATABASE_URL=pglite:./.pglite
BETTER_AUTH_SECRET=$secret
BETTER_AUTH_URL=http://localhost:3000
ALLOWED_SIGNUP_EMAILS=${FLIGHTSCOUT_EMAIL:-}
ENGINE_URL=http://127.0.0.1:8787
ENGINE_KEY=local
TRACKER_KEY=local
EOF
fi

cd "$WEB"
[ -d node_modules ] || { say "Installing website dependencies"; npm ci; }
say "Database"
npm run -s db:migrate
if [ ! -f .next/BUILD_ID ] || [ -n "$(find src -newer .next/BUILD_ID -type f | head -1)" ]; then
  say "Building the website (first run or after changes)"
  npm run -s build
fi
say "FlightScout on http://localhost:3000 (Ctrl+C to stop)"
npx next start -p 3000
