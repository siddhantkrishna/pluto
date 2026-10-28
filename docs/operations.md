# Operations

## Environment reference

Root `.env` is ignored by Git. The API reads it when launched from `apps/api`; containers receive explicit environment values. `.env.example` contains names only. Production should inject secrets rather than bake files into images.

| Variable | Use |
|---|---|
| `DATABASE_URL` | Required SQLAlchemy `postgresql+psycopg://` application connection using restricted `pluto_app`. |
| `MIGRATION_DATABASE_URL` | Direct schema-owner connection for migrations/bootstrap only; not required or supplied to the serving API. |
| `POSTGRES_PASSWORD` | Generated local Docker database owner password. |
| `PLUTO_DB_PASSWORD` | Generated local Docker application role password. |
| `ENVIRONMENT` | `development`, `test`, or `production`; defaults to development. |
| `WEB_ORIGIN` | Exact browser origin. Default `http://localhost:3000`; production requires HTTPS. No trailing slash. |
| `API_INTERNAL_URL` | Server-only web-to-API upstream. Native default `http://127.0.0.1:8000`; Docker `http://api:8000`. Supply during web build and runtime. |
| `SESSION_HOURS` | Session absolute lifetime, default 12 hours. |
| `MAIL_DIRECTORY` | Private development/test email directory, default `.dev-mail` relative to API working directory. Not an HTTP endpoint. |
| `SMTP_HOST`, `SMTP_PORT` | SMTP delivery endpoint; default port 587, STARTTLS required. Host required in production. |
| `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | SMTP credentials and sender. Sender should be a verified domain address. |
| `PLUTO_ADMIN_EMAIL`, `PLUTO_ADMIN_NAME`, `PLUTO_ADMIN_PASSWORD` | One-time bootstrap command only. Remove after provisioning. |
| `PLUTO_TEST_ALLOW_RESET` | Test harness safety opt-in: `yes`. Only for disposable test databases. |

## Migrations

Provision the `pluto_app` login before migration, without superuser, role creation, database creation, or BYPASSRLS privileges. Never run the web-facing API as schema owner. Initial migration creates all tables, indexes, constraints, and forced RLS policies, then grants restricted application access. It is frozen SQL and does not import live ORM metadata.

From `apps/api`:

```sh
.venv/bin/alembic upgrade head
.venv/bin/alembic current
.venv/bin/alembic check
```

For subsequent development, edit ORM models, generate `alembic revision --autogenerate -m "description"`, and inspect the result. RLS policies and permission changes must be written explicitly; autogeneration does not cover them. New tenant tables require FORCE RLS, transaction context, grants, composite tenant foreign keys where relevant, and negative isolation tests. Run migrations on a disposable database, test an upgrade from the last release, then test on a production-like clone before release. Take a recoverable backup. The initial downgrade drops all core data; never use it as a routine production rollback.

## Neon deployment

Use an existing authorized Neon project and create an isolated branch for validation. This repository does not provision a remote database automatically. Create `pluto_app` with ordinary PostgreSQL SQL through an administrative connection; do not use Neon dashboard-created roles that inherit elevated privileges for application traffic. Check `pg_roles`, table ownership, schema privileges, and RLS using the startup check and test suite.

Use a pooled connection string for `DATABASE_URL`, and a direct, non-pooler connection for `MIGRATION_DATABASE_URL`. Both use the `postgresql+psycopg` SQLAlchemy scheme and TLS (`sslmode=require` or stricter verification supported by your infrastructure). The application sets context with transaction-local `set_config`, not persistent session `SET`. Never share a migration URL with the web app or API-serving process. See [Neon connection pooling](https://neon.com/docs/connect/connection-pooling).

Run the same Alembic migration job before rolling out API replicas. Provision the initial platform administrator through the one-time command. Supply SMTP and set `ENVIRONMENT=production`, `WEB_ORIGIN=https://your-authorized-domain`. No Neon credentials were supplied during implementation; hosted deployment is a separate operator action.

## Production topology

