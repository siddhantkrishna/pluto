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

## Subsequent text-ingestion subset verification

The incomplete Step 02 text-ingestion subset was verified with 30 passing backend tests and four passing production-server browser tests. New coverage exercises resumable chunk offsets, incomplete upload rejection, checksum mismatch, filename traversal rejection, worker processing/idempotency, tenant-isolated full-text search, authorized original download, cancellation and object cleanup, retry exhaustion/reprocessing, and the browser upload flow. The migration round-trip test now includes both ingestion revisions and checks schema drift. TypeScript, production build, Ruff, Prettier and Compose configuration checks pass. Containers were not executed. No Google Drive, external database connector, multimodal parser or 1 TB throughput verification is claimed; those capabilities remain unimplemented.

## Multimodal and connector continuation

An initial full backend run passed 39 tests after adding the source-connection migration, encrypted OAuth state, parser adapters and a larger-than-64-MiB fixture. Subsequent changes were verified with focused tests rather than repeating unaffected authentication tests: 14 ingestion/parser/catalog tests passed; six connector tests passed after the final connector changes, including OAuth session/state binding, state replay, tenant denial, encryption, quota retries, Drive version changes/disconnect, SSRF rejection, bounded media command generation and eviction of processed Drive originals. The worker tests pass with extraction moved to a subprocess. The production build, TypeScript and formatting pass. The four existing browser tests passed after adjusting the upload option locator for the added source destination selector.

Real PDF, DOCX, PPTX, XLSX, Parquet and Pillow image fixtures were parsed locally. OCR behavior used a local test adapter; live Tesseract and FFmpeg/FFprobe execution were not available on this native host. Their Docker packages are specified, but Docker Engine remains unavailable, so image builds/runtime are unverified. Google protocol behavior was verified with test doubles; no Google credential environment variables were available to this process. Real OAuth consent, Picker loading, cloud API quotas/revocation and external PostgreSQL TLS/import/incremental behavior have not been exercised against live services. The PostgreSQL connector blocks private addresses and unapproved hosts; its database read-only/server-cursor path still requires an authorized external integration test.

The implementation does not claim a 1 TB benchmark. Parser time, per-record, image and archive-expansion bounds are intentional safety controls. Audio transcription is not enabled; media extraction is metadata and bounded preview frames. Incremental PostgreSQL imports apply to append-only monotonic primary keys, not arbitrary CDC/update/delete capture. Worker recovery re-extracts a file with idempotent index replacement rather than resuming inside arbitrary document formats.
