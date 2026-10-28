import hashlib
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import delete, func, select, text

from . import schemas as s
from .config import settings
from .db import database
from .models import ContentChunk, Dataset, IngestFile, IngestJob
from .repository import page, scoped
from .security import tenant
from .services import audit, lock_institution
from .storage import objects

router = APIRouter(prefix="/api/v1/ingestion", tags=["ingestion"])
SUPPORTED = {"txt", "csv", "json", "jsonl"}


class Upload(s.Input):
    dataset_id: UUID
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    checksum: str = Field(pattern="^[a-f0-9]{64}$")


class FileOut(s.RecordOut):
    dataset_id: UUID
    name: str
    size: int
    received: int
    checksum: str
    state: str
    error: str


@router.post("/{institution_id}/files", response_model=FileOut, status_code=201)
def initialize(
    institution_id: UUID,
    body: Upload,
    request: Request,
    member=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    lock_institution(db, institution_id)
    scoped(db, Dataset, institution_id, body.dataset_id)
    if (
        "/" in body.name
        or "\\" in body.name
        or any(ord(c) < 32 for c in body.name)
        or body.name.rsplit(".", 1)[-1].lower() not in SUPPORTED
    ):
        raise HTTPException(422, "Supported files: TXT, CSV, JSON, JSONL. Use a plain filename.")
    used = db.scalar(
        select(func.coalesce(func.sum(IngestFile.size), 0)).where(
            IngestFile.institution_id == institution_id, IngestFile.state != "cancelled"
        )
    )
    if (
        body.size > settings.max_upload_bytes
        or used + body.size > settings.institution_storage_bytes
    ):
        raise HTTPException(413, "Institution storage limit or maximum file size exceeded")
    duplicate = db.scalar(
        select(IngestFile).where(
            IngestFile.institution_id == institution_id,
            IngestFile.dataset_id == body.dataset_id,
            IngestFile.checksum == body.checksum,
            IngestFile.size == body.size,
            IngestFile.state != "cancelled",
        )
    )
    if duplicate:
        return duplicate
    record = IngestFile(institution_id=institution_id, **body.model_dump())
    db.add(record)
    db.flush()
    audit(db, request, "upload.initialized", record.id, institution_id)
    return record


@router.get("/{institution_id}/files", response_model=s.Page[FileOut])
def files(
    institution_id: UUID,
    dataset_id: UUID | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    member=Depends(tenant()),
    db=Depends(database, scope="function"),
):
    query = select(IngestFile).where(IngestFile.institution_id == institution_id)
    if dataset_id:
        query = query.where(IngestFile.dataset_id == dataset_id)
    return page(db, query.order_by(IngestFile.created_at.desc(), IngestFile.id), offset, limit)


@router.put("/{institution_id}/files/{file_id}/chunks", response_model=FileOut)
async def chunk(
    institution_id: UUID,
    file_id: UUID,
    request: Request,
    offset: int = Query(ge=0),
    member=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    record = scoped(db, IngestFile, institution_id, file_id)
    db.refresh(record, with_for_update=True)
    if record.state != "uploading" or record.received != offset:
        raise HTTPException(409, "Refresh upload progress before resuming")
    data = bytearray()
    async for part in request.stream():
        if len(data) + len(part) > 4 * 1024 * 1024:
            raise HTTPException(413, "Chunks must not exceed 4 MiB")
        data.extend(part)
    if not data or offset + len(data) > record.size:
        raise HTTPException(422, "Invalid chunk size")
    objects.append(institution_id, file_id, offset, data)
    record.received += len(data)
    db.flush()
    return record


@router.post("/{institution_id}/files/{file_id}/complete", response_model=FileOut)
def complete(
    institution_id: UUID,
    file_id: UUID,
    request: Request,
    member=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    record = scoped(db, IngestFile, institution_id, file_id)
    db.refresh(record, with_for_update=True)
    if record.state != "uploading":
        return record
    if record.received != record.size:
        raise HTTPException(409, "Upload is incomplete")
    checksum = hashlib.sha256()
    with objects.path(institution_id, file_id).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(block)
    if checksum.hexdigest() != record.checksum:
        raise HTTPException(422, "Checksum mismatch; cancel and upload again")
    record.state = "queued"
    db.add(IngestJob(institution_id=institution_id, file_id=file_id))
    audit(db, request, "upload.completed", file_id, institution_id)
    db.flush()
    return record


@router.delete("/{institution_id}/files/{file_id}", response_model=s.Message)
def remove(
    institution_id: UUID,
    file_id: UUID,
    request: Request,
    member=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    record = scoped(db, IngestFile, institution_id, file_id)
    db.refresh(record, with_for_update=True)
    record.state = "cancelled"
    db.execute(
        delete(ContentChunk).where(
            ContentChunk.institution_id == institution_id, ContentChunk.file_id == file_id
        )
    )
    audit(db, request, "file.cancelled", file_id, institution_id)
    return {"message": "File cancelled; content removed"}


@router.post("/{institution_id}/files/{file_id}/reprocess", response_model=FileOut)
def reprocess(
    institution_id: UUID,
    file_id: UUID,
    request: Request,
    member=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    record = scoped(db, IngestFile, institution_id, file_id)
    if record.state not in ("ready", "failed"):
        raise HTTPException(409, "File cannot be reprocessed in its current state")
    job = db.scalar(
        select(IngestJob).where(
            IngestJob.institution_id == institution_id, IngestJob.file_id == file_id
        )
    )
    record.state = "queued"
    record.error = ""
    job.attempts = 0
    job.available_at = func.now()
    job.lease_until = None
    job.lease_token = None
    audit(db, request, "file.reprocessing", file_id, institution_id)
    db.flush()
    return record


@router.get("/{institution_id}/files/{file_id}/download")
def download(
    institution_id: UUID,
    file_id: UUID,
    member=Depends(tenant()),
    db=Depends(database, scope="function"),
):
    record = scoped(db, IngestFile, institution_id, file_id)
    if record.state not in ("ready", "queued", "processing", "failed"):
        raise HTTPException(404, "File unavailable")
    return FileResponse(
        objects.path(institution_id, file_id),
        media_type="application/octet-stream",
        filename=record.name,
        content_disposition_type="attachment",
    )


@router.get("/{institution_id}/search", response_model=list[dict])
def search(
    institution_id: UUID,
    q: str = Query(min_length=1, max_length=200),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    member=Depends(tenant()),
    db=Depends(database, scope="function"),
):
    return (
        db.execute(
            text("""SELECT c.file_id,c.reference, f.name,
      ts_headline('english',c.content,websearch_to_tsquery('english',:q),'StartSel=, StopSel=, MaxWords=40, MinWords=10') AS snippet
      FROM content_chunks c JOIN ingest_files f ON f.id=c.file_id
      WHERE c.institution_id=:tenant AND f.institution_id=:tenant AND f.state='ready'
      AND to_tsvector('english',c.content) @@ websearch_to_tsquery('english',:q)
      ORDER BY ts_rank(to_tsvector('english',c.content),websearch_to_tsquery('english',:q)) DESC,c.id
      LIMIT :limit OFFSET :offset"""),
            {"tenant": institution_id, "q": q, "limit": limit, "offset": offset},
        )
        .mappings()
        .all()
    )