Build the API and web Dockerfiles, deploy them behind a trusted HTTPS reverse proxy, and keep PostgreSQL and the API upstream on private networking. Local Compose binds ports only to loopback and is a development topology. Terminate TLS at the ingress; route browser traffic only through the web origin. Forward Origin unchanged. Configure HSTS at the ingress as well as the API. Do not enable wildcard CORS.

Restrict incoming body sizes (e.g. 64 KiB for this metadata API), request concurrency, and network rates at ingress. The API's persistent login limits use the actual socket peer; default proxy-header trust is disabled. If all traffic arrives through one web proxy, the network limit is shared. For a multi-node production installation, configure a trusted ingress that overwrites forwarding headers and a reviewed proxy trust chain before relying on individual client-IP limits; never trust arbitrary public X-Forwarded-For. Per-account limits remain active regardless.

Images run without root. Mount development email volumes only locally. Production uses SMTP with STARTTLS and no development link exposure. Keep SMTP, database, and provisioning secrets in your approved secret manager. The future connector credential provider intentionally fails closed until a secret-manager integration is implemented.

The web CSP disallows third-party origins, framing, and external connections. Next.js hydration currently requires inline scripts/styles in this policy; a nonce-based CSP can further harden deployments. Inter, Inter Tight, and IBM Plex Mono are bundled from their open-source font packages; the browser does not contact a font CDN. No Alliance fonts or proprietary visual assets are included.

## Backups, maintenance, and incident handling

Schedule encrypted database backups and restore drills. Set retention, RPO, and RTO appropriate to the installation. Neon restore windows and plan limits are operator configuration, not application guarantees. Monitor health endpoints, error rates, SMTP delivery errors, storage, connection pool saturation, and unauthorized attempts. Audit rows are immutable to the application role, but database administrators retain maintenance privileges.

Schedule cleanup through your operational scheduler using the migration identity: remove expired authentication sessions, used/expired recovery records, and rate-limit windows older than the agreed retention. Invitations and audit events should follow institutional retention policy. Do not silently delete audit history. Database tables are indexed for session expiration and common tenant catalog/audit queries; benchmark realistic tenant sizes before increasing workload.

If an account is compromised, revoke its sessions and reset the password. Platform operators can disable ordinary accounts; owners must first arrange another active owner. Suspend an institution to block its workspace operations while preserving records. A platform administrator has no automatic content access. Remove platform privileges before disabling an administrator, and keep at least one active administrator.

## Text ingestion subset (Step 02 in progress)

The current ingestion routes support resumable TXT, CSV, JSON and JSONL uploads with 4 MiB chunks, SHA-256 verification, tenant quotas, PostgreSQL-backed leased jobs, text extraction, full-text search and cancellation. The imports screen computes hashes incrementally in the browser with WebAssembly; CSP permits WebAssembly compilation without enabling JavaScript eval in production. Raw files stay outside PostgreSQL, under private tenant UUID directories. Object storage must be included in backup/restore operations.

Set `WORKER_INSTITUTION` to an existing authorized institution UUID, then run `docker compose --profile processing up --build`. Each worker process handles one configured institution. For native operation, from `apps/api`, run `WORKER_INSTITUTION=<uuid> .venv/bin/python -m pluto.worker`. The worker uses transaction-local tenant context and the restricted application database role. Compose limits worker memory, CPU and process count. Extraction is capped at 64 MiB per file and 10000 text chunks; errors retry three times. Cancellation removes indexes transactionally; the tenant worker deletes cancelled raw files and manifests after commit. Remove files and allow worker cleanup before deleting their dataset. Storage directories must be private to trusted API/worker processes.

This is an incomplete Step 02 implementation. Google OAuth/Picker/synchronization, PostgreSQL source imports, Excel/Parquet, office/PDF/image/audio/video processing, OCR/transcription, richer previews, retention scheduling, source permission synchronization and enterprise worker credential separation are not implemented. No real Google credentials have been requested or stored. The current subset must not be presented as universal ingestion or as validated for 1 TB workloads.
