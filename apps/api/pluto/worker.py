"""Tenant-bound durable worker. Run one configured institution per process."""

import csv
import json
import time
import uuid
from datetime import timedelta

from sqlalchemy import delete, select

from .config import settings
from .db import SessionLocal, context
from .models import ContentChunk, IngestFile, IngestJob, Institution
from .security import now
from .storage import objects


def extract(path, name):
    # shortcut: bounded text formats only; add isolated format adapters before enabling more types.
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Text extraction is limited to 64 MiB per file")
    kind = name.rsplit(".", 1)[-1].lower()
    with path.open(encoding="utf-8-sig") as source:
        if kind == "csv":
            csv.field_size_limit(1024 * 1024)
            for index, row in enumerate(csv.reader(source)):
                yield f"row {index + 1}", json.dumps(row, ensure_ascii=False)
        elif kind == "json":
            value = json.load(source)
            for index, row in enumerate(value if isinstance(value, list) else [value]):
                yield f"record {index + 1}", json.dumps(row, ensure_ascii=False)
        elif kind == "jsonl":
            for index, line in enumerate(source):
                if len(line) > 1024 * 1024:
                    raise ValueError("Structured record is too large")
                yield f"record {index + 1}", json.dumps(json.loads(line), ensure_ascii=False)
        else:
            for index, line in enumerate(source):
                yield f"line {index + 1}", line


def run_once(institution_id):
    token = uuid.uuid4()
    with SessionLocal.begin() as db:
        context(db, "tenant", institution_id)
        if db.get(Institution, institution_id).status != "active":
            return False
        cancelled = db.scalars(
            select(IngestFile)
            .where(IngestFile.institution_id == institution_id, IngestFile.state == "cancelled")
            .limit(10)
            .with_for_update(skip_locked=True)
        ).all()
        for record in cancelled:
            objects.path(institution_id, record.id).unlink(missing_ok=True)
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
        with SessionLocal.begin() as db:
            context(db, "tenant", institution_id)
            record = db.scalar(select(IngestFile).where(IngestFile.id == file_id).with_for_update())
            job = db.get(IngestJob, job_id)
            if record.state != "processing" or job.lease_token != token:
                return True
            db.execute(
                delete(ContentChunk).where(
                    ContentChunk.file_id == file_id, ContentChunk.institution_id == institution_id
                )
            )
            position = 0
            for reference, content in extract(objects.path(institution_id, file_id), name):
                for start in range(0, len(content), 4000):
                    if position >= 10000:
                        raise ValueError("Extracted content exceeds 10000 chunks")
                    db.add(
                        ContentChunk(
                            institution_id=institution_id,
                            file_id=file_id,
                            position=position,
                            reference=reference,
                            content=content[start : start + 4000],
                        )
                    )
                    position += 1
                    if position % 100 == 0:
                        db.flush()
            record.state = "ready"
            record.error = ""
            job.lease_until = None
    except Exception:
        with SessionLocal.begin() as db:
            context(db, "tenant", institution_id)
            record = db.scalar(select(IngestFile).where(IngestFile.id == file_id).with_for_update())
            job = db.get(IngestJob, job_id)
            if record.state == "processing" and job.lease_token == token:
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
