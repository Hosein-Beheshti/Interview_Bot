# Deployment

The free stack, and why each piece:

| Piece | Where | Why | Cost |
|---|---|---|---|
| Postgres + pgvector | **Neon** | Free tier includes pgvector and does not expire. Render's own free Postgres has neither. | $0 |
| FastAPI container | **Render** | Builds the repo's Dockerfile straight from GitHub. | $0 |
| React frontend | **Cloudflare Pages** | Static, global CDN, genuinely unmetered on the free plan. | $0 |
| Retention sweep | **GitHub Actions** | Render's free tier has no cron. | $0 |

Everything deploys from the GitHub repo — there is no CLI to install.

**The one honest caveat:** a free Render instance sleeps after 15 minutes idle and
takes roughly 50 seconds to wake. The first visitor after a quiet spell waits.
Neon also scales to zero, adding a few hundred milliseconds on top. Options: pay
$7/month for Render's `starter` plan (the fix), or keep it warm (see the end).

---

## Order matters

The frontend needs the backend's URL, and the backend needs the frontend's origin
for CORS. Neither exists until the other is deployed, so: **database → backend →
frontend → point the backend at the frontend.**

---

## 1. Database (Neon)

1. Sign up at [neon.tech](https://neon.tech) — no card required.
2. Create a project. Any region; pick one near your users.
3. Copy the **pooled** connection string from the dashboard. It looks like:

   ```
   postgresql://USER:PASSWORD@ep-xxx-pooler.REGION.aws.neon.tech/neondb?sslmode=require
   ```

   Keep `?sslmode=require`. Prefer the **pooled** endpoint (`-pooler`) — a
   sleeping free instance handles reconnections better through it.

You do not need to create tables or enable pgvector by hand. The API does both on
startup (`persistence/schema.py`), inside one advisory-locked transaction.

## 2. Backend (Render)

1. Sign up at [render.com](https://render.com) with your GitHub account.
2. **New → Blueprint**, pick the `Interview_Bot` repo, and choose the branch you
   pushed. Render reads `render.yaml` and configures the service itself.
3. It will prompt for the five values marked `sync: false`:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | the Neon string from step 1 |
   | `ANTHROPIC_API_KEY` | your Anthropic key |
   | `VOYAGE_API_KEY` | your Voyage key (CV upload fails without it) |
   | `DEEPGRAM_API_KEY` | your Deepgram key (voice fails without it; text is fine) |
   | `CORS_ORIGINS` | `http://localhost:5173` for now — corrected in step 4 |

4. Deploy. The first build takes 3–5 minutes. When it is live, check:

   ```sh
   curl https://YOUR-SERVICE.onrender.com/health        # {"status":"ok"}
   curl https://YOUR-SERVICE.onrender.com/health/ready   # {"status":"ready"}
   ```

   `ready` is the one that matters — it returns `ready` only if Neon is
   reachable. A 503 means `DATABASE_URL` is wrong or the database is unreachable.

Note the service URL; the frontend needs it.

## 3. Frontend (Cloudflare Pages)

1. Sign up at [dash.cloudflare.com](https://dash.cloudflare.com) — no card required.
2. **Workers & Pages → Create → Pages → Connect to Git**, pick the repo and branch.
3. Build settings:

   | Setting | Value |
   |---|---|
   | Framework preset | None |
   | Build command | `npm run build` |
   | Build output directory | `dist` |
   | Root directory | `frontend` |

4. Environment variables (Settings → Environment variables), **both** required:

   | Variable | Value |
   |---|---|
   | `VITE_API_URL` | `https://YOUR-SERVICE.onrender.com` — origin only, no `/api` |
   | `NODE_VERSION` | `20` |

   `VITE_API_URL` is read at **build** time, not run time. Changing it later means
   triggering a fresh deployment, not just saving the variable.

5. Deploy. Note the `*.pages.dev` URL.

## 4. Close the CORS loop

Back in Render → your service → Environment, set:

```
CORS_ORIGINS = https://YOUR-PROJECT.pages.dev
```

Saving triggers a redeploy. Until this is right, the browser blocks every API
call and the UI shows "Cannot reach the server" — that message is CORS, not a
backend outage. Comma-separate to allow more than one origin (e.g. a custom
domain alongside the `pages.dev` one).

## 5. Retention sweep

In GitHub → Settings → Secrets and variables → Actions, add a repository secret
`DATABASE_URL` with the same Neon string. The workflow in
`.github/workflows/retention.yml` then runs daily.

Verify it without deleting anything: Actions → retention-sweep → Run workflow,
leaving "dry run" checked.

---

## Before you share the link

- [ ] `curl .../health/ready` returns `ready`
- [ ] Run one full interview end to end in the browser — the reply should stream
      in word by word, and the score card should appear before the next question
      finishes writing
- [ ] Upload a CV, confirm the questions reference it, then use **Delete my
      transcript and CV** and confirm it is gone
- [ ] Confirm `DAILY_TOKEN_CEILING` is a number you would be content to pay on the
      worst possible day (the `render.yaml` default of 500,000/day is roughly
      $18/month at the absolute ceiling — usually far less)
- [ ] Set a spend alert in the [Anthropic Console](https://console.anthropic.com)
      as a second, independent backstop. The in-app ceiling can only stop what it
      can see; a billing alert stops what it cannot.
- [ ] Update the demo link at the top of `README.md`

---

## Operating notes

**Cold starts.** A free Render instance sleeps after 15 minutes idle. You *can*
keep it warm with a scheduled ping, but be aware of the arithmetic: the free plan
grants 750 instance-hours per month and a month is 744 hours, so an always-warm
service consumes essentially the entire allowance and leaves nothing for a second
service. If the wait bothers you, `starter` at $7/month is the cleaner answer.

**Logs.** Render → your service → Logs. Every rate-limit rejection, vendor
failure, and readiness failure is logged with context; nothing logs a CV's
contents or an API key.

**Scaling past free.** In rough order of when it starts to hurt: Render
`starter` ($7/mo, no sleeping) → Neon paid (~$19/mo, point-in-time recovery,
which matters as soon as the data is someone else's) → a second Render instance.
Cloudflare Pages will not be the thing that needs upgrading.

**Rolling back.** Render keeps previous deploys — Deploys → pick one → Redeploy.
The schema migrations are additive and idempotent, so an app rollback does not
need a database rollback.
