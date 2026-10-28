"""One-time provisioning; uses the migration identity, never the serving identity."""

import os
import uuid

from pydantic import ValidationError
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.orm import Session

from .config import settings
from .models import Audit, PlatformAdmin, User
from .schemas import Register
from .security import hasher


def main():
    try:
        account = Register(
            email=os.environ["PLUTO_ADMIN_EMAIL"],
            name=os.environ["PLUTO_ADMIN_NAME"],
            password=os.environ["PLUTO_ADMIN_PASSWORD"],
        )
    except (ValidationError, KeyError):
        raise SystemExit(
            "Invalid administrator configuration. Supply email, name, and a password of at least 12 characters."
        ) from None
    with Session(create_engine(settings.migration_database_url)) as db, db.begin():
        db.execute(text("SELECT pg_advisory_xact_lock(481513)"))
        if db.scalar(select(PlatformAdmin.id).limit(1)):
            raise SystemExit("Already provisioned. Use authenticated platform administration.")
        user = db.scalar(select(User).where(User.email == account.email))
        if user:
            raise SystemExit(
                "Use a new dedicated administrator email; existing accounts are not overwritten."
            )
        user = User(
            email=account.email, name=account.name, password_hash=hasher.hash(account.password)
        )
        db.add(user)
        db.flush()
        db.add(PlatformAdmin(user_id=user.id))
        db.execute(
            insert(Audit)
            .inline()
            .values(
                actor_id=user.id,
                action="platform.bootstrap",
                target=str(user.id),
                request_id=str(uuid.uuid4()),
            )
        )
    print("Platform administrator provisioned. Remove provisioning variables from the environment.")


if __name__ == "__main__":
    main()
