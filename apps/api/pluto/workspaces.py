import secrets
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from . import schemas as s
from .db import context, database
from .models import (
    Audit,
    Dataset,
    Institution,
    InstitutionSettings,
    Invitation,
    Membership,
    User,
)
from .repository import page, scoped
from .security import authenticated, digest, now, rate_limit, tenant
from .services import audit, deliver, guard_owner, lock_institution

router = APIRouter(prefix="/api/v1", tags=["workspaces"])


@router.get("/institutions", response_model=list[s.Workspace])
def institutions(user=Depends(authenticated), db=Depends(database, scope="function")):
    rows = db.execute(
        select(Institution, Membership.role)
        .join(Membership, Membership.institution_id == Institution.id)
        .where(Membership.user_id == user.id)
        .order_by(Institution.name)
    ).all()
    return [{"institution": institution, "role": role} for institution, role in rows]


@router.post("/institutions", response_model=s.InstitutionOut, status_code=201)
def create(
    body: s.InstitutionInput,
    request: Request,
    user=Depends(authenticated),
    db=Depends(database, scope="function"),
):
    rate_limit(f"institution:{user.id}", 10)
    institution = Institution(name=body.name, created_by=user.id)
    db.add(institution)
    db.flush()
    context(db, "tenant", institution.id)
    db.add(Membership(institution_id=institution.id, user_id=user.id, role="owner"))
    db.add(InstitutionSettings(institution_id=institution.id))
    audit(db, request, "institution.created", institution.id, institution.id)
    return institution


@router.get("/institutions/{institution_id}/settings", response_model=s.SettingsOut)
def get_settings(
    institution_id: UUID, membership=Depends(tenant()), db=Depends(database, scope="function")
):
    institution = db.get(Institution, institution_id)
    settings = db.scalar(
        select(InstitutionSettings).where(InstitutionSettings.institution_id == institution_id)
    )
    return {"name": institution.name, "description": settings.description}


@router.put("/institutions/{institution_id}/settings", response_model=s.SettingsOut)
def edit_settings(
    institution_id: UUID,
    body: s.SettingsInput,
    request: Request,
    membership=Depends(tenant("settings")),
    db=Depends(database, scope="function"),
):
    institution = lock_institution(db, institution_id)
    institution.name = body.name
    settings = db.scalar(
        select(InstitutionSettings).where(InstitutionSettings.institution_id == institution_id)
    )
    settings.description = body.description
    audit(db, request, "settings.updated", institution_id, institution_id)
    return body


@router.get("/memberships/{institution_id}", response_model=s.Page[s.MemberOut])
def members(
    institution_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    membership=Depends(tenant()),
    db=Depends(database, scope="function"),
):
    query = (
        select(Membership)
        .where(Membership.institution_id == institution_id)
        .order_by(Membership.created_at, Membership.id)
    )
    result = page(db, query, offset, limit)
    result["items"] = [
        dict(
            id=m.id,
            user_id=m.user_id,
            role=m.role,
            name=(u := db.get(User, m.user_id)).name,
            email=u.email,
            status=u.status,
        )
        for m in result["items"]
    ]
    return result


@router.patch("/memberships/{institution_id}/{member_id}", response_model=s.Message)
def change_role(
    institution_id: UUID,
    member_id: UUID,
    body: s.RoleInput,
    request: Request,
    membership=Depends(tenant("members")),
    db=Depends(database, scope="function"),
):
    lock_institution(db, institution_id)
    target = scoped(db, Membership, institution_id, member_id)
    if membership.role != "owner" and (
        target.role in ("owner", "administrator") or body.role in ("owner", "administrator")
    ):
        raise HTTPException(403, "Only owners can manage administrators and owners")
    guard_owner(db, target, body.role)
    target.role = body.role
    audit(db, request, "membership.role_changed", member_id, institution_id)
    return {"message": "Role updated"}


@router.delete("/memberships/{institution_id}/{member_id}", response_model=s.Message)
def remove_member(
    institution_id: UUID,
    member_id: UUID,
    request: Request,
    membership=Depends(tenant("members")),
    db=Depends(database, scope="function"),
):
    lock_institution(db, institution_id)
    target = scoped(db, Membership, institution_id, member_id)
    if membership.role != "owner" and target.role in ("owner", "administrator"):
        raise HTTPException(403, "Only owners can remove administrators and owners")
    guard_owner(db, target)
    if db.scalar(
        select(Dataset.id)
        .where(Dataset.institution_id == institution_id, Dataset.owner_id == target.user_id)
        .limit(1)
    ):
        raise HTTPException(409, "Reassign this member’s datasets before removal")
    db.delete(target)
    audit(db, request, "membership.removed", member_id, institution_id)
    return {"message": "Member removed"}


