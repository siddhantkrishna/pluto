from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def database():
    with SessionLocal() as db, db.begin():
        yield db


def context(db, key, value):
    db.execute(
        text("SELECT set_config(:key, :value, true)"), {"key": f"pluto.{key}", "value": str(value)}
    )
