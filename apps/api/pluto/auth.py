import logging
import secrets
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from . import schemas as s
from .config import settings
from .db import database
from .models import AuthSession, PlatformAdmin, Recovery, User
from .security import (
    DUMMY_HASH,
    authenticated,
    digest,
    hasher,
    new_session,
    now,
    rate_limit,
    verify,
)
from .services import audit, deliver

router = APIRouter(prefix="/api/v1", tags=["identity"])


@router.post("/auth/register", response_model=s.Message, status_code=201)
def register(body: s.Register, request: Request, db=Depends(database, scope="function")):
    rate_limit(f"register:{request.client.host}", 20)
    password_hash = hasher.hash(body.password)
    user_id = db.scalar(
        insert(User)
        .values(email=body.email, name=body.name, password_hash=password_hash)
        .on_conflict_do_nothing(index_elements=[User.email])
        .returning(User.id)
    )
    if user_id:
        audit(db, request, "account.registered", user_id)
    return {
        "message": "If this address is available, your account is ready. Sign in or recover your password."
    }


@router.post("/auth/login", response_model=s.Me)
def login(
    body: s.Login, request: Request, response: Response, db=Depends(database, scope="function")
):
    rate_limit(f"login-ip:{request.client.host}", 60)
    rate_limit(f"login-email:{body.email}")
    user = db.scalar(select(User).where(User.email == body.email).with_for_update())
    valid = verify(user.password_hash if user else DUMMY_HASH, body.password)
    if not valid or not user or user.status != "active":
        raise HTTPException(401, "Invalid email or password")
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(body.password)
    session = new_session(db, user, response, settings)
    request.state.user = user
    audit(db, request, "session.created", user.id)
    return {
        "user": user,
        "csrf": session.csrf,
        "platform_admin": bool(
            db.scalar(select(PlatformAdmin.id).where(PlatformAdmin.user_id == user.id))
        ),
    }


@router.get("/auth/me", response_model=s.Me)
def me(request: Request, user=Depends(authenticated), db=Depends(database, scope="function")):
    return {
        "user": user,
        "csrf": request.state.session.csrf,
        "platform_admin": bool(
            db.scalar(select(PlatformAdmin.id).where(PlatformAdmin.user_id == user.id))
        ),
    }


@router.post("/auth/logout", response_model=s.Message)
def logout(
    request: Request,
    response: Response,
    user=Depends(authenticated),
    db=Depends(database, scope="function"),
):
    db.delete(request.state.session)
    response.delete_cookie("pluto_session", path="/")
    audit(db, request, "session.revoked", user.id)
    return {"message": "Signed out"}


@router.post("/auth/recovery", response_model=s.Message)
def recovery(body: s.Email, request: Request, db=Depends(database, scope="function")):
    rate_limit(f"recovery-ip:{request.client.host}", 30)
    rate_limit(f"recovery-email:{body.email}", 5)
    user = db.scalar(
        select(User).where(User.email == body.email, User.status == "active").with_for_update()
    )
    if user:
        token = secrets.token_urlsafe(32)
        db.add(
            Recovery(
                user_id=user.id, token_hash=digest(token), expires_at=now() + timedelta(minutes=30)
            )
        )
        try:
            deliver(user.email, "recovery", token)
        except HTTPException:
            logging.getLogger("pluto").error('{"event":"recovery_delivery_failed"}')
    return {"message": "If the account exists, a recovery link will be delivered."}


@router.post("/auth/reset-password", response_model=s.Message)
def reset(body: s.ResetPassword, request: Request, db=Depends(database, scope="function")):
    rate_limit(f"reset:{request.client.host}", 20)
    recovery = db.scalar(select(Recovery).where(Recovery.token_hash == digest(body.token)))
    if not recovery or recovery.used_at or recovery.expires_at <= now():
        raise HTTPException(400, "Invalid or expired link")
    user = db.scalar(select(User).where(User.id == recovery.user_id).with_for_update())
    db.refresh(recovery, with_for_update=True)
    if user.status != "active" or recovery.used_at or recovery.expires_at <= now():
        raise HTTPException(400, "Invalid or expired link")
    user.password_hash = hasher.hash(body.password)
    db.execute(
        update(Recovery)
        .where(Recovery.user_id == user.id, Recovery.used_at.is_(None))
        .values(used_at=now())
    )
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    audit(db, request, "password.recovered", user.id)
    return {"message": "Password reset. Sign in with your new password."}


@router.post("/users/password", response_model=s.Message)
def password(
    body: s.ChangePassword,
    request: Request,
    response: Response,
    user=Depends(authenticated),
    db=Depends(database, scope="function"),
):
    rate_limit(f"password:{user.id}", 10)
    db.refresh(user, with_for_update=True)
    if not verify(user.password_hash, body.current_password):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = hasher.hash(body.password)
    db.execute(
        update(Recovery)
        .where(Recovery.user_id == user.id, Recovery.used_at.is_(None))
        .values(used_at=now())
    )
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    response.delete_cookie("pluto_session", path="/")
    audit(db, request, "password.changed", user.id)
    return {"message": "Password changed. Sign in again."}


@router.get("/users/sessions", response_model=list[s.SessionOut])
def sessions(user=Depends(authenticated), db=Depends(database, scope="function")):
    return db.scalars(
        select(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.expires_at > now())
        .order_by(AuthSession.created_at.desc())
    ).all()


@router.delete("/users/sessions/{session_id}", response_model=s.Message)
def revoke(
    session_id: UUID,
    request: Request,
    user=Depends(authenticated),
    db=Depends(database, scope="function"),
):
    db.execute(
        delete(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == user.id)
    )
    audit(db, request, "session.revoked", session_id)
    return {"message": "Session revoked"}
