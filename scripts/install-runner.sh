#!/bin/sh
# FlightScout local runner: searches run from your computer (your own IP)
# instead of the shared server, with the same website. It starts only when
# the website searches and stops after 10 quiet minutes (nothing runs in the
# background otherwise). macOS and Linux (systemd).
#
#   curl -fsSL https://raw.githubusercontent.com/halvis82/FlightScout/main/scripts/install-runner.sh | sh
#
# Remove: curl -fsSL https://raw.githubusercontent.com/halvis82/FlightScout/main/scripts/uninstall-runner.sh | sh
set -eu

REPO="${FLIGHTSCOUT_REPO:-https://github.com/halvis82/FlightScout}"
say() { printf '\033[1m%s\033[0m\n' "$*"; }

if ! command -v uv >/dev/null 2>&1; then
  say "Installing uv (Python tool installer, one file in ~/.local/bin)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$PATH"
fi

say "Installing the flightscout command"
uv tool install --force --reinstall --python 3.12 "flightscout[browser] @ git+${REPO}#subdirectory=engine"
PATH="$HOME/.local/bin:$PATH"

if [ -d "/Applications/Google Chrome.app" ] || command -v google-chrome >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1; then
  say "Google Chrome found: airlines and booking sites that need a browser are on (headless, no windows)"
else
  say "No Google Chrome found: everything works except the browser read airlines and booking sites (install Chrome to add them)"
fi

say "Setting up the on demand runner"
flightscout serve --install

say "Done. Open the website: the header shows \"Your IP\" when it's in use."
say "Optional: \`flightscout login\` then \`flightscout serve --install --track\` also checks your watches from this computer twice a day."
