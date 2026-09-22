#!/usr/bin/env bash
# One command self-hosting for FlightScout on your own free accounts:
# Vercel (site + engine), Neon Postgres (via Vercel Marketplace) and GitHub
# Actions (daily price tracking). Run from a fork or clone of the repo:
#
#   ./scripts/setup.sh [site-name] [your-email]
#
# If <site-name>.vercel.app is taken, Vercel picks another domain; set
# SITE_DOMAIN=my-name.vercel.app to force the one you added.
#
# Needs: git, gh (logged in), vercel CLI (logged in), node, openssl, python3.
# Safe to re-run: existing projects and keys are reused.
set -euo pipefail

SITE="${1:-flightscout-$(whoami | tr -cd 'a-z0-9' | cut -c1-12)}"
EMAIL="${2:-$(git config user.email || true)}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SECRETS="$HOME/.config/flightscout/deploy-secrets.env"
REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null || { echo "Missing $1"; exit 1; }; }
for c in git gh vercel node openssl python3; do need "$c"; done
vercel whoami >/dev/null 2>&1 || { echo "Run: vercel login"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Run: gh auth login"; exit 1; }

say "1/6 Secrets (stored only in $SECRETS, Vercel and GitHub)"
mkdir -p "$(dirname "$SECRETS")"
touch "$SECRETS" && chmod 600 "$SECRETS"
# shellcheck disable=SC1090
source "$SECRETS"
add() { grep -q "^$1=" "$SECRETS" || echo "$1=$2" >> "$SECRETS"; }
add ENGINE_KEY "$(openssl rand -hex 32)"
add TRACKER_KEY "$(openssl rand -hex 32)"
add BETTER_AUTH_SECRET "$(openssl rand -hex 32)"
add CRON_SECRET "$(openssl rand -hex 32)"
if ! grep -q '^VAPID_PUBLIC=' "$SECRETS"; then
  keys=$(npx -y web-push generate-vapid-keys --json)
  add VAPID_PUBLIC "$(echo "$keys" | python3 -c 'import json,sys;print(json.load(sys.stdin)["publicKey"])')"
  add VAPID_PRIVATE "$(echo "$keys" | python3 -c 'import json,sys;print(json.load(sys.stdin)["privateKey"])')"
fi
# shellcheck disable=SC1090
source "$SECRETS"

TOKEN=$(python3 - <<'PY'
import json, os, sys
for p in ("~/Library/Application Support/com.vercel.cli/auth.json", "~/.local/share/com.vercel.cli/auth.json"):
    p = os.path.expanduser(p)
    if os.path.exists(p):
        print(json.load(open(p))["token"]); sys.exit()
PY
)
api() { curl -fsS -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' "$@"; }
TEAM=$(api https://api.vercel.com/v2/user | python3 -c 'import json,sys;print(json.load(sys.stdin)["user"].get("defaultTeamId") or "")')
Q=${TEAM:+?teamId=$TEAM}
ORG=${TEAM:-$(api https://api.vercel.com/v2/user | python3 -c 'import json,sys;print(json.load(sys.stdin)["user"]["id"])')}

project() { # name rootDir framework
  local id
  id=$(api "https://api.vercel.com/v9/projects/$1$Q" 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])' || true)
  if [ -z "$id" ]; then
    id=$(api -X POST "https://api.vercel.com/v11/projects$Q" -d "{\"name\":\"$1\",\"rootDirectory\":\"$2\",${3:+\"framework\":\"$3\",}\"gitRepository\":{\"type\":\"github\",\"repo\":\"$REPO\"}}" \
      | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
  fi
  api -X PATCH "https://api.vercel.com/v9/projects/$id$Q" -d '{"commandForIgnoringBuildStep":"git diff --quiet HEAD^ HEAD -- . || exit 1"}' >/dev/null
  echo "$id"
}
link_dir() { # projectId name -> temp dir linked to it
  local d; d=$(mktemp -d); mkdir -p "$d/.vercel"
  echo "{\"projectId\":\"$1\",\"orgId\":\"$ORG\",\"projectName\":\"$2\"}" > "$d/.vercel/project.json"
  echo "$d"
}
setenv() { # dir name value
  for e in production preview; do printf '%s' "$3" | (cd "$1" && vercel env add "$2" "$e" --force >/dev/null 2>&1); done
}

say "2/6 Engine project ($SITE-engine)"
EID=$(project "$SITE-engine" engine "")
ED=$(link_dir "$EID" "$SITE-engine")
setenv "$ED" ENGINE_KEY "$ENGINE_KEY"

say "3/6 Web project ($SITE)"
WID=$(project "$SITE" web nextjs)
WD=$(link_dir "$WID" "$SITE")
pick_domain() { # projectId -> preferred <name>.vercel.app domain, else the first one
  api "https://api.vercel.com/v9/projects/$1/domains$Q" | python3 -c "import json,sys;d=[x['name'] for x in json.load(sys.stdin)['domains']];print(next((x for x in d if x=='$2.vercel.app'),d[0]))"
}
DOMAIN=${SITE_DOMAIN:-$(pick_domain "$WID" "$SITE")}
ENGINE_DOMAIN=$(pick_domain "$EID" "$SITE-engine")
URL="https://$DOMAIN"

say "4/6 Database (Neon, free tier). Accept the terms in the browser if asked, then re-run."
if ! (cd "$WD" && vercel env ls 2>/dev/null | grep -q DATABASE_URL); then
  (cd "$WD" && vercel integration add neon --name "$SITE-db" --no-env-pull) || {
    echo "Accept Neon's terms in the browser page that opened (or in the Vercel dashboard), then run this script again."; exit 1; }
fi

say "5/6 Environment variables"
setenv "$WD" BETTER_AUTH_SECRET "$BETTER_AUTH_SECRET"
setenv "$WD" BETTER_AUTH_URL "$URL"
setenv "$WD" ENGINE_URL "https://$ENGINE_DOMAIN"
setenv "$WD" ENGINE_KEY "$ENGINE_KEY"
setenv "$WD" TRACKER_KEY "$TRACKER_KEY"
setenv "$WD" CRON_SECRET "$CRON_SECRET"
setenv "$WD" NEXT_PUBLIC_VAPID_PUBLIC_KEY "$VAPID_PUBLIC"
setenv "$WD" VAPID_PRIVATE_KEY "$VAPID_PRIVATE"
setenv "$WD" VAPID_SUBJECT "mailto:${EMAIL:-you@example.com}"
[ -n "$EMAIL" ] && setenv "$WD" ALLOWED_SIGNUP_EMAILS "$EMAIL"
gh secret set FLIGHTSCOUT_API_URL -b "$URL" >/dev/null
gh secret set FLIGHTSCOUT_TRACKER_KEY -b "$TRACKER_KEY" >/dev/null

say "6/6 Deploy (from GitHub, main branch)"
OWNER="${REPO%/*}"; NAME="${REPO#*/}"
for p in "$SITE-engine" "$SITE"; do
  api -X POST "https://api.vercel.com/v13/deployments${Q:-?x=1}&forceNew=1" \
    -d "{\"name\":\"$p\",\"project\":\"$p\",\"target\":\"production\",\"gitSource\":{\"type\":\"github\",\"org\":\"$OWNER\",\"repo\":\"$NAME\",\"ref\":\"main\"}}" >/dev/null
done
rm -rf "$ED" "$WD"

say "Done"
echo "Site:     $URL"
echo "Engine:   https://$ENGINE_DOMAIN"
echo "Sign up with ${EMAIL:-the email you set in ALLOWED_SIGNUP_EMAILS}."
echo "CLI:      uv tool install 'flightscout[browser] @ git+https://github.com/$REPO#subdirectory=engine'"
echo "          flightscout login --url $URL --token <token from Settings>"
echo "Runner:   flightscout serve --install   (searches from your own IP)"
