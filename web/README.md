# FlightScout web

The browser app for FlightScout: search, smart routes (split tickets, stopovers, nested round trips), a multi city trip builder, explore, a watchlist with price history charts, places, history and settings. It is a Next.js 16 app (App Router) with Better Auth, Drizzle ORM on Postgres, MapLibre with OpenFreeMap tiles, and Recharts.

It talks to the Python engine (`../engine`, FastAPI) server side for every flight search. Everything else lives in Postgres for signed in users and in `localStorage` for guests.

## Modes

* **Guest (no login).** Search, smart routes, trip builder, explore and the map all work. Places, the watchlist (with a manual "Check now"), settings and recent history are kept in this browser. The client `api()` helper (`src/lib/client.ts`) sends those routes to `src/lib/guest.ts` instead of the server. Engine calls are rate limited per IP.
* **Signed in.** Data syncs across devices. The GitHub Actions tracker checks watches daily. Alerts go out by email or web push. API tokens let the CLI, the MCP server and AI agents push results into History and watches. On first login the app offers to import guest data.
* **Invite only sign up.** Only emails in `ALLOWED_SIGNUP_EMAILS` can create accounts. This is enforced in a Better Auth `databaseHooks.user.create.before` hook, so it covers email, OAuth and passkey sign ups.

## Local setup

```bash
cd web
npm install                  # also copies the MapLibre worker into public/maplibre
cp .env.example .env.local   # then fill in secrets
# Postgres: any Postgres works. With colima or Docker:
docker run -d --name flightscout-pg -e POSTGRES_USER=flightscout -e POSTGRES_PASSWORD=flightscout \
  -e POSTGRES_DB=flightscout -p 5433:5432 postgres:17
# or no server at all: DATABASE_URL=pglite:./.pglite
npm run db:migrate
npm run dev                  # http://localhost:3000
```

Run the engine next to it (see `../engine`) on `http://127.0.0.1:8787` with `ENGINE_KEY=dev-engine-key`.

## Environment variables

| Name | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | yes | Postgres (Neon on Vercel). `pglite:<dir>` for a local embedded DB |
| `BETTER_AUTH_SECRET` | yes | Long random string (`openssl rand -hex 32`) |
| `BETTER_AUTH_URL` | yes in prod | `https://flightscout-app.vercel.app` |
| `ALLOWED_SIGNUP_EMAILS` | no | Comma separated. Default `hhafnor@gmail.com` |
| `ENGINE_URL`, `ENGINE_KEY` | yes | Engine base URL (`https://flightscout-engine.vercel.app`) and its shared key |
| `TRACKER_KEY` | for tracking | Shared secret the GitHub Actions tracker sends as `x-tracker-key` |
| `NEXT_PUBLIC_VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | for push | `npx web-push generate-vapid-keys` |
| `RESEND_API_KEY`, `ALERT_FROM_EMAIL` | for email | Resend API key and a verified sender |
| `GITHUB_CLIENT_ID/SECRET`, `GOOGLE_CLIENT_ID/SECRET` | no | OAuth buttons appear only when set |
| `CRON_SECRET` | for cleanup | Protects `/api/cron/cleanup` (Vercel sends it automatically) |

## Deploy (Vercel)

1. Create a Vercel project with root directory `web`.
2. Set the env vars above. `DATABASE_URL` already exists on the production project.
3. Deploy. `npm run build` runs `scripts/migrate.mjs` first, which applies Drizzle migrations when `DATABASE_URL` is set and skips them otherwise, then `next build`.
4. `vercel.json` schedules a daily `/api/cron/cleanup`. It drops trip JSON from observations older than 30 days (prices are kept), trims old search payloads, and removes stale rate limit rows.

## Scripts

| Script | What it does |
|---|---|
| `npm run dev` | Dev server |
| `npm run build` | Migrate (if a DB is configured) and build |
| `npm run db:generate` | New migration from `src/lib/db/schema.ts` |
| `npm run db:migrate` | Apply migrations (fails if `DATABASE_URL` is missing) |
| `npm run lint` | ESLint |

## API (`/api/v1`)

Auth is the session cookie or `Authorization: Bearer fsk_...` (create tokens in Settings). Guests may call the engine proxies anonymously.

| Route | Notes |
|---|---|
| `GET /me` | `{user: null}` for guests |
| `POST /search`, `/plan`, `/trip`, `/explore`, `/dates` | Engine proxies. Per hour limits: guests 30/5/5/20/20 per IP, users 300/40/40/200/200. Signed in results are saved to history and feed matching watches |
| `GET/PATCH /settings`, `GET/POST /places`, `PATCH/DELETE /places/:id` | |
| `GET/POST /watches`, `GET/PATCH/DELETE /watches/:id` | |
| `GET /watches/:id/history`, `POST /watches/:id/observations`, `POST /watches/:id/check` | |
| `POST /results` | CLI and MCP push `{kind, query, payload, origin}` |
| `GET /searches`, `GET/DELETE /searches/:id` | History |
| `GET/POST /tokens`, `DELETE /tokens/:id` | API tokens |
| `GET/POST /alerts`, `POST/DELETE /push`, `GET /fx` | |
| `GET /tracker/watches`, `POST /tracker/observations` | GitHub Actions tracker (`x-tracker-key`) |
