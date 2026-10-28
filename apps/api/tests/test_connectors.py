import pytest
from cryptography.fernet import Fernet
from test_core import account, institution, second_client

from pluto import connectors
from pluto.config import settings


def test_google_state_encryption_and_isolation(client, monkeypatch):
    monkeypatch.setattr(settings, "credential_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "google_client_id", "test-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    account(client)
    org = institution(client)
    result = client.post(f"/api/v1/connectors/{org}/google/authorize")
    assert result.status_code == 200, result.text
    from urllib.parse import parse_qs, urlsplit

    state = parse_qs(urlsplit(result.json()["url"]).query)["state"][0]
    assert "drive.file" in result.json()["url"] and "test-secret" not in result.text
    assert (
        client.get("/api/v1/connectors/google/callback?state=invalid&code=bad").status_code == 400
    )
    with second_client() as other:
        account(other, "other@example.org")
        assert (
            other.get(
                "/api/v1/connectors/google/callback", params={"state": state, "code": "valid"}
            ).status_code
            == 400
        )
        assert other.get(f"/api/v1/connectors/{org}").status_code == 404

    def google(method, url, **kwargs):
        return (
            {"refresh_token": "private-refresh", "access_token": "short-lived"}
            if "token" in url
            else {"startPageToken": "1"}
        )

    monkeypatch.setattr(connectors, "google_request", google)
    result = client.get(
        "/api/v1/connectors/google/callback",
        params={"state": state, "code": "valid"},
        follow_redirects=False,
    )
    assert result.status_code == 303, result.text
    assert (
        client.get(
            "/api/v1/connectors/google/callback", params={"state": state, "code": "valid"}
        ).status_code
        == 400
    )
    connections = client.get(f"/api/v1/connectors/{org}")
    assert "refresh" not in connections.text and "private" not in connections.text
    value = connectors.seal({"refresh_token": "private-refresh"})
    assert (
        "private-refresh" not in value
        and connectors.unseal(value)["refresh_token"] == "private-refresh"
    )


def test_postgres_blocks_unapproved_networks(monkeypatch):
    from fastapi import HTTPException

    from pluto.postgres_source import connect

    monkeypatch.setattr(settings, "postgres_allowed_hosts", "")
    with pytest.raises(HTTPException):
        connect({"host": "127.0.0.1", "port": 5432})
    monkeypatch.setattr(settings, "postgres_allowed_hosts", "127.0.0.1")
    with pytest.raises(HTTPException):
        connect({"host": "127.0.0.1", "port": 5432})


def test_google_quota_retry_and_revocation(monkeypatch):
    import httpx
    from fastapi import HTTPException

    replies = iter(
        [
            httpx.Response(429),
            httpx.Response(503),
            httpx.Response(200, json={"files": []}, headers={"content-type": "application/json"}),
        ]
    )
    monkeypatch.setattr(connectors.httpx, "request", lambda *a, **k: next(replies))
    monkeypatch.setattr(connectors.time, "sleep", lambda seconds: None)
    assert connectors.google_request("GET", "https://www.googleapis.com/drive/v3/files") == {
        "files": []
    }
    monkeypatch.setattr(connectors.httpx, "request", lambda *a, **k: httpx.Response(403))
    with pytest.raises(HTTPException) as error:
        connectors.google_request("GET", "https://www.googleapis.com/drive/v3/files")
    assert error.value.status_code == 403


def test_drive_import_sync_and_disconnect(client, monkeypatch):
    from uuid import UUID

    from sqlalchemy import select
    from test_core import dataset

    from pluto.db import SessionLocal, context
    from pluto.models import IngestFile, SourceConnection

    monkeypatch.setattr(settings, "credential_encryption_key", Fernet.generate_key().decode())
    user = account(client)
    org = institution(client)
    d = dataset(client, org, user)
    with SessionLocal.begin() as db:
        context(db, "tenant", org)
        c = SourceConnection(
            institution_id=UUID(org),
            provider="google",
            encrypted=connectors.seal({"refresh_token": "test-refresh"}),
            cursor="page1",
        )
        db.add(c)
        db.flush()
        cid = str(c.id)
    monkeypatch.setattr(connectors, "access", lambda connection: "short-test-token")
    info = {
        "id": "provider1",
        "name": "evidence.txt",
        "mimeType": "text/plain",
        "version": "1",
        "size": "20",
    }
    monkeypatch.setattr(connectors, "google_request", lambda method, url, **kwargs: info)
    base = f"/api/v1/connectors/{org}/{cid}"
    result = client.post(base + "/import", json={"dataset_id": d["id"], "file_ids": ["provider1"]})
    assert result.status_code == 200, result.text
    info = {**info, "version": "2"}

    def changed(method, url, **kwargs):
        if "/changes" in url:
            return {
                "newStartPageToken": "page2",
                "changes": [{"fileId": "provider1", "file": info}],
            }
        return info

    monkeypatch.setattr(connectors, "google_request", changed)
    assert client.post(base + "/sync").json()["updated"] == 1
    with SessionLocal.begin() as db:
        context(db, "tenant", org)
        rows = db.scalars(select(IngestFile).order_by(IngestFile.created_at)).all()
        assert [r.state for r in rows] == ["cancelled", "queued"]
        assert rows[1].source_metadata["version"] == "2"
    assert client.delete(base).status_code == 200
    assert client.get(f"/api/v1/connectors/{org}").json()[0]["state"] == "revoked"


def test_media_metadata_and_bounded_keyframes(tmp_path, monkeypatch):
    import json

    import pluto.parsers as parsers

    monkeypatch.setattr(settings, "media_keyframes", 3)
    calls = []

    def command(args, timeout=120):
        calls.append(args)
        return (
            json.dumps(
                {
                    "format": {"duration": "60"},
                    "streams": [{"codec_type": "video", "width": 640, "height": 480}],
                }
            ).encode()
            if args[0] == "ffprobe"
            else b""
        )

    monkeypatch.setattr(parsers, "command", command)
    path = tmp_path / "test.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypisom")
    rows = list(parsers.extract(path, path.name, tmp_path / "preview.png"))
    assert sum(c[0] == "ffmpeg" for c in calls) == 3
    assert any("keyframe 20.000s" == ref for ref, text in rows)


