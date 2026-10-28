# Step 01 verification

Verified locally on 28 October 2026 on an Intel Mac using Python 3.14, Node.js 24, Next.js 16.4.3, and PostgreSQL 17.6. Application tests use a separate disposable UTF-8 database and a non-owner PostgreSQL role without superuser or BYPASSRLS privileges.

## Executed checks

- `pytest -q`: 27 backend tests pass. Coverage includes registration/normalization, duplicate and concurrent registration, invalid login and persistent rate limiting, CSRF/Origin enforcement, session expiration/revocation, password change/recovery and token expiration/reuse, institution creation/switching, catalog CRUD/filtering, source definitions, invitations, role restrictions/member removal, cross-institution API denials and direct SQL RLS isolation, concurrent owner demotions, platform authorization/lifecycle controls, unsafe database identity rejection, one-time administrator provisioning, sanitized errors, production configuration/cookie flags, and SMTP certificate-verification configuration.
- Alembic initial upgrade, downgrade/reapply on the disposable database, and `alembic check` pass. No schema drift detected.
- Ruff lint and formatting checks pass.
- TypeScript strict compilation and Next.js production standalone build pass.
- Prettier check passes. `npm audit --omit=dev` reports no known production dependency vulnerabilities at verification time.
- Playwright runs against the production standalone server and real FastAPI/PostgreSQL services. Checks cover protected-page redirection, registration/login, workspace creation, dataset create/edit/delete, source definition, audit history, account sessions, logout, and desktop/mobile layout. Screenshots were inspected locally; table overflow remains within its scroll container, and sign-out remains reachable on mobile.
- Docker Compose configuration validates with Compose v5.6.1. The resolved API container environment was checked to exclude migration URLs, database owner passwords, and provisioning passwords.
- SMTP regression check: reverting to STARTTLS without an explicit certificate-verifying context causes the new test to fail; restoring the fix passes.

## External checks not executed

Docker Engine/Desktop is not installed on this host. Container image builds, Compose service startup/health checks, and the database initialization script have not been executed inside containers. Native services and the production standalone web bundle were executed instead; Compose validation is not a claim that containers were run.

No Neon credentials or live SMTP provider credentials were supplied. Hosted database connectivity, real email delivery, public HTTPS deployment, backup restoration, load testing, and independent penetration testing were not performed. Neon application/direct migration URL configuration and SMTP settings are documented in `operations.md`.

The test environment emits a Starlette notice that its httpx TestClient adapter is deprecated; functional tests pass. This is a development-test dependency warning, not evidence of a production fault.

Browser checks create identifiable verification accounts/workspaces in the development database. They are test records, not seeded product metrics or operational examples. No default production account is created.

Step 02 ingestion, connectors, AI, graph discovery, and analytics remain outside this implementation. No 1 TB capacity or security certification is claimed.
