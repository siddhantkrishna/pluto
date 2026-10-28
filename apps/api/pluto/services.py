import os
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from fastapi import HTTPException
from sqlalchemy import func, insert, select

from .config import settings
from .models import Audit, Institution, Membership, User


class CredentialProvider(Protocol):
    def resolve(self, reference: str) -> str: ...


class UnconfiguredCredentials:
    def resolve(self, reference: str) -> str:
        raise RuntimeError("Connector credentials are unavailable in Step 01")


def deliver(email, kind, token):
    route = "reset-password" if kind == "recovery" else "accept-invitation"
    link = f"{settings.web_origin}/{route}#token={token}"
    message = EmailMessage()
    message["Subject"] = f"PLUTO — {kind}"
    message["From"] = settings.smtp_from or "development@localhost"
    message["To"] = email
    message.set_content(
        f"Open this single-use link in PLUTO:\n{link}\nIf you did not expect this message, ignore it.",
        cte="8bit",
    )
    if settings.environment in ("development", "test") and not settings.smtp_host:
        directory = Path(settings.mail_directory)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / f"{secrets.token_hex(16)}.eml"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(message.as_string())
        return
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        raise HTTPException(503, "Email delivery is unavailable. Please retry.") from None


def audit(db, request, action, target, institution_id=None):
    user = getattr(request.state, "user", None)
    db.execute(
        insert(Audit)
        .inline()
        .values(
            actor_id=user.id if user else None,
            institution_id=institution_id,
            action=action,
            target=str(target),
            request_id=request.state.request_id,
        )
    )


def lock_institution(db, institution_id):
    return db.scalar(select(Institution).where(Institution.id == institution_id).with_for_update())


def guard_owner(db, membership, new_role=None):
    if membership.role == "owner" and new_role != "owner":
        count = db.scalar(
            select(func.count())
            .select_from(Membership)
            .join(User)
            .where(
                Membership.institution_id == membership.institution_id,
                Membership.role == "owner",
                User.status == "active",
            )
        )
        if count <= 1:
            raise HTTPException(409, "An institution must retain at least one active owner")
