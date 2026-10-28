"""Tenant-bound durable worker. Run one configured institution per process."""

import json
import subprocess
import sys
import threading
import time
import uuid
from datetime import timedelta

from sqlalchemy import delete, select

from .config import settings
from .db import SessionLocal, context
from .models import ContentChunk, IngestFile, IngestJob, Institution
from .security import now
from .storage import objects


def isolated_extract(path, name, preview):
    process = subprocess.Popen(
        [sys.executable, "-m", "pluto.parse_process", str(path), name, str(preview)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    timer = threading.Timer(settings.parser_timeout, process.kill)
    timer.start()
    try:
        while line := process.stdout.readline(settings.max_record_bytes * 6 + 1024):
            if not line.endswith(b"\n"):
                raise ValueError("Parser record exceeded output limit")
            yield json.loads(line)
        if process.wait() != 0:
            raise ValueError("Parser failed or exceeded resource limits")
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


def run_once(institution_id):
    token = uuid.uuid4()
    with SessionLocal.begin() as db:
        context(db, "tenant", institution_id)
        if db.get(Institution, institution_id).status != "active":
            return False
        # Objects are removed only after their metadata deletion has committed.
        directory = objects.path(institution_id, uuid.UUID(int=0)).parent
        for item in directory.iterdir():
            try:
                object_id = uuid.UUID(item.name.split(".")[0])
            except ValueError:
                continue
            if item.is_file() and not db.get(IngestFile, object_id):
                item.unlink(missing_ok=True)
        if settings.retention_days:
            old = db.scalars(
                select(IngestFile)
                .where(
                    IngestFile.institution_id == institution_id,
                    IngestFile.created_at < now() - timedelta(days=settings.retention_days),
                    IngestFile.state.in_(["ready", "failed"]),
                )
                .limit(100)
                .with_for_update(skip_locked=True)
            ).all()
            for expired in old:
                expired.state = "cancelled"
                db.execute(
                    delete(ContentChunk).where(
                        ContentChunk.institution_id == institution_id,
                        ContentChunk.file_id == expired.id,
                    )
                )
        cancelled = db.scalars(
            select(IngestFile)
            .where(IngestFile.institution_id == institution_id, IngestFile.state == "cancelled")
            .limit(10)
            .with_for_update(skip_locked=True)
        ).all()
        for record in cancelled:
            objects.path(institution_id, record.id).unlink(missing_ok=True)
            objects.path(institution_id, record.id).with_suffix(".preview.png").unlink(
                missing_ok=True
            )
            for derived in directory.glob(str(record.id) + ".keyframe-*.png"):
                derived.unlink(missing_ok=True)
            db.delete(record)
        job = db.scalar(
            select(IngestJob)
            .join(IngestFile, IngestFile.id == IngestJob.file_id)
            .where(
                IngestJob.institution_id == institution_id,
                IngestFile.institution_id == institution_id,
                IngestFile.state.in_(["queued", "processing"]),
                IngestJob.available_at <= now(),
                (IngestJob.lease_until.is_(None)) | (IngestJob.lease_until < now()),
            )
            .order_by(IngestJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return False
        job.lease_token = token
        job.lease_until = now() + timedelta(minutes=10)
        job.attempts += 1
        record = db.get(IngestFile, job.file_id)
        record.state = "processing"
        job_id, file_id, name = job.id, record.id, record.name
    try:
        path = objects.path(institution_id, file_id)
        preview = path.with_suffix(".preview.png")
        with SessionLocal.begin() as db:
            context(db, "tenant", institution_id)
            record = db.scalar(select(IngestFile).where(IngestFile.id == file_id).with_for_update())
            job = db.get(IngestJob, job_id)
            if record.state != "processing" or job.lease_token != token:
                return True
            if record.source_metadata and (not path.exists() or record.received == 0):
                from .connectors import retrieve_google, unseal
                from .models import SourceConnection

                connection = db.get(
                    SourceConnection, uuid.UUID(record.source_metadata["connection_id"])
                )
                if not connection or connection.state != "active":
                    raise ValueError("Source access revoked")
                if connection.provider == "google":
                    record.size, record.checksum = retrieve_google(db, record, path)
                else:
                    import hashlib

                    from .postgres_source import retrieve

                    next_cursor = retrieve(
                        unseal(connection.encrypted), record.source_metadata, path
                    )
                    record.source_metadata = {**record.source_metadata, "next_cursor": next_cursor}
                    record.size = path.stat().st_size
                    checksum = hashlib.sha256()
                    with path.open("rb") as source:
                        for block in iter(lambda: source.read(1048576), b""):
                            checksum.update(block)
                    record.checksum = checksum.hexdigest()
                record.received = record.size
            db.execute(
                delete(ContentChunk).where(
                    ContentChunk.file_id == file_id, ContentChunk.institution_id == institution_id
                )
            )
        batch = []
        position = 0

        def persist(finished=False):
            with SessionLocal.begin() as db:
                context(db, "tenant", institution_id)
                current = db.scalar(
                    select(IngestFile).where(IngestFile.id == file_id).with_for_update()
                )
                job = db.get(IngestJob, job_id)
                if not current or current.state != "processing" or job.lease_token != token:
                    raise ValueError("Processing cancelled or superseded")
                if db.get(Institution, institution_id).status != "active":
                    raise ValueError("Institution suspended")
                db.add_all(
                    [
                        ContentChunk(
                            institution_id=institution_id,
                            file_id=file_id,
                            position=p,
                            reference=r,
                            content=c,
                        )
                        for p, r, c in batch
                    ]
                )
                job.lease_until = now() + timedelta(minutes=10)
                if finished:
                    current.state = "ready"
                    current.error = ""
                    job.lease_until = None
            batch.clear()

        for reference, content in isolated_extract(path, name, preview):
            if len(content.encode("utf-8")) > settings.max_record_bytes:
                raise ValueError("Individual extracted record exceeds configured limit")
            for start in range(0, len(content), 4000):
                batch.append((position, reference[:160], content[start : start + 4000]))
                position += 1
                if len(batch) >= 100:
                    persist()
        persist(True)
        if record.source_metadata.get("provider_id") and not settings.cache_remote_files:
            path.unlink(missing_ok=True)
    except Exception:
        with SessionLocal.begin() as db:
            context(db, "tenant", institution_id)
            record = db.scalar(select(IngestFile).where(IngestFile.id == file_id).with_for_update())
            job = db.get(IngestJob, job_id)
            if record and job and record.state == "processing" and job.lease_token == token:
                record.state = "failed" if job.attempts >= 3 else "queued"
                record.error = "Extraction failed: verify UTF-8, file format and processing limits."
                job.available_at = now() + timedelta(seconds=2**job.attempts)
                job.lease_until = None
    return True


def main():
    institution_id = uuid.UUID(settings.worker_institution)
    while True:
        if not run_once(institution_id):
            time.sleep(2)


if __name__ == "__main__":
    main()
