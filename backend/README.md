# Upload API (login-protected PDF intake)

Small FastAPI service that backs `upload.html` on the static site.

## Local setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then set UPLOAD_SEED_USERNAME / UPLOAD_SEED_PASSWORD
python -m app
```

API listens on `http://127.0.0.1:8081` by default.

Serve the site from the repo root:

```bash
python -m http.server 8000
```

Then open http://127.0.0.1:8000/upload.html

## Tests

Multi-artifact job result coverage (temp SQLite, no Railway):

```bash
cd backend
source .venv/bin/activate
python -m unittest tests.test_job_artifacts -v
```

## Shared production (Railway)

Anyone with the shared password uploads to **one** Railway volume (not each person's laptop).

### 1. Create the service

1. [Railway](https://railway.app) → New Project → Deploy from GitHub (this repo).
2. Set the service **Root Directory** to `backend`.
3. Railway will build via [`Dockerfile`](Dockerfile) / [`railway.toml`](railway.toml).

### 2. Attach a volume

1. Service → **Volumes** → Add volume.
2. Mount path: `/data`
3. Size: start with 1–5 GB.

This persists SQLite + PDFs across deploys.

### 3. Environment variables

In Railway → Variables (do **not** commit these):

| Variable | Example |
|----------|---------|
| `HOST` | `0.0.0.0` |
| `DATA_DIR` | `/data` |
| `UPLOAD_DIR` | `/data/uploads` |
| `UPLOAD_SEED_USERNAME` | `pete` |
| `UPLOAD_SEED_PASSWORD` | *(shared password)* |
| `SESSION_SECRET` | *(long random string)* |
| `CORS_ORIGINS` | `https://ai-in-math-or.github.io,http://127.0.0.1:8000,http://localhost:8000` |

`PORT` is set automatically by Railway.

`CORS_ORIGINS` must name the exact scheme and host the site is served from, with
no path — `https://ai-in-math-or.github.io` covers the whole project page. The
value is read once at import, so changing it in Railway needs a redeploy to take
effect. Because the API runs with `allow_credentials=True`, `*` is not accepted
as a shortcut; every origin has to be listed.

### 4. Public URL

1. Service → **Settings** → **Networking** → Generate domain (e.g. `https://opor-upload-api.up.railway.app`).
2. Confirm `GET https://<domain>/health` returns `{"status":"ok"}`.
3. Set that origin (no trailing slash) in [`../js/site-config.js`](../js/site-config.js) as `uploadApiBaseUrl`, then commit/push so GitHub Pages picks it up.

### 5. Smoke test

Open the live Upload tab → log in → upload a small PDF → it should appear in the list and land on the Railway volume under `/data/uploads/`.

## Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health` | no | Liveness |
| POST | `/auth/login` | no | `{username,password}` → `{token,user}` |
| GET | `/auth/me` | bearer | Current user |
| POST | `/auth/logout` | bearer | Client discards token |
| POST | `/api/uploads` | bearer | multipart `file` (PDF) |
| GET | `/api/uploads` | bearer | List caller's uploads (includes recent jobs) |
| GET | `/api/uploads/{id}` | bearer or worker | Upload metadata |
| GET | `/api/uploads/{id}/file` | bearer or worker | Download stored PDF |
| POST | `/api/uploads/{id}/jobs` | bearer | Queue `{kind:"extract"\|"pipeline"}` |
| GET | `/api/uploads/{id}/jobs` | bearer | List jobs for upload (includes `artifacts`) |
| GET | `/api/jobs/{id}` | bearer or worker | Job status + `artifacts[]` + `stages` |
| POST | `/api/jobs/claim` | worker | Claim next queued job (`?kind=extract\|pipeline`) |
| POST | `/api/jobs/{id}/stages` | worker | Update stage map mid-run |
| POST | `/api/jobs/{id}/result` | worker | multipart PDF + form `artifact_kind` + `finalize` |
| POST | `/api/jobs/{id}/fail` | worker | Mark job failed |
| POST | `/api/jobs/{id}/cancel` | bearer | User cancels own queued/running job |
| POST | `/api/jobs/reap-stale` | worker | Fail all `running` jobs (worker startup) |

`POST /api/jobs/{id}/result` form fields:

| Field | Default | Meaning |
|-------|---------|---------|
| `file` | required | PDF bytes |
| `artifact_kind` | `extraction` | `extraction` \| `literature_review` \| `solver_verified` \| `solver_partial` \| `solver_attempt` |
| `finalize` | `true` | Mark job `done` after this artifact. Pipeline workers post intermediate results with `finalize=false`, then finalize on the last PDF. |

Each result is stored as an upload (`kind` matching the artifact) linked via `parent_upload_id` and listed on the job under `artifacts`.

Worker auth: set the same `WORKER_API_TOKEN` on this API and on the `llm-math` Railway service. The worker calls `GET /api/uploads/{id}/file` with `Authorization: Bearer <WORKER_API_TOKEN>` over Railway private networking (`UPLOAD_API_BASE_URL`). Volumes are **not** shared between services.

## Data layout

| Env | Local default | Railway |
|-----|---------------|---------|
| `DATA_DIR` | `backend/data/` | `/data` |
| `UPLOAD_DIR` | `backend/data/uploads/` | `/data/uploads` |
| DB | `$DATA_DIR/upload_api.sqlite3` | same |

First boot seeds the admin user from `UPLOAD_SEED_*` if the users table is empty.

## Scaling later

- Add more users (same `users` table / roles)
- Swap volume files for R2/S3 without changing the HTTP contract
- Rotate `SESSION_SECRET` and the shared password periodically
