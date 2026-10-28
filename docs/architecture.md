# Architecture and security

## Boundaries

The browser talks to Next.js on one origin. Next.js forwards REST requests to FastAPI. FastAPI owns identity, sessions, permissions, validation, transactions, and audit records. PostgreSQL is the source of truth. No authentication token is stored in browser storage. Server-rendered protected layouts verify the session with FastAPI; every protected API operation independently authenticates and authorizes requests.

The backend uses explicit router, schema, service, repository, and persistence modules. Repository helpers always include the institution predicate. Service operations and audit writes commit in one request transaction. FastAPI's generated OpenAPI schema supplies frontend TypeScript contracts.

## Identity

Passwords use Argon2id. Email addresses are normalized to lowercase and constrained unique. Registration returns the same generic response for an existing email; login uses a dummy Argon2 hash for unknown accounts. Database-backed, atomic rate limits apply across worker processes, with email and network limits for login/recovery. Rate keys are hashed, and raw emails/IPs are not logged. Authentication failures have safe error bodies with a generated request identifier.

Sessions contain a random 256-bit bearer token; PostgreSQL stores only its SHA-256 digest. A separate random CSRF value is bound to the session. Cookies are HTTP-only, SameSite=Lax, path `/`, with Secure enabled in production. Sessions expire after 12 hours by default. The authenticated identity endpoint exposes only safe account data and the CSRF value. Every state-changing API request must have the configured exact Origin; authenticated mutations additionally require the session CSRF value in a header. The browser API helper holds CSRF only in memory.

Password changes and recovery revoke all sessions and invalidate outstanding recovery tokens. Recovery tokens expire after 30 minutes; invitations after seven days. Token consumption locks database records to prevent reuse. No raw bearer, recovery, or invitation token is returned in API response bodies or logs. Recovery and invitation links use fragments and are cleared from history after extraction.

SMTP uses STARTTLS with certificate and hostname verification. Without SMTP, only development/test environments may write private `.eml` files. Production fails startup without HTTPS configuration and SMTP. Users must sign into the account matching an invitation's address; existing memberships are never silently promoted by invitation acceptance.

## Institutions and permissions

| Role | Read catalog/sources/member directory | Edit catalog/sources | Manage ordinary members | Manage administrators/owners | Settings/audit |
|---|---|---|---|---|---|
| Owner | Yes | Yes | Yes | Yes | Yes |
| Administrator | Yes | Yes | Yes | No | Yes |
| Analyst | Yes | No | No | No | No |
| Viewer | Yes | No | No | No | No |

Analyst and viewer permissions coincide in Step 01 because analysis is intentionally absent. Classification labels describe metadata; they are not a separate per-record clearance model. All members of an institution can read its catalog. There are no public dataset access endpoints, even for records labeled public.

Institution ownership changes use role modification: promote a second owner, then demote/remove the original. Every membership mutation serializes on the institution row; the last active owner cannot be demoted, removed, or globally disabled. Members owning dataset records must have those records reassigned before removal. Dataset ownership requires an active member of the same institution. A composite foreign key prevents cross-institution source associations. All state changes validate ownership and roles on the backend.

## Row-level security

Memberships, invitations, settings, datasets, sources, and audit events use ENABLE and FORCE ROW LEVEL SECURITY. The application role is not the table owner and has no superuser/BYPASSRLS privilege. API startup rejects unsafe credentials. It receives only SELECT/INSERT/UPDATE/DELETE grants, without schema creation or TRUNCATE privileges. Audit rows are append-only for the application role.

The server sets user identity after validating the session. Tenant context is set only after verifying an active membership and institution. Context uses parameterized `set_config(..., true)` inside each transaction and disappears on transaction end, compatible with transaction pooling. Read policies permit users to discover only their own memberships before selecting a tenant; an invitation hash grants only the read needed to accept that invitation. Tenant tables otherwise fail closed without tenant context.

Institutions and platform administrators are control-plane metadata. Platform endpoints expose institution lifecycle metadata and account administration, not customer datasets, settings, invitations, or tenant audit history. Platform status alone grants no tenant policy exception. Operational account suspension examines memberships internally to protect last-owner invariants and returns no tenant contents.

RLS is defense in depth against missed tenant predicates, not a sandbox against arbitrary SQL execution by a compromised API server: the trusted server can set context variables. Protect application credentials and API execution. Tests run through the restricted role, including deliberately unscoped queries and cross-tenant inserts. References: [PostgreSQL row security](https://www.postgresql.org/docs/17/ddl-rowsecurity.html).

## Data and future extensions

Datasets hold metadata only: name, description, source category/type/reference, classification, tags, status, record count, byte count, institutional owner, source association, and timestamps. Counts are explicitly supplied metadata, not measured ingestion statistics. All source definitions remain `not_configured` at the database constraint level. External credentials are neither accepted nor resolved. The credential-provider protocol fails closed until an approved secret-manager implementation is supplied. Descriptions/references are metadata and must not contain secrets.

Step 02 can add ingestion jobs, storage manifests, connector implementations, and processing status keyed to existing institution/dataset/source IDs. It must preserve scoped authorization, composite foreign keys, transaction-local context, and separate operational privileges. No large content blobs are stored in these metadata tables.

## Logging and deployment limits

Structured application logs contain request ID, route template, method, status, duration, and exception class only. Audit records contain actor, institution, action, target, timestamp, and request ID; no full payloads or tokens. Disable proxy/access log query strings and request bodies. API requests may contain confidential search terms.

No external connectors, AI, ingestion, cross-tenant sharing, MFA, SSO, compliance accreditation, penetration-test certification, or 1 TB throughput claims are included. Use HTTPS, restricted network ingress, backups, monitoring, patching, and independent review before a commercial deployment. Rate limits also need ingress-level request-size and volumetric protections; the local setup is not an internet-facing perimeter.
