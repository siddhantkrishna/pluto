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

## Source ingestion and processing

Uploads now accept TXT, CSV, JSON/JSONL, PDF, DOCX, PPTX, XLSX, Parquet, JPEG/PNG/WebP/TIFF, MP3/WAV/M4A and MP4/MOV/WebM. Text and JSON arrays stream records; Parquet uses PyArrow batches and Polars; XLSX is read-only/row-wise; PDFs are processed page-wise. Office XML expansion and individual record/image sizes remain bounded for malicious-input protection. There is no blanket 64 MiB file cap or 10000-chunk cap. Index batches commit while the file remains hidden until indexing succeeds. Failures and cancellations cannot expose partial content. Reprocessing restarts extraction idempotently; it does not resume a parser inside a document.

Parser subprocesses have configurable time/CPU and preview-size limits. Docker also bounds total worker memory/CPU/PIDs. Native operation must supply equivalent OS/container memory isolation for untrusted content. Docker images install FFmpeg, FFprobe and Tesseract. OCR is local when Tesseract is present; absent OCR is explicitly recorded. Media extraction records duration, codecs, stream properties and preview frames; it does not perform semantic understanding or transcription. `MEDIA_KEYFRAMES` (default 1, maximum 8) bounds sampled frames. No transcription model is bundled.

Run a tenant worker using `WORKER_INSTITUTION=<institution UUID>` with `docker compose --profile processing up --build`, or run `python -m pluto.worker` from `apps/api` using the same environment. All worker transactions set tenant context and use the restricted serving database role. Workers commit index batches and check fencing/cancellation on each batch. `RETENTION_DAYS=0` disables automatic expiration; positive values expire ready/failed imports by age. Dataset deletion removes database content immediately; the tenant worker cleans orphaned raw/preview objects after commit. Run workers for all institutions requiring cleanup. Include raw object volumes and encryption-key recovery in backup procedures.

### Google OAuth and Picker

Inject these variables securely into the API and worker environments (never into chat, Git or browser public variables):

- `GOOGLE_CLIENT_ID`: OAuth web application client ID.
- `GOOGLE_CLIENT_SECRET`: OAuth client secret.
- `GOOGLE_PICKER_API_KEY`: Picker browser API key, restricted to approved browser origins/APIs.
- `GOOGLE_PROJECT_NUMBER`: numeric Google Cloud project number used by Picker.
- `CREDENTIAL_ENCRYPTION_KEY`: a Fernet key generated once with `Fernet.generate_key()`. Keep it in an approved secret manager; preserve it for recovery and migrate encrypted credentials before rotation.

With the configured local `WEB_ORIGIN=http://localhost:3000`, the exact redirect URI is **http://localhost:3000/api/v1/connectors/google/callback**. For a deployment, replace only the origin with its exact configured HTTPS `WEB_ORIGIN`, retaining `/api/v1/connectors/google/callback`. Register that URI in the OAuth web client. Enable Google Drive API and Google Picker API in the same project, add approved JavaScript origins, configure the consent screen/test users or publish the consent application as appropriate, and restrict the Picker API key. The application requests only `drive.file`; folder selection does not imply descendant access.

The authorization code uses session-bound, expiring, single-use state and PKCE. Refresh tokens and PostgreSQL passwords are encrypted at rest. Google Picker necessarily receives a short-lived access token and a browser-restricted API key; it never receives the client secret, refresh token or encryption key. Imported Drive files are metadata-first references. Workers retrieve content lazily; processed Drive originals are evicted locally by default and authorized downloads stream from Google. `CACHE_REMOTE_FILES=true` explicitly retains local originals. Google exports native Docs as PDF, Sheets as XLSX and Slides as PPTX, subject to Google's own export limits. Change-page synchronization covers only previously selected imports and processes one quota-bounded page per action; repeat while `has_more=true`. Removal events cancel local access and indexes. Disconnect removes local access even if remote revocation cannot be confirmed; Google account security settings can revoke the grant independently.

### Read-only PostgreSQL

Set `POSTGRES_ALLOWED_HOSTS` to a comma-separated list of explicitly approved hostnames. Targets must resolve exclusively to public IPs; loopback, link-local and private networks are rejected even if listed. The connector pins the resolved address while verifying the hostname through TLS (`verify-full`, system trust roots). Use dedicated SELECT-only, non-superuser credentials; connections additionally enforce read-only transactions and statement/lock/connect timeouts. Schemas/tables come from authorized base-table discovery, never arbitrary user SQL. Selected table imports use server-side cursors and bounded records. Full snapshots stream all rows subject to configured storage/import quotas. Optional incremental imports require a single-column primary key with append-only, monotonically increasing semantics; each import fetches at most 100000 new rows and stores its next cursor. This is not CDC and does not discover updates/deletes behind the cursor. Public provider connectivity still requires environment-specific TLS/network verification.

### Capacity and verification limits

The design stores only metadata for registered remote sources and processes content in bounded batches, with configurable per-record, timeout, upload and institution quotas. Aggregate 1 TB capacity has not been benchmarked. Individual oversized records, huge Office XML members and excessive image dimensions are rejected intentionally; these are security limits, not a whole-corpus RAM assumption. Production sizing, storage/index growth, cleanup throughput and restore drills remain to be measured. A serving/worker database credential remains a trusted application identity capable of setting tenant context; deploy workers with isolated secrets and networks per institution where stronger execution-domain isolation is required.
