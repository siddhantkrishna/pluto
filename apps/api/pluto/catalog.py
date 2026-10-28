from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, select

from . import schemas as s
from .db import database
from .models import Dataset, DataSource, IngestFile, Membership, User
from .repository import page, scoped
from .security import tenant
from .services import audit, lock_institution

router = APIRouter(prefix="/api/v1", tags=["catalog"])


def validate_owner(db, institution_id, body):
    if not db.scalar(
        select(Membership.id)
        .join(User)
        .where(
            Membership.institution_id == institution_id,
            Membership.user_id == body.owner_id,
            User.status == "active",
        )
    ):
        raise HTTPException(422, "Owner must be an active institution member")
    if body.source_id:
        source = scoped(db, DataSource, institution_id, body.source_id)
        if source.category != body.source_category:
            raise HTTPException(422, "Source category must match the associated source")


@router.get("/catalog/{institution_id}", response_model=s.Page[s.DatasetOut])
def datasets(
    institution_id: UUID,
    q: str = Query("", max_length=160),
    status: str = Query("", max_length=30),
    classification: str = Query("", max_length=30),
    tag: str = Query("", max_length=40),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    membership=Depends(tenant()),
    db=Depends(database, scope="function"),
):
    query = select(Dataset).where(Dataset.institution_id == institution_id)
    if q:
        query = query.where(
            Dataset.name.icontains(q, autoescape=True)
            | Dataset.description.icontains(q, autoescape=True)
        )
    if status:
        query = query.where(Dataset.status == status)
    if classification:
        query = query.where(Dataset.classification == classification)
    if tag:
        query = query.where(Dataset.tags.contains([tag]))
    return page(db, query.order_by(Dataset.updated_at.desc(), Dataset.id), offset, limit)


@router.get("/catalog/{institution_id}/{dataset_id}", response_model=s.DatasetOut)
def dataset(
    institution_id: UUID,
    dataset_id: UUID,
    membership=Depends(tenant()),
    db=Depends(database, scope="function"),
):
    return scoped(db, Dataset, institution_id, dataset_id)


@router.post("/catalog/{institution_id}", response_model=s.DatasetOut, status_code=201)
def add_dataset(
    institution_id: UUID,
    body: s.DatasetInput,
    request: Request,
    membership=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    lock_institution(db, institution_id)
    validate_owner(db, institution_id, body)
    record = Dataset(institution_id=institution_id, **body.model_dump())
    db.add(record)
    db.flush()
    audit(db, request, "dataset.created", record.id, institution_id)
    return record


@router.put("/catalog/{institution_id}/{dataset_id}", response_model=s.DatasetOut)
def edit_dataset(
    institution_id: UUID,
    dataset_id: UUID,
    body: s.DatasetInput,
    request: Request,
    membership=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    lock_institution(db, institution_id)
    record = scoped(db, Dataset, institution_id, dataset_id)
    validate_owner(db, institution_id, body)
    for key, value in body.model_dump().items():
        setattr(record, key, value)
    db.flush()
    audit(db, request, "dataset.updated", record.id, institution_id)
    return record


@router.delete("/catalog/{institution_id}/{dataset_id}", response_model=s.Message)
def delete_dataset(
    institution_id: UUID,
    dataset_id: UUID,
    request: Request,
    membership=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    record = scoped(db, Dataset, institution_id, dataset_id)
    db.execute(
        delete(IngestFile).where(
            IngestFile.institution_id == institution_id, IngestFile.dataset_id == dataset_id
        )
    )
    db.delete(record)
    audit(db, request, "dataset.deleted", dataset_id, institution_id)
    return {"message": "Dataset metadata deleted"}


@router.get("/data-sources/{institution_id}", response_model=s.Page[s.SourceOut])
def sources(
    institution_id: UUID,
    q: str = Query("", max_length=160),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    membership=Depends(tenant()),
    db=Depends(database, scope="function"),
):
    query = select(DataSource).where(DataSource.institution_id == institution_id)
    if q:
        query = query.where(DataSource.name.icontains(q, autoescape=True))
    return page(db, query.order_by(DataSource.created_at.desc(), DataSource.id), offset, limit)


@router.post("/data-sources/{institution_id}", response_model=s.SourceOut, status_code=201)
def add_source(
    institution_id: UUID,
    body: s.SourceInput,
    request: Request,
    membership=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    record = DataSource(
        institution_id=institution_id, created_by=request.state.user.id, **body.model_dump()
    )
    db.add(record)
    db.flush()
    audit(db, request, "source.created", record.id, institution_id)
    return record


@router.put("/data-sources/{institution_id}/{source_id}", response_model=s.SourceOut)
def edit_source(
    institution_id: UUID,
    source_id: UUID,
    body: s.SourceInput,
    request: Request,
    membership=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    lock_institution(db, institution_id)
    record = scoped(db, DataSource, institution_id, source_id)
    if body.category != record.category and db.scalar(
        select(Dataset.id)
        .where(Dataset.institution_id == institution_id, Dataset.source_id == source_id)
        .limit(1)
    ):
        raise HTTPException(409, "Remove dataset associations before changing category")
    for key, value in body.model_dump().items():
        setattr(record, key, value)
    db.flush()
    audit(db, request, "source.updated", record.id, institution_id)
    return record


@router.delete("/data-sources/{institution_id}/{source_id}", response_model=s.Message)
def delete_source(
    institution_id: UUID,
    source_id: UUID,
    request: Request,
    membership=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    lock_institution(db, institution_id)
    record = scoped(db, DataSource, institution_id, source_id)
    if db.scalar(
        select(Dataset.id)
        .where(Dataset.institution_id == institution_id, Dataset.source_id == source_id)
        .limit(1)
    ):
        raise HTTPException(409, "Remove dataset associations before deleting this source")
    db.delete(record)
    audit(db, request, "source.deleted", source_id, institution_id)
    return {"message": "Source definition deleted"}
