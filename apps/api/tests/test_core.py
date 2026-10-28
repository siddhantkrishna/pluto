import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from pluto.config import settings
from pluto.db import SessionLocal, context
from pluto.main import app
from pluto.models import Dataset

PASSWORD = "A long test passphrase 029!"


def account(client, email="owner@example.org"):
    r = client.post(
        "/api/v1/auth/register", json={"name": "Test Person", "email": email, "password": PASSWORD}
    )
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    data = r.json()
    client.headers["X-CSRF-Token"] = data["csrf"]
    return data["user"]


def institution(client, name="Institution A"):
    r = client.post("/api/v1/institutions", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def dataset(client, org, user, **extra):
    body = {
        "name": "Operations register",
        "source_category": "local_file",
        "owner_id": user["id"],
        **extra,
    }
    r = client.post(f"/api/v1/catalog/{org}", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def link(kind):
    files = [p for p in Path(settings.mail_directory).glob("*.eml") if kind in p.read_text()]
    content = (
        BytesParser(policy=policy.default)
        .parsebytes(max(files, key=lambda p: p.stat().st_mtime_ns).read_bytes())
        .get_content()
    )
    return re.search(r"#token=([A-Za-z0-9_-]+)", content).group(1)


def invite(client, org, email, role="viewer"):
    r = client.post(f"/api/v1/invitations/{org}", json={"email": email, "role": role})
    assert r.status_code == 201, r.text
    assert "token" not in r.json() and "token_hash" not in r.json()
    return link("invitation"), r.json()["id"]


def second_client():
    return TestClient(
        app, base_url="http://localhost:8000", headers={"Origin": settings.web_origin}
    )


def test_registration_normalization_login_logout(client):
    user = account(client, "Owner@Example.org")
    assert user["email"] == "owner@example.org"
    assert "password_hash" not in user
    assert client.get("/api/v1/auth/me").status_code == 200
    cookie = client.cookies.get("pluto_session")
    assert cookie
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set("pluto_session", cookie)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_invalid_login_and_rate_limit(client):
    account(client)
    for _ in range(9):
        r = client.post(
            "/api/v1/auth/login", json={"email": "owner@example.org", "password": "incorrect"}
        )
        assert r.status_code == 401
        assert r.json()["error"]["message"] == "Invalid email or password"
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "owner@example.org", "password": PASSWORD}
        ).status_code
        == 429
    )


def test_expired_session(client):
    account(client)
    from sqlalchemy import create_engine

    with create_engine(settings.migration_database_url).begin() as db:
        db.execute(text("UPDATE auth_sessions SET expires_at=now()-interval '1 second'"))
    assert client.get("/api/v1/auth/me").status_code == 401


