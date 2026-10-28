from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, select, text

from . import schemas as s
from .db import context, database
from .models import Audit, AuthSession, Institution, Membership, PlatformAdmin, User
from .repository import page
from .security import platform
from .services import audit, guard_owner, lock_institution

router = APIRouter(prefix="/api/v1/platform", tags=["platform"])


@router.get("/institutions", response_model=s.Page[s.InstitutionOut])
def institutions(
    q: str = Query("", max_length=160),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user=Depends(platform),
    db=Depends(database, scope="function"),
):
    query = select(Institution)
    if q:
        query = query.where(Institution.name.icontains(q, autoescape=True))
    return page(db, query.order_by(Institution.created_at.desc(), Institution.id), offset, limit)


@router.patch("/institutions/{institution_id}", response_model=s.InstitutionOut)
def status(
    institution_id: UUID,
    body: s.StatusInput,
    request: Request,
    user=Depends(platform),
    db=Depends(database, scope="function"),
):
    institution = lock_institution(db, institution_id)
    if not institution:
        raise HTTPException(404, "Institution not found")
    institution.status = body.status
    audit(db, request, "platform.institution." + body.status, institution_id)
    db.flush()
    return institution


@router.get("/administrators", response_model=list[s.UserOut])
def administrators(user=Depends(platform), db=Depends(database, scope="function")):
    return db.scalars(
        select(User).join(PlatformAdmin, PlatformAdmin.user_id == User.id).order_by(User.email)
    ).all()


@router.post("/administrators", response_model=s.Message)
def add_admin(
    body: s.Email, request: Request, user=Depends(platform), db=Depends(database, scope="function")
):
    db.execute(text("SELECT pg_advisory_xact_lock(481513)"))
    target = db.scalar(select(User).where(User.email == body.email, User.status == "active"))
    if not target:
        raise HTTPException(404, "Active account not found")
    if not db.scalar(select(PlatformAdmin.id).where(PlatformAdmin.user_id == target.id)):
        db.add(PlatformAdmin(user_id=target.id))
        audit(db, request, "platform.administrator.added", target.id)
    return {"message": "Administrator added"}


@router.delete("/administrators/{user_id}", response_model=s.Message)
def remove_admin(
    user_id: UUID, request: Request, user=Depends(platform), db=Depends(database, scope="function")
):
    db.execute(text("SELECT pg_advisory_xact_lock(481513)"))
    admins = db.scalars(select(PlatformAdmin)).all()
    if len(admins) <= 1:
        raise HTTPException(409, "At least one platform administrator must remain")
    db.execute(delete(PlatformAdmin).where(PlatformAdmin.user_id == user_id))
    audit(db, request, "platform.administrator.removed", user_id)
    return {"message": "Administrator removed"}


@router.get("/users", response_model=s.Page[s.UserOut])
def users(
    q: str = Query("", max_length=160),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user=Depends(platform),
    db=Depends(database, scope="function"),
):
    query = select(User)
    if q:
        query = query.where(User.email.icontains(q, autoescape=True))
    return page(db, query.order_by(User.created_at.desc(), User.id), offset, limit)


@router.patch("/users/{user_id}", response_model=s.Message)
def account_status(
    user_id: UUID,
    body: s.AccountStatus,
    request: Request,
    user=Depends(platform),
    db=Depends(database, scope="function"),
):
    # Owners must transfer ownership before global account suspension.
    db.execute(text("SELECT pg_advisory_xact_lock(481513)"))
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "Account not found")
    if db.scalar(select(PlatformAdmin.id).where(PlatformAdmin.user_id == user_id)):
        raise HTTPException(409, "Remove platform administrator privileges first")
    context(db, "user", user_id)
    memberships = db.scalars(
        select(Membership).where(Membership.user_id == user_id).order_by(Membership.institution_id)
    ).all()
    for membership in memberships:
        lock_institution(db, membership.institution_id)
        context(db, "tenant", membership.institution_id)
        if body.status == "disabled":
            guard_owner(db, membership)
    target.status = body.status
    if body.status == "disabled":
        db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    audit(db, request, "platform.account." + body.status, user_id)
    return {"message": "Account status updated"}


@router.get("/audit", response_model=s.Page[s.AuditOut])
def history(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user=Depends(platform),
    db=Depends(database, scope="function"),
):
    return page(
        db,
        select(Audit)
        .where(Audit.institution_id.is_(None), Audit.action.startswith("platform."))
        .order_by(Audit.created_at.desc(), Audit.id),
        offset,
        limit,
    )
