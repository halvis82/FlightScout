#!/bin/sh
# Turn on price alert emails for the online FlightScout (flightscout-app.vercel.app).
#
# Alerts are already computed twice a day and shown under the bell; this gives
# them a way out by email. Delivery is through Resend (https://resend.com,
# free for 3,000 emails a month):
#
#   1. Sign up at resend.com with the address your FlightScout account uses.
#   2. API Keys, Create API key (sending access is enough), copy it (re_...).
#   3. From the repo:  scripts/setup-email.sh re_your_key
#
# Without a verified domain Resend only delivers to the address of its own
# account, from "onboarding@resend.dev": fine for one person. To email others,
# verify a domain at resend.com and pass the sender: scripts/setup-email.sh re_key "FlightScout <alerts@your-domain.com>"
#
# The script checks the key, stores both values in the web project's Vercel
# production environment, keeps a copy in ~/.config/flightscout/deploy-secrets.env
# and redeploys the website. Then, in Settings, Alerts, switch on "Email to ...".
set -eu

KEY="${1:-}"
FROM="${2:-FlightScout <onboarding@resend.dev>}"
if [ -z "$KEY" ]; then
  echo "usage: scripts/setup-email.sh <resend api key> [from address]" >&2
  exit 2
fi
case "$KEY" in re_*) ;; *) echo "That doesn't look like a Resend API key (they start with re_)." >&2; exit 2 ;; esac

here=$(cd "$(dirname "$0")/.." && pwd)
web="$here/web"
command -v vercel >/dev/null 2>&1 || { echo "Install the Vercel CLI first: npm i -g vercel" >&2; exit 1; }

echo "Checking the key with Resend..."
code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $KEY" https://api.resend.com/domains)
case "$code" in
  200) ;;
  401|403) echo "Resend rejected the key (HTTP $code). Copy it again from resend.com, API Keys." >&2; exit 1 ;;
  *) echo "Could not reach Resend (HTTP $code). Check your connection and try again." >&2; exit 1 ;;
esac

cd "$web"
[ -f .vercel/project.json ] || vercel link --yes --project flightscout >/dev/null

set_env() {  # name value: replace in production
  vercel env rm "$1" production --yes >/dev/null 2>&1 || true
  printf '%s' "$2" | vercel env add "$1" production >/dev/null
  echo "  $1 set"
}
echo "Saving to Vercel (production)..."
set_env RESEND_API_KEY "$KEY"
set_env ALERT_FROM_EMAIL "$FROM"

conf="${FLIGHTSCOUT_HOME:-$HOME/.config/flightscout}"
mkdir -p "$conf"
secrets="$conf/deploy-secrets.env"
touch "$secrets"
chmod 600 "$secrets"
grep -v '^RESEND_API_KEY=\|^ALERT_FROM_EMAIL=' "$secrets" > "$secrets.tmp" || true
printf 'RESEND_API_KEY=%s\nALERT_FROM_EMAIL=%s\n' "$KEY" "$FROM" >> "$secrets.tmp"
mv "$secrets.tmp" "$secrets"
echo "  copy kept in $secrets"

echo "Redeploying the website so it picks the values up..."
current=$(vercel ls flightscout --prod 2>/dev/null | grep -o 'https://[^ ]*' | head -1 || true)
if [ -n "$current" ]; then
  vercel redeploy "$current" >/dev/null && echo "  redeployed"
else
  echo "  could not find the current deployment; push any commit or run: cd web && vercel --prod" >&2
fi

cat <<EOF

Done. Last step, once the deploy shows Ready (a minute or two):
  open https://flightscout-app.vercel.app/settings, Alerts, switch on "Email to <your address>".

You get an email when a watch meets its alert (price under its target, or a
drop of the chosen percentage since the last check), at most once per 12 hours
per watch. Set targets per watch in the Watchlist.
EOF
