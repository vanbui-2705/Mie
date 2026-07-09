# FlowMeta Web Deploy

## Quick Start

1. Copy `.env.example` to `.env`.
2. Replace `POSTGRES_PASSWORD`, `FERNET_KEY`, and `FLOWMETA_TOKEN_SECRET`.
3. Start the stack:

```powershell
docker compose up --build -d
```

Frontend: `http://localhost:3000`  
Backend API docs: `http://localhost:8000/docs`

The stack runs four app services: `frontend`, `backend`, `worker`, plus PostgreSQL and Redis. Long-running comment tasks should be queued through `/api/comment-tasks`; the worker consumes Redis jobs and writes task/log state back to Postgres.

## Local One-Account Test

1. Start the local stack:

```powershell
docker compose up --build -d
```

2. Open `http://localhost:3000/accounts`.
3. Import one line:

```text
UID|FACEBOOK_USER_TOKEN
```

4. Check token, then sync pages.
5. Open `http://localhost:3000/auto-comment` and run a small comment/edit/delete task.
6. Open `http://localhost:3000/auto-post` to post text/link to one synced Fanpage.
7. Open `http://localhost:3000/auto-share` to share a source URL to one synced Fanpage.

Task status and logs are stored in Postgres, so the UI can poll persisted state even when API and worker are separate processes.

## Required Secrets

- `FERNET_KEY`: encrypts Facebook tokens, page tokens, and proxy secrets. Keep it stable across restarts.
- `FLOWMETA_TOKEN_SECRET`: signs login tokens.
- `POSTGRES_PASSWORD`: database password.

Generate a Fernet key:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## First Admin Password

For the migration stage, requests without an auth token use a default `admin` user so the current UI remains usable.

To lock the admin login, call:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/auth/bootstrap `
  -ContentType 'application/json' `
  -Body '{"password":"change-this-password"}'
```

Then login with:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/auth/login `
  -ContentType 'application/json' `
  -Body '{"username":"admin","password":"change-this-password"}'
```

## Production Notes

- Caddy and Nginx configs are included under `deploy/caddy` and `deploy/nginx`.
- Set `NEXT_PUBLIC_API_URL` to the public API URL.
- Set `CORS_ORIGINS` to the public frontend origin.
- Back up the Postgres volume regularly.
- Do not rotate `FERNET_KEY` without a token re-encryption migration.

Run production with Caddy HTTPS:

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

Run the included Nginx reverse proxy profile instead:

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile nginx up --build -d nginx
```

Production `.env` should include:

```text
APP_DOMAIN=your-domain.com
ACME_EMAIL=you@your-domain.com
NEXT_PUBLIC_API_URL=https://your-domain.com
CORS_ORIGINS=https://your-domain.com
```

## Tests

Run fast backend tests:

```powershell
cd backend
$env:PYTHONPATH='.'
python -m pytest -q
```

Run real PostgreSQL integration tests by setting `TEST_DATABASE_URL` first:

```powershell
cd backend
$env:PYTHONPATH='.'
$env:TEST_DATABASE_URL='postgresql+asyncpg://flowmeta:change-me@localhost:5432/flowmeta_test'
python -m pytest -q -m integration
```
