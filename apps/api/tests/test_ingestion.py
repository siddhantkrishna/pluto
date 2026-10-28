import hashlib
from uuid import UUID

from sqlalchemy import select
from test_core import account, dataset, institution, second_client

from pluto.config import settings
from pluto.db import SessionLocal, context
from pluto.models import ContentChunk
from pluto.worker import run_once


def test_upload_resume_process_isolation_cleanup(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_directory", str(tmp_path / "objects"))
    user = account(client)
    org = institution(client)
    d = dataset(client, org, user)
    content = b"Institutional logistics register\nclassified transport"
    checksum = hashlib.sha256(content).hexdigest()
    url = f"/api/v1/ingestion/{org}"
    record = client.post(
        url + "/files",
        json={
            "dataset_id": d["id"],
            "name": "register.txt",
            "size": len(content),
            "checksum": checksum,
        },
    )
    assert record.status_code == 201, record.text
    fid = record.json()["id"]
    path = url + "/files/" + fid
    assert client.put(path + "/chunks?offset=0", content=content[:10]).json()["received"] == 10
    assert client.put(path + "/chunks?offset=0", content=b"wrong").status_code == 409
    assert client.post(path + "/complete").status_code == 409
    assert client.put(path + "/chunks?offset=10", content=content[10:]).status_code == 200
    assert client.post(path + "/complete").json()["state"] == "queued"
    assert run_once(UUID(org))
    assert not run_once(UUID(org))
    assert client.get(url + "/search?q=logistics").json()[0]["file_id"] == fid
    assert client.get(path + "/download").content == content
    with second_client() as other:
        account(other, "other@example.org")
        other_org = institution(other)
        assert other.get(url + "/search?q=logistics").status_code == 404
        assert other.get(f"/api/v1/ingestion/{other_org}/search?q=logistics").json() == []
        assert other.get(path + "/download").status_code == 404
        with SessionLocal.begin() as db:
            context(db, "tenant", other_org)
            assert db.scalars(select(ContentChunk)).all() == []
    assert client.delete(path).status_code == 200
    assert client.get(url + "/search?q=logistics").json() == []
    assert client.get(path + "/download").status_code == 404
    run_once(UUID(org))
    assert not (tmp_path / "objects" / org / fid).exists()


def test_upload_rejects_traversal_and_bad_checksum(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_directory", str(tmp_path / "objects"))
    u = account(client)
    org = institution(client)
    d = dataset(client, org, u)
    base = f"/api/v1/ingestion/{org}/files"
    body = {"dataset_id": d["id"], "name": "../bad.txt", "size": 5, "checksum": "0" * 64}
    assert client.post(base, json=body).status_code == 422
    body["name"] = "bad.txt"
    fid = client.post(base, json=body).json()["id"]
    assert client.put(base + "/" + fid + "/chunks?offset=0", content=b"hello").status_code == 200
    assert client.post(base + "/" + fid + "/complete").status_code == 422


def test_worker_retry_and_reprocessing(client, tmp_path, monkeypatch):
    from pluto.models import IngestFile, IngestJob
    from pluto.security import now

    monkeypatch.setattr(settings, "object_directory", str(tmp_path / "objects"))
    user = account(client)
    org = institution(client)
    d = dataset(client, org, user)
    content = b"not valid json"
    base = f"/api/v1/ingestion/{org}/files"
    fid = client.post(
        base,
        json={
            "dataset_id": d["id"],
            "name": "broken.json",
            "size": len(content),
            "checksum": hashlib.sha256(content).hexdigest(),
        },
    ).json()["id"]
    client.put(base + "/" + fid + "/chunks?offset=0", content=content)
    client.post(base + "/" + fid + "/complete")
    for _ in range(3):
        with SessionLocal.begin() as db:
            context(db, "tenant", org)
            job = db.scalar(select(IngestJob).where(IngestJob.file_id == UUID(fid)))
            job.available_at = now()
        assert run_once(UUID(org))
    with SessionLocal.begin() as db:
        context(db, "tenant", org)
        assert db.get(IngestFile, UUID(fid)).state == "failed"
        assert db.scalars(select(ContentChunk)).all() == []
    assert client.post(base + "/" + fid + "/reprocess").json()["state"] == "queued"