def test_csrf_origin_and_cookie_flags(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "x@example.org", "name": "X", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    account(client)
    r = client.post("/api/v1/auth/login", json={"email": "owner@example.org", "password": PASSWORD})
    assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=lax" in r.headers["set-cookie"]
    assert (
        client.post(
            "/api/v1/institutions", json={"name": "No CSRF"}, headers={"X-CSRF-Token": ""}
        ).status_code
        == 403
    )


def test_catalog_crud_filter_and_sources(client):
    user = account(client)
    org = institution(client)
    source = client.post(
        f"/api/v1/data-sources/{org}", json={"name": "Local files", "category": "local_file"}
    ).json()
    assert source["status"] == "not_configured"
    d = dataset(client, org, user, source_id=source["id"], tags=["logistics"], record_count=15)
    assert client.get(f"/api/v1/catalog/{org}?q=Operations&tag=logistics").json()["total"] == 1
    assert client.get(f"/api/v1/catalog/{org}?classification=restricted").json()["total"] == 0
    assert client.delete(f"/api/v1/data-sources/{org}/{source['id']}").status_code == 409
    payload = {
        k: v for k, v in d.items() if k not in ["id", "institution_id", "created_at", "updated_at"]
    }
    payload["name"] = "Updated register"
    assert client.put(f"/api/v1/catalog/{org}/{d['id']}", json=payload).status_code == 200
    assert client.get(f"/api/v1/catalog/{org}/{d['id']}").json()["name"] == "Updated register"
    assert client.delete(f"/api/v1/catalog/{org}/{d['id']}").status_code == 200
    assert client.delete(f"/api/v1/data-sources/{org}/{source['id']}").status_code == 200
    actions = [e["action"] for e in client.get(f"/api/v1/audit/{org}").json()["items"]]
    assert "dataset.created" in actions and "dataset.deleted" in actions


def test_cross_tenant_api_and_database(client):
    owner = account(client)
    org_a = institution(client)
    d = dataset(client, org_a, owner)
    with second_client() as other:
        user = account(other, "other@example.org")
        org_b = institution(other, "Institution B")
        assert other.get(f"/api/v1/catalog/{org_a}").status_code == 404
        assert other.get(f"/api/v1/catalog/{org_b}/{d['id']}").status_code == 404
        assert other.delete(f"/api/v1/catalog/{org_b}/{d['id']}").status_code == 404
        assert other.get(f"/api/v1/memberships/{org_a}").status_code == 404
        assert other.get(f"/api/v1/audit/{org_a}").status_code == 404
        assert (
            other.put(f"/api/v1/institutions/{org_a}/settings", json={"name": "Stolen"}).status_code
            == 404
        )
        with SessionLocal.begin() as db:
            context(db, "user", user["id"])
            context(db, "tenant", org_b)
            assert db.scalars(select(Dataset)).all() == []
        with SessionLocal.begin() as db:
            assert db.scalars(select(Dataset)).all() == []
        with pytest.raises(ProgrammingError):
            with SessionLocal.begin() as db:
                context(db, "tenant", org_b)
                db.add(
                    Dataset(
                        institution_id=uuid.UUID(org_a),
                        owner_id=uuid.UUID(user["id"]),
                        name="Injected",
                        source_category="api",
                    )
                )
                db.flush()


@pytest.mark.parametrize("role", ["viewer", "analyst", "administrator"])
def test_invitation_permissions_removal(client, role):
    account(client)
    org = institution(client)
    token, _ = invite(client, org, "member@example.org", role)
    with second_client() as member:
        user = account(member, "member@example.org")
        r = member.post("/api/v1/invitations/accept", json={"token": token})
        assert r.status_code == 200, r.text
        assert member.post("/api/v1/invitations/accept", json={"token": token}).status_code == 400
        assert member.get(f"/api/v1/catalog/{org}").status_code == 200
        r = member.post(
            f"/api/v1/catalog/{org}",
            json={"name": "Data", "source_category": "api", "owner_id": user["id"]},
        )
        assert r.status_code == (201 if role == "administrator" else 403)
        if role == "administrator":
            assert (
                member.post(
                    f"/api/v1/invitations/{org}", json={"email": "new@example.org", "role": "owner"}
                ).status_code
                == 403
            )
            assert member.delete(f"/api/v1/catalog/{org}/{r.json()['id']}").status_code == 200
        rows = client.get(f"/api/v1/memberships/{org}").json()["items"]
        target = next(m for m in rows if m["user_id"] == user["id"])
        assert client.delete(f"/api/v1/memberships/{org}/{target['id']}").status_code == 200
        assert member.get(f"/api/v1/catalog/{org}").status_code == 404


def test_invitation_expiry_and_wrong_email(client):
    account(client)
    org = institution(client)
    token, invitation_id = invite(client, org, "member@example.org")
    with second_client() as member:
        account(member, "wrong@example.org")
        assert member.post("/api/v1/invitations/accept", json={"token": token}).status_code == 400
    from sqlalchemy import create_engine

    with create_engine(settings.migration_database_url).begin() as db:
        db.execute(
            text("UPDATE invitations SET expires_at=now()-interval '1 day' WHERE id=:id"),
            {"id": invitation_id},
        )
    with second_client() as member:
        account(member, "member@example.org")
        assert member.post("/api/v1/invitations/accept", json={"token": token}).status_code == 400


def test_last_owner_and_multiple_workspaces(client):
    account(client)
    org = institution(client)
    institution(client, "Second")
    assert len(client.get("/api/v1/institutions").json()) == 2
    owner = client.get(f"/api/v1/memberships/{org}").json()["items"][0]
    assert client.delete(f"/api/v1/memberships/{org}/{owner['id']}").status_code == 409
    assert (
        client.patch(
            f"/api/v1/memberships/{org}/{owner['id']}", json={"role": "viewer"}
        ).status_code
        == 409
    )


def test_recovery_single_use_and_session_revocation(client):
    account(client)
    r = client.post("/api/v1/auth/recovery", json={"email": "owner@example.org"})
    assert r.status_code == 200 and "token" not in r.text
    token = link("recovery")
    assert (
        client.post(
            "/api/v1/auth/reset-password", json={"token": token, "password": PASSWORD + "new"}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/reset-password", json={"token": token, "password": PASSWORD}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "owner@example.org", "password": PASSWORD + "new"}
        ).status_code
        == 200
    )


def test_password_change(client):
    account(client)
    assert (
        client.post(
            "/api/v1/users/password",
            json={"current_password": "wrong", "password": PASSWORD + "new"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/users/password",
            json={"current_password": PASSWORD, "password": PASSWORD + "new"},
        ).status_code
        == 200
    )
    assert client.get("/api/v1/auth/me").status_code == 401


def test_platform_privileges_and_no_implicit_tenant_access(client):
    admin = account(client)
    assert client.get("/api/v1/platform/institutions").status_code == 403
    from sqlalchemy import create_engine

    with create_engine(settings.migration_database_url).begin() as db:
        db.execute(
            text("INSERT INTO platform_admins (id,user_id) VALUES (:id,:user)"),
            {"id": uuid.uuid4(), "user": admin["id"]},
        )
    with second_client() as other:
        user = account(other, "customer@example.org")
        org = institution(other)
        dataset(other, org, user)
        assert client.get("/api/v1/platform/institutions").json()["total"] == 1
        assert client.get(f"/api/v1/catalog/{org}").status_code == 404
        assert (
            client.patch(
                f"/api/v1/platform/institutions/{org}", json={"status": "suspended"}
            ).status_code
            == 200
        )
        assert other.get(f"/api/v1/catalog/{org}").status_code == 403
        assert (
            client.patch(
                f"/api/v1/platform/institutions/{org}", json={"status": "active"}
            ).status_code
            == 200
        )
        assert other.get(f"/api/v1/catalog/{org}").status_code == 200
        assert (
            client.patch(
                f"/api/v1/platform/users/{user['id']}", json={"status": "disabled"}
            ).status_code
            == 409
        )
    assert client.delete(f"/api/v1/platform/administrators/{admin['id']}").status_code == 409
    assert client.get("/api/v1/platform/audit").json()["total"] == 2


def test_database_roles_policies_and_audit_append_only(client):
    account(client)
    org = institution(client)
    with SessionLocal.begin() as db:
        role = db.execute(
            text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
        ).one()
        assert not role.rolsuper and not role.rolbypassrls
        policies = db.execute(
            text(
                "SELECT count(*) FROM pg_class WHERE relname IN ('datasets','data_sources','memberships','invitations','institution_settings','audit_events') AND relrowsecurity AND relforcerowsecurity"
            )
        ).scalar()
        assert policies == 6
    with pytest.raises(ProgrammingError):
        with SessionLocal.begin() as db:
            context(db, "tenant", org)
            db.execute(text("DELETE FROM audit_events"))


def test_validation_and_protected_routes(client):
    assert client.get("/api/v1/institutions").status_code == 401
    user = account(client)
    org = institution(client)
    assert (
        client.post(
            f"/api/v1/catalog/{org}",
            json={
                "name": "No",
                "source_category": "api",
                "owner_id": user["id"],
                "record_count": -1,
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/data-sources/{org}",
            json={
                "name": "Secrets",
                "category": "database",
                "reference": "postgres://user:password@host",
            },
        ).status_code
        == 422
    )
    assert client.get(f"/api/v1/catalog/{org}?limit=1000").status_code == 422
    assert client.get("/api/v1/catalog/not-a-uuid").status_code == 404


def test_concurrent_owner_demotions(client):
    owner = account(client)
    org = institution(client)
    token, _ = invite(client, org, "second@example.org", "owner")
    with second_client() as second:
        account(second, "second@example.org")
        assert second.post("/api/v1/invitations/accept", json={"token": token}).status_code == 200
        rows = client.get(f"/api/v1/memberships/{org}").json()["items"]
        a = next(m for m in rows if m["user_id"] == owner["id"])
        b = next(m for m in rows if m["user_id"] != owner["id"])
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(
                client.patch, f"/api/v1/memberships/{org}/{a['id']}", json={"role": "viewer"}
            )
            f2 = pool.submit(
                second.patch, f"/api/v1/memberships/{org}/{b['id']}", json={"role": "viewer"}
            )
            assert sorted([f1.result().status_code, f2.result().status_code]) == [200, 409]


def test_recovery_expiration_and_duplicate_registration(client):
    account(client)
    r = client.post(
        "/api/v1/auth/register",
        json={"name": "Different", "email": "OWNER@example.org", "password": PASSWORD + "other"},
    )
    assert r.status_code == 201
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "owner@example.org", "password": PASSWORD}
        ).status_code
        == 200
    )
    client.post("/api/v1/auth/recovery", json={"email": "owner@example.org"})
    token = link("recovery")
    from sqlalchemy import create_engine

    with create_engine(settings.migration_database_url).begin() as db:
        db.execute(text("UPDATE recoveries SET expires_at=now()-interval '1 minute'"))
    assert (
        client.post(
            "/api/v1/auth/reset-password", json={"token": token, "password": PASSWORD + "new"}
        ).status_code
        == 400
    )


