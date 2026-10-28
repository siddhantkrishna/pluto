import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import create_engine, select, text

from .config import settings
from .db import context, database
from .models import AuthSession, Institution, Membership, PlatformAdmin, User

rate_engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=2, max_overflow=2)

hasher = PasswordHasher(type=Type.ID)
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))
PERMISSIONS = {
    "owner": {"read", "catalog", "members", "owners", "settings", "audit"},
    "administrator": {"read", "catalog", "members", "settings", "audit"},
    "analyst": {"read"},
    "viewer": {"read"},
}


def now():
    return datetime.now(UTC)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def verify(encoded, password):
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def rate_limit(key, limit=10):
    # A separate committed transaction keeps failed attempts counted across workers.
    with rate_engine.begin() as db:
        count = db.execute(
            text("""
            INSERT INTO rate_limits (key, "window", count) VALUES (:key, now(), 1)
            ON CONFLICT (key) DO UPDATE SET
              count = CASE WHEN rate_limits."window" < now() - interval '15 minutes' THEN 1 ELSE rate_limits.count + 1 END,
              "window" = CASE WHEN rate_limits."window" < now() - interval '15 minutes' THEN now() ELSE rate_limits."window" END
            RETURNING count
        """),
            {"key": digest(key)},
        ).scalar_one()
    if count > limit:
        raise HTTPException(
            429, "Too many attempts. Try again later.", headers={"Retry-After": "900"}
        )


def authenticated(request: Request, db=Depends(database, scope="function")):
    token = request.cookies.get("pluto_session", "")
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == digest(token), AuthSession.expires_at > now()
        )
    )
    user = db.get(User, session.user_id) if session else None
    if user is None or user.status != "active":
        raise HTTPException(401, "Authentication required")
    if request.method not in ("GET", "HEAD", "OPTIONS") and not secrets.compare_digest(
        request.headers.get("X-CSRF-Token", ""), session.csrf
    ):
        raise HTTPException(403, "CSRF validation failed")
    context(db, "user", user.id)
    request.state.user = user
    request.state.session = session
    return user


def platform(request: Request, user=Depends(authenticated), db=Depends(database, scope="function")):
    if not db.scalar(select(PlatformAdmin.id).where(PlatformAdmin.user_id == user.id)):
        raise HTTPException(403, "Platform administrator required")
    context(db, "platform", "true")
    return user


def tenant(permission="read"):
    def dependency(
        request: Request, user=Depends(authenticated), db=Depends(database, scope="function")
    ):
        try:
            institution_id = UUID(request.path_params["institution_id"])
        except ValueError:
            raise HTTPException(404, "Workspace not found") from None
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            db.scalar(select(Institution).where(Institution.id == institution_id).with_for_update())
        membership = db.scalar(
            select(Membership).where(
                Membership.institution_id == institution_id, Membership.user_id == user.id
            )
        )
        institution = db.get(Institution, institution_id)
        if membership is None or institution is None:
            raise HTTPException(404, "Workspace not found")
        if institution.status != "active":
            raise HTTPException(403, "Institution is suspended")
        if permission not in PERMISSIONS[membership.role]:
            raise HTTPException(403, "Permission denied")
        context(db, "tenant", institution_id)
        request.state.membership = membership
        return membership

    return dependency


def new_session(db, user, response, settings):
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    session = AuthSession(
        user_id=user.id,
        token_hash=digest(token),
        csrf=csrf,
        expires_at=now() + timedelta(hours=settings.session_hours),
    )
    db.add(session)
    response.set_cookie(
        "pluto_session",
        token,
        httponly=True,
        secure=settings.secure,
        samesite="lax",
        max_age=settings.session_hours * 3600,
        path="/",
    )
    return session
