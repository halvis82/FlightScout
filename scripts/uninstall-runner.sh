#!/bin/sh
# Remove the FlightScout local runner (and its scheduled watch checks), then
# the flightscout command. The website keeps working through the server.
#
#   curl -fsSL https://raw.githubusercontent.com/halvis82/FlightScout/main/scripts/uninstall-runner.sh | sh
set -eu
PATH="$HOME/.local/bin:$PATH"
if command -v flightscout >/dev/null 2>&1; then
  flightscout serve --uninstall || true
fi
if command -v uv >/dev/null 2>&1; then
  uv tool uninstall flightscout || true
fi
echo "FlightScout local runner removed."
