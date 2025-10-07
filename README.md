# Amadeus 2.0

## Frontend development

Run frontend npm scripts from the `frontend/amadeus-ui` directory so the Angular CLI can find the workspace configuration. For example:

```bash
cd frontend/amadeus-ui
npm run start
```

Alternatively, you can run commands from the repository root using `npm --prefix frontend/amadeus-ui <command>`:

```bash
npm --prefix frontend/amadeus-ui run lint
```

This prevents "missing package.json" errors that occur when running the scripts from the wrong folder.

## Backend setup

Create a PostgreSQL role for the gateway services before running the backend:

```sql
CREATE USER amadeus WITH PASSWORD 'amadeus';
```

## Setup DB/Redis & Run Nautilus Nodes

1. **Install dependencies.**
   ```bash
   pip install -r requirements.txt
   npm --prefix frontend/amadeus-ui install
   ```

2. **Provision database and Redis services.** Use a local PostgreSQL instance for
   relational storage and Redis for low-latency caching. Docker makes it easy to
   spin up both services:
   ```bash
   docker run -d --name amadeus-postgres -e POSTGRES_DB=amadeus -e POSTGRES_USER=amadeus \
     -e POSTGRES_PASSWORD=amadeus -p 5432:5432 postgres:16
   docker run -d --name amadeus-redis -p 6379:6379 redis:7
   ```

3. **Run Alembic migrations.** The helper script configures the Python path and
   applies compatibility shims so that migrations work against SQLite during
   development and PostgreSQL in production.
   ```bash
   python backend/gateway/scripts/apply_migrations.py \
     --database-url postgresql+asyncpg://amadeus:amadeus@localhost:5432/amadeus
   ```

4. **Export runtime settings.**
   ```bash
   export DATABASE_URL=postgresql+asyncpg://amadeus:amadeus@localhost:5432/amadeus
   export REDIS_URL=redis://localhost:6379/0
   # Enable real Nautilus integration once the engine package is installed.
   export AMAD_USE_MOCK=false
   ```
   Leaving `AMAD_USE_MOCK=true` retains the fully featured mock service for local
   experimentation.

5. **Launch the gateway API and front-end.**
   ```bash
   uvicorn backend.gateway.app.main:app --reload
   npm --prefix frontend/amadeus-ui run start
   ```

6. **Run Nautilus nodes.** With the API running and the Nautilus engine
   available on the Python path (either installed from PyPI or via the `vendor`
   bundle), open the dashboard at <http://localhost:4200>, configure credentials,
   and use the *Launch node* wizard. The gateway will refuse engine-bound
   actions with HTTP 501 responses if `nautilus-trader` is missing while mocks
   are disabled, providing a clear hint to install the package or re-enable the
   mock integration.