def test_application_rejects_privileged_database_identity(monkeypatch):
    from sqlalchemy import create_engine

    import pluto.main as main

    privileged = create_engine(settings.migration_database_url)
    monkeypatch.setattr(main, "engine", privileged)
    with pytest.raises(RuntimeError, match="must not own tables"):
        with TestClient(app):
            pass
    privileged.dispose()


def test_migration_round_trip():
    import subprocess
    import sys

    for args in [("downgrade", "base"), ("upgrade", "head"), ("check",)]:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stdout + result.stderr
    with SessionLocal.begin() as db:
        assert (
            db.execute(text("SELECT version_num FROM alembic_version")).scalar() == "c5f609506dd2"
        )


def test_bootstrap_administrator_one_time(client):
    import os
    import subprocess
    import sys

    env = {
        **os.environ,
        "PLUTO_ADMIN_EMAIL": "bootstrap@example.org",
        "PLUTO_ADMIN_NAME": "Installation Admin",
        "PLUTO_ADMIN_PASSWORD": PASSWORD,
    }
    result = subprocess.run(
        [sys.executable, "-m", "pluto.admin"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [sys.executable, "-m", "pluto.admin"], env=env, capture_output=True, text=True
    )
    assert result.returncode != 0 and "Already provisioned" in result.stderr
    r = client.post(
        "/api/v1/auth/login", json={"email": "bootstrap@example.org", "password": PASSWORD}
    )
    assert r.status_code == 200 and r.json()["platform_admin"] is True


def test_local_configuration_generator(tmp_path):
    import importlib.util

    script = Path(__file__).resolve().parents[3] / "infra" / "configure-local.py"
    spec = importlib.util.spec_from_file_location("configure_local", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    destination = tmp_path / "local.env"
    content = module.configure(destination)
    assert destination.stat().st_mode & 0o777 == 0o600
    assert "pluto_app:" in content
    with pytest.raises(FileExistsError):
        module.configure(destination)


def test_production_configuration_and_secure_cookie(client, monkeypatch):
    from pydantic import ValidationError

    from pluto.config import Settings

    with pytest.raises(ValidationError):
        Settings(
            database_url=settings.database_url,
            environment="production",
            web_origin="http://example.org",
            smtp_host="smtp.example.org",
            smtp_from="pluto@example.org",
        )
    with pytest.raises(ValidationError):
        Settings(
            database_url=settings.database_url,
            environment="production",
            web_origin="https://example.org",
            smtp_host="",
        )
    production = Settings(
        database_url=settings.database_url,
        environment="production",
        web_origin="https://example.org",
        smtp_host="smtp.example.org",
        smtp_from="pluto@example.org",
    )
    assert production.secure
    account(client)
    monkeypatch.setattr(settings, "environment", "production")
    response = client.post(
        "/api/v1/auth/login", json={"email": "owner@example.org", "password": PASSWORD}
    )
    assert "Secure" in response.headers["set-cookie"]


def test_concurrent_registration_is_generic(client):
    def register():
        with second_client() as c:
            return c.post(
                "/api/v1/auth/register",
                json={
                    "name": "New account",
                    "email": "concurrent@example.org",
                    "password": PASSWORD,
                },
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: register(), range(2)))
    assert [r.status_code for r in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()


def test_internal_errors_do_not_expose_details(client, monkeypatch):
    import pluto.auth as auth

    def fail(*args, **kwargs):
        raise RuntimeError("sensitive_internal_payload")

    monkeypatch.setattr(auth, "rate_limit", fail)
    response = client.post(
        "/api/v1/auth/login", json={"email": "test@example.org", "password": PASSWORD}
    )
    assert response.status_code == 500
    assert "sensitive_internal_payload" not in response.text
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]


def test_invalid_bootstrap_does_not_echo_secret():
    import os
    import subprocess
    import sys

    secret = "shortSECRET"
    env = {
        **os.environ,
        "PLUTO_ADMIN_EMAIL": "invalid@example.org",
        "PLUTO_ADMIN_NAME": "Admin",
        "PLUTO_ADMIN_PASSWORD": secret,
    }
    result = subprocess.run(
        [sys.executable, "-m", "pluto.admin"], env=env, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert secret not in result.stdout + result.stderr


def test_smtp_verifies_provider_certificate(monkeypatch):
    import ssl

    from pluto import services

    observed = {}

    class SMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self, *, context):
            observed["context"] = context

        def send_message(self, message):
            observed["sent"] = True

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(services.smtplib, "SMTP", SMTP)
    services.deliver("recipient@example.org", "recovery", "test-token")
    assert observed["context"].verify_mode == ssl.CERT_REQUIRED
    assert observed["context"].check_hostname
    assert observed["sent"]
