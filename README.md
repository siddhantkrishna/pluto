# PLUTO

PLUTO by VOGON is a multi-institution data-governance and intelligence platform.

## Current deployment: Next.js + Neon

The production web application is a single Next.js service on Vercel. Its Route Handlers
implement the core API directly against a restricted Neon PostgreSQL role. **FastAPI
and Render are not required to create accounts, sign in, manage institutions,
memberships, invitations, access controls, catalog metadata or platform administration.**

- Web app: `apps/web` (Next.js 16, Node.js runtime).
- Server routes: `apps/web/app/api/v1/[...path]/route.ts`.
- Database and authorization: `apps/web/lib/server/`.
- Existing PostgreSQL schema: the already-migrated Neon database, using `pluto_app`.

### Configure Vercel

Set these variables on the **PLUTO Vercel project** (never use `NEXT_PUBLIC_`):

| Variable | Configuration |
|---|---|
| `DATABASE_URL` | Neon pooled connection URL, **restricted `pluto_app`** login, `postgresql://` scheme with SSL |
| `WEB_ORIGIN` | Exactly `https://pluto.vogon.in` in production |
| `SESSION_HOURS` | Optional; default `12` |
| `RESEND_API_KEY` | Optional; HTTPS transactional-email API key for recovery and invitations |
| `MAIL_FROM` | Required with `RESEND_API_KEY`: verified email sender |

No `API_INTERNAL_URL`, Docker web proxy, Render service, SMTP host, migration-owner connection, or Python process is required for this Next.js core.

The PostgreSQL schema is **not** re-created by Next.js. The current schema uses the
original Alembic migration series through `c5f609506dd2`. The old migrations remain
in `apps/api/alembic` as a historical maintenance reference. Never run migrations
with the restricted `pluto_app` database role.

### Security

- All database operations are parameterized and run in transactions using the restricted
  application role; tenant/user context is always transaction-local for PostgreSQL RLS.
- Sessions are stored as SHA-256 hashed tokens in PostgreSQL and set in
  HttpOnly, Secure (production), SameSite=Lax cookies.
- Newly registered passwords use salted Node.js scrypt hashes. No existing account
  data was present at the time of the migration. Pre-existing Python Argon2 hashes
  are **not** supported by the new login verifier and require a separately reviewed
  credential migration if such data is introduced.
- Write APIs require same-origin requests and a CSRF token for authenticated actions.
- Database passwords never belong in client bundles or source control.

### Known gaps

**This is a core-services migration, not a full replacement for Python processing.**
The older `apps/api` code and Docker workflow are retained for archival/recovery purposes,
but are **not used by the deployed Next.js application**. The following capabilities
currently return an explicit HTTP 501 until rewritten against durable object storage
and independently deployed processing workers:

- Large-file/resumable uploads, content extraction, indexing, search, and previews.
- Google Drive/PostgreSQL source connectors and background synchronization.
- Persistent media processing and scheduled ingestion workers.

Do not delete existing data, assets or the old backend source as a shortcut, or represent
these features as working on Vercel. Core authentication, governance and catalog functionality
must be verified before turning off the Render deployment.

### Develop

```sh
cd apps/web
npm install
npm run typecheck
npm run build
npm run dev
```

For local testing, supply `DATABASE_URL` pointing to a disposable, migrated Neon
branch using `pluto_app`, and `WEB_ORIGIN=http://localhost:3000`. Never use
a database owner or privileged Neon dashboard role in application execution.
End-to-end Playwright tests create real database records; use a disposable branch.

### Platform administrator

Ordinary registration deliberately does not grant platform-level privileges. To bootstrap
the first administrator, register a dedicated account and use an authorized Neon
database-owner SQL session (not the application role) to insert one `platform_admins`
record. Do not expose an unauthenticated admin-bootstrap HTTP endpoint.

See `docs/operations.md` for historical migration/database notes and architecture limits.
