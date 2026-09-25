#!/bin/sh
# The whole FlightScout on your computer, running only while it's open in your
# browser: open http://localhost:3000 and it starts (a few seconds the first
# time), close the tab and it stops a couple of minutes later. Every feature,
# accounts and login included, no limits, searches from your own IP.
#
#   curl -fsSL https://raw.githubusercontent.com/halvis82/FlightScout/main/scripts/install-local.sh | sh
#   curl -fsSL https://raw.githubusercontent.com/halvis82/FlightScout/main/scripts/install-local.sh | sh -s -- --shared
#
# --shared: use the online site's accounts and watchlist (needs its database
# address in ~/.config/flightscout/local.env as DATABASE_URL=...).
# macOS and Linux. Updates: `flightscout local update`. Remove: `flightscout local uninstall`.
set -eu

REPO_URL="${FLIGHTSCOUT_REPO:-https://github.com/halvis82/FlightScout}"
DIR="${FLIGHTSCOUT_DIR:-$HOME/.local/share/flightscout/FlightScout}"
CONF="$HOME/.config/flightscout"
say() { printf '\033[1m%s\033[0m\n' "$*"; }
mkdir -p "$CONF"

# 1. uv (small Python installer) and the flightscout command
if ! command -v uv >/dev/null 2>&1; then
  say "Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
PATH="$HOME/.local/bin:$PATH"
say "Installing the flightscout command"
uv tool install --force --reinstall --python 3.12 "flightscout[browser] @ git+${REPO_URL}#subdirectory=engine" >/dev/null

# 2. Node.js 22+ (only if missing: installed for FlightScout alone, no admin rights)
NODE="$(command -v node || true)"
if [ -z "$NODE" ] || [ "$("$NODE" -p 'process.versions.node.split(".")[0]')" -lt 22 ]; then
  say "Installing Node.js for FlightScout (in $CONF/node)"
  os="$(uname -s | tr 'A-Z' 'a-z')"; arch="$(uname -m)"
  case "$arch" in x86_64) arch=x64 ;; aarch64|arm64) arch=arm64 ;; esac
  ver="$(curl -fsSL https://nodejs.org/dist/index.json | python3 -c 'import json,sys;print(next(r["version"] for r in json.load(sys.stdin) if r["version"].startswith("v22.")))')"
  rm -rf "$CONF/node" && mkdir -p "$CONF/node"
  curl -fsSL "https://nodejs.org/dist/$ver/node-$ver-$os-$arch.tar.gz" | tar -xz -C "$CONF/node" --strip-components 1
  NODE="$CONF/node/bin/node"
fi

# 3. The code
if [ -d "$DIR/.git" ]; then
  say "Updating $DIR"
  git -C "$DIR" pull --ff-only
else
  say "Downloading FlightScout into $DIR"
  mkdir -p "$(dirname "$DIR")"
  git clone --depth 1 "$REPO_URL" "$DIR"
fi

# 4. Build and register (starts only when you open it)
flightscout local install --repo "$DIR" --node "$NODE" "$@"

if command -v open >/dev/null 2>&1; then open "http://localhost:3000"; fi
