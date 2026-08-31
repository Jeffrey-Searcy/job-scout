# Job Scout — multi-user go-live (Tailscale)

This is the checklist to turn the single-user app into a two-person app served
over your Tailscale network with real HTTPS. Do the steps in order. Nothing here
runs automatically — you run each step so you can see it work.

> **One thing that will bite you if skipped:** your live database has job data
> (18 applications, 16 leads) but **no user account yet**. The ownership
> migration refuses to guess an owner — it will STOP with a clear error unless a
> user exists first. So **Step 3 (create your account) must happen before the
> migration backfill**, which is why the order below matters.

---

## 1. Pick your tailnet hostname

Find your machine's Tailscale name (looks like `yourbox.tailXXXX.ts.net`):

```
tailscale status
```

Call it `HOST` below. Your app URL will be `https://HOST` (port 443, the default).

## 2. Add these lines to your `.env`

I can't edit `.env` (it holds secrets). Add/adjust these — replace `HOST` with
your real tailnet hostname, and generate a fresh worker secret:

```dotenv
# --- multi-user + HTTPS (Tailscale) ---
DEBUG=0

# Your tailnet hostname (the app's only host). Keep localhost for local testing.
ALLOWED_HOSTS=HOST,localhost,127.0.0.1

# The browser origin(s) Django trusts for CSRF + CORS. Must be the https:// URL.
CSRF_TRUSTED_ORIGINS=https://HOST
CORS_ALLOWED_ORIGINS=https://HOST

# Lock the login cookies to HTTPS, and trust the Tailscale TLS proxy in front.
SECURE_COOKIES=1
BEHIND_TLS_PROXY=1

# Shared secret the host worker uses to read the task queue. Generate a long
# random value and paste it here AND into the worker's environment (Step 6).
# Make one with:  python3 -c "import secrets; print(secrets.token_urlsafe(48))"
WORKER_SHARED_SECRET=PASTE_A_LONG_RANDOM_VALUE_HERE
```

> Generate the worker secret once and use the SAME value in `.env` and in the
> worker's shell (Step 6). If they differ, the worker can't read the queue and
> you'll see `403` in its logs.

## 3. Create YOUR account first (before the migration backfill)

Your existing 18 applications + 16 leads belong to you. The migration assigns
all pre-existing rows to the first superuser, so make that superuser now:

```
docker compose exec backend python manage.py createsuperuser
```

Use a username/password you'll remember — this is your login to the app too.

## 4. Rebuild and start the stack with the new code

```
docker compose build
docker compose up -d
```

The backend's entrypoint runs the migrations on start. Watch the logs to confirm
the owner backfill ran without the "no user account exists" error:

```
docker compose logs -f backend
```

You should see the migrations apply cleanly. Your existing data is now owned by
your account. (If you skipped Step 3, the backend will stop with a clear message
telling you to create a user and retry — just do Step 3 and `docker compose up`
again.)

## 5. Put the app on Tailscale HTTPS

This serves your frontend (port 8080) at `https://HOST` with a real cert:

```
tailscale serve --bg https / http://localhost:8080
```

Check it:

```
tailscale serve status
```

Open `https://HOST` in a browser on any device in your tailnet. You should see
the login screen.

## 6. Start the host worker (runs the AI searches)

The worker runs on the host (not in Docker) so it can use your Claude Max login.
It now needs the shared secret from Step 2:

```
cd /Users/jeff/Documents/work-docs/job-scout
export WORKER_SHARED_SECRET='the-same-value-you-put-in-.env'
export JOBSCOUT_API_URL='http://localhost:8000/api'   # the backend's host port
python3 agent_worker.py
```

It will refuse to start if `WORKER_SHARED_SECRET` is unset — that's intentional.

## 7. Invite your girlfriend

1. She joins your Tailscale network (send her a device-invite from the Tailscale
   admin console).
2. She opens `https://HOST`, clicks **"New here? Create an account"**, and signs
   up. Sign-up is open on purpose — only people on your tailnet can reach the URL.
3. She uploads her resume PDF in the **Your resume** panel.
4. She clicks **Run scan now**. The first scan reads her resume once to build her
   search profile, then finds roles that match *her*, saved to *her* inbox.

Your data and hers are fully separate — different logins, different pipelines,
different resumes. The one worker handles both your searches, one at a time.

---

## How the pieces fit (for future you)

- **Login** = Django session cookie + CSRF. The SPA sends the cookie on every
  call and echoes the CSRF token on writes.
- **Per-user data** = every row has an `owner`; every query is scoped to the
  logged-in user server-side. Nobody can see or forge another user's rows.
- **AI search** = the dashboard makes an `AgentTask`, which mints a **scoped,
  expiring token**. The worker reads the queue with the **shared secret**, runs
  Claude with that task's token, and the MCP tools use the token so every saved
  job lands in the right person's account. The token dies when the task finishes.
- **Resumes** = uploaded PDFs live on the `media` Docker volume inside the
  backend only. They are **never** served by nginx (that would leak them). The
  only ways to read one back are two login/secret-gated Django endpoints: you get
  your own via `/api/resume/pdf/`, and the worker fetches the one it needs via
  `/api/worker/tasks/<id>/resume.pdf` using the shared secret.