def test_remote_original_is_evicted_after_indexing(client, tmp_path, monkeypatch):
    import hashlib
    from uuid import UUID

    from test_core import dataset

    from pluto.db import SessionLocal, context
    from pluto.models import IngestFile, IngestJob, SourceConnection
    from pluto.storage import objects
    from pluto.worker import run_once

    monkeypatch.setattr(settings, "object_directory", str(tmp_path / "objects"))
    monkeypatch.setattr(settings, "cache_remote_files", False)
    user = account(client)
    org = institution(client)
    d = dataset(client, org, user)
    with SessionLocal.begin() as db:
        context(db, "tenant", org)
        c = SourceConnection(institution_id=UUID(org), provider="google", encrypted="test fixture")
        db.add(c)
        db.flush()
        f = IngestFile(
            institution_id=UUID(org),
            dataset_id=UUID(d["id"]),
            name="remote.txt",
            size=1,
            received=0,
            checksum="",
            state="queued",
            source_metadata={
                "connection_id": str(c.id),
                "provider_id": "remote1",
                "mimeType": "text/plain",
            },
        )
        db.add(f)
        db.flush()
        fid = f.id
        db.add(IngestJob(institution_id=UUID(org), file_id=f.id))

    def retrieve(db, record, path):
        value = b"Remote evidence"
        path.write_bytes(value)
        return len(value), hashlib.sha256(value).hexdigest()

    monkeypatch.setattr(connectors, "retrieve_google", retrieve)
    assert run_once(UUID(org))
    assert not objects.path(org, fid).exists()
    assert client.get(f"/api/v1/ingestion/{org}/search?q=evidence").json()
