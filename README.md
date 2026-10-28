# PLUTO by VOGON

PLUTO Core is a multi-institution data catalog and governance platform. It provides account authentication, independent institutional workspaces, membership and invitation management, role-based permissions, metadata catalogs, source definitions, activity history, and installation administration.

**Step 01 only:** source definitions do not connect to external systems. No ingestion, file upload, AI, knowledge graph, or analytical pipeline is implemented. No AI API key or paid service is needed locally.

## Run with Docker

Requires Docker Engine/Desktop with Compose v2 (Intel Mac supported by the images), Git, and Python 3 for configuration generation.

```sh
python3 infra/configure-local.py
docker compose up --build
```

The generator refuses to overwrite an existing `.env`. If using the native development configuration from this checkout, preserve it elsewhere before generating Docker configuration. It generates random local database passwords, never default credentials. Compose starts PostgreSQL, runs migrations as a separate one-shot job, then starts FastAPI and Next.js. Open **http://localhost:3000** and register an account. API documentation: **http://localhost:8000/docs**. PostgreSQL is not published to the host. Database and development email volumes persist across restarts.

Development email links are written to a private volume, never returned by the API:

```sh
docker compose exec api sh -c 'ls /app/.dev-mail'
docker compose exec api cat /app/.dev-mail/SELECTED_FILE.eml
```

Open recovery/invitation links in the same browser as PLUTO. Invitation acceptance requires the invited account to be signed in. Links use URL fragments to keep tokens out of request URLs and are cleared from browser history after loading.

## Native development

Use PostgreSQL 17+, Node.js 24 LTS, and Python 3.14. Create a UTF-8 database and a `pluto_app` login with **NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE**, separate from the migration/schema owner. Use independently generated passwords. The migration requires that `pluto_app` already exists. Set `DATABASE_URL` to its SQLAlchemy `postgresql+psycopg://` URL and `MIGRATION_DATABASE_URL` to the schema owner's URL in root `.env`. Set `WEB_ORIGIN=http://localhost:3000` and `ENVIRONMENT=development`. The `.env.example` deliberately contains names without values.

```sh
cd apps/api
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head
.venv/bin/uvicorn pluto.main:app --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

In another terminal:

```sh
cd apps/web
npm ci
npm run dev
```

Next.js proxies `/api/*` to FastAPI. The browser uses a single origin. Native development defaults to `http://127.0.0.1:8000`; Docker uses `http://api:8000`. Restart/rebuild the web application after changing the upstream URL. Never put database credentials in `NEXT_PUBLIC_*` variables.

## First platform administrator

Registering an account never grants platform privileges. Supply a new dedicated email, name, and strong password as `PLUTO_ADMIN_EMAIL`, `PLUTO_ADMIN_NAME`, and `PLUTO_ADMIN_PASSWORD` in the process environment, using your secret manager or a non-echoing shell prompt. From `apps/api`, with the migration URL available:

```sh
.venv/bin/python -m pluto.admin
```

For Docker, use the migration image with environment variables explicitly passed from your shell:

```sh
docker compose run --rm -e PLUTO_ADMIN_EMAIL -e PLUTO_ADMIN_NAME -e PLUTO_ADMIN_PASSWORD migrate python -m pluto.admin
```

The command refuses to run once any platform administrator exists and refuses to overwrite existing accounts. Remove the provisioning variables afterward. Subsequent administrator changes use authenticated platform administration. The API-serving container deliberately receives no migration URL.

## Verification

Use a **separate disposable UTF-8 PostgreSQL database**, migrated to head, with the same restricted application role. Set `DATABASE_URL`, `MIGRATION_DATABASE_URL`, `ENVIRONMENT=test`, and `PLUTO_TEST_ALLOW_RESET=yes` in an ignored test env file. **Tests truncate their configured database.** Never point them at an institution's real data.

```sh
cd apps/api
.venv/bin/dotenv -f ../../.local/test.env run -- .venv/bin/alembic upgrade head
.venv/bin/dotenv -f ../../.local/test.env run -- .venv/bin/pytest -q
.venv/bin/ruff check pluto tests
cd ../web
npm run typecheck
npm run build
npx playwright install chromium
npm test
```

Browser tests require the API and web server running at localhost ports 8000/3000. They create clearly named verification accounts/workspaces in the running development database. See [verification notes](docs/verification.md) for checks actually executed in this checkout.

API contracts are generated from FastAPI, not separately maintained business rules:

```sh
./infra/generate-contracts.sh
```

## Structure and operations

- `apps/api/pluto`: API routers, Pydantic contracts, SQLAlchemy models, transaction-scoped database access, centralized authorization, services, and scoped repository helpers.
- `apps/web`: Next.js App Router, server-side authentication gate, accessible forms/dialogs, generated API types, responsive VOGON styling, and locally bundled open-source fonts.
- `packages/openapi.json`: generated API contract.
- `infra`: container bootstrap and contract generation.
- [Architecture and security](docs/architecture.md)
- [Deployment, migrations, and environment reference](docs/operations.md)

The core is designed for later ingestion services; it does not establish or benchmark 1 TB processing capacity. Independent security review, operational hardening, and capacity testing remain deployment responsibilities. No certification or accreditation is claimed.