@router.post("/invitations/accept", response_model=s.InstitutionOut)
def accept(
    body: s.Token,
    request: Request,
    user=Depends(authenticated),
    db=Depends(database, scope="function"),
):
    context(db, "invitation", digest(body.token))
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == digest(body.token)))
    if (
        not invitation
        or invitation.email != user.email
        or invitation.accepted_at
        or invitation.revoked_at
        or invitation.expires_at <= now()
    ):
        raise HTTPException(400, "Invalid or expired invitation")
    institution = lock_institution(db, invitation.institution_id)
    context(db, "tenant", institution.id)
    db.refresh(invitation, with_for_update=True)
    if invitation.accepted_at or invitation.revoked_at or invitation.expires_at <= now():
        raise HTTPException(400, "Invalid or expired invitation")
    if institution.status != "active":
        raise HTTPException(403, "Institution is suspended")
    context(db, "tenant", institution.id)
    if db.scalar(
        select(Membership.id).where(
            Membership.institution_id == institution.id, Membership.user_id == user.id
        )
    ):
        raise HTTPException(409, "Already a member")
    db.add(Membership(institution_id=institution.id, user_id=user.id, role=invitation.role))
    invitation.accepted_at = now()
    audit(db, request, "invitation.accepted", invitation.id, institution.id)
    return institution


@router.get("/invitations/{institution_id}", response_model=s.Page[s.InviteOut])
def invitations(
    institution_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    membership=Depends(tenant("members")),
    db=Depends(database, scope="function"),
):
    return page(
        db,
        select(Invitation)
        .where(Invitation.institution_id == institution_id)
        .order_by(Invitation.created_at.desc(), Invitation.id),
        offset,
        limit,
    )


@router.post("/invitations/{institution_id}", response_model=s.InviteOut, status_code=201)
def invite(
    institution_id: UUID,
    body: s.InviteInput,
    request: Request,
    membership=Depends(tenant("members")),
    db=Depends(database, scope="function"),
):
    rate_limit(f"invite:{request.state.user.id}", 30)
    lock_institution(db, institution_id)
    if membership.role != "owner" and body.role in ("owner", "administrator"):
        raise HTTPException(403, "Only owners can invite administrators and owners")
    existing = db.scalar(
        select(Membership.id)
        .join(User)
        .where(Membership.institution_id == institution_id, User.email == body.email)
    )
    if existing:
        raise HTTPException(409, "This account is already a member")
    pending = db.scalars(
        select(Invitation).where(
            Invitation.institution_id == institution_id,
            Invitation.email == body.email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
    ).all()
    for old in pending:
        old.revoked_at = now()
    token = secrets.token_urlsafe(32)
    invitation = Invitation(
        institution_id=institution_id,
        email=body.email,
        role=body.role,
        token_hash=digest(token),
        expires_at=now() + timedelta(days=7),
        invited_by=request.state.user.id,
    )
    db.add(invitation)
    db.flush()
    deliver(body.email, "invitation", token)
    audit(db, request, "invitation.created", invitation.id, institution_id)
    return invitation


@router.delete("/invitations/{institution_id}/{invitation_id}", response_model=s.Message)
def revoke(
    institution_id: UUID,
    invitation_id: UUID,
    request: Request,
    membership=Depends(tenant("members")),
    db=Depends(database, scope="function"),
):
    invitation = scoped(db, Invitation, institution_id, invitation_id)
    if membership.role != "owner" and invitation.role in ("owner", "administrator"):
        raise HTTPException(403, "Only owners can revoke this invitation")
    invitation.revoked_at = now()
    audit(db, request, "invitation.revoked", invitation.id, institution_id)
    return {"message": "Invitation revoked"}


@router.get("/audit/{institution_id}", response_model=s.Page[s.AuditOut])
def history(
    institution_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    membership=Depends(tenant("audit")),
    db=Depends(database, scope="function"),
):
    return page(
        db,
        select(Audit)
        .where(Audit.institution_id == institution_id)
        .order_by(Audit.created_at.desc(), Audit.id),
        offset,
        limit,
    )
