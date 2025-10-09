# Amadeus 2.0

## Run the full stack with one command

The repository ships with a Compose setup that launches the API, Angular UI, PostgreSQL, and Redis in a single terminal. The API container runs database migrations on boot so you land on an operational dashboard without any manual prep.

```bash
docker compose up --build
```

The services become available on:

| Service   | URL                  |
|-----------|----------------------|
| Frontend  | <http://localhost:4200> |
| API       | <http://localhost:8000> |
| Postgres  | `localhost:5432`      |
| Redis     | `localhost:6379`      |

By default the stack runs with `AMAD_USE_MOCK=true`, enabling the in-repo Nautilus mocks so you can explore the UI without installing the trading engine. Switch to the real integration by exporting the variable before starting Compose:

```bash
export AMAD_USE_MOCK=false
docker compose up --build
```

The primary administrator account is seeded automatically during startup using the credentials below:

| Email                     | Password   |
|---------------------------|------------|
| `volkov.zheka@gmail.com`  | `volkov650`|

After signing in you can rotate the password from the **Settings → Password** panel.
Two-factor authentication (TOTP) is disabled by default for every account and can be enabled later from the security settings.

The authentication service automatically rate-limits login attempts by allowing five failures per minute before temporary lockout,
so the stack ships with basic brute-force protection out of the box.

To change the bootstrap credentials, edit the `.env` file (or export the variables in your deployment environment) with
`AUTH__ADMIN_EMAIL` and `AUTH__ADMIN_PASSWORD`. The gateway reads those values on boot and either creates the administrator
if no matching user exists yet or updates the stored password for the existing admin. See [docs/bootstrap-admin.md](docs/bootstrap-admin.md)
for a detailed walkthrough of the process.

When the Nautilus engine is unavailable while `AMAD_USE_MOCK=false`, engine-dependent API calls respond with HTTP 501 and a hint to install `nautilus-trader` or toggle the mock profile.

To reset the database while Compose is running, stop the stack and remove the named volume:

```bash
docker compose down
docker volume rm amadeus-2.0_db_data
```

## Development workflows

### Frontend

Run npm scripts from `frontend/amadeus-ui` so the Angular CLI resolves the workspace correctly:

```bash
cd frontend/amadeus-ui
npm run start
```

You can also stay at the repository root and prefix commands:

```bash
npm --prefix frontend/amadeus-ui run lint
```

### Backend

The `Makefile` offers shortcuts for installing dependencies and running the FastAPI gateway locally:

```bash
make dev           # install Python requirements
make run           # start uvicorn in reload mode
make test          # execute pytest
```

Run migrations against your preferred database with:

```bash
python backend/gateway/scripts/apply_migrations.py --database-url <DATABASE_URL>
```

### Linting and formatting

Strong lint/format defaults are enabled for both the frontend and backend:

```bash
make lint          # ruff + Angular ESLint
make format        # ruff format + Prettier (TS/SCSS)
```

### End-to-end smoke test

The Playwright suite confirms that the dashboard boots.

```bash
cd frontend/amadeus-ui
npx playwright install  # once per machine to download browsers
npm run e2e
```

The test harness starts `ng serve` automatically and checks that the dashboard shell renders.
