import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from pluto.config import settings
from pluto.db import engine
from pluto.main import app


@pytest.fixture(autouse=True)
def clean_database(tmp_path):
    if settings.environment != "test" or not os.environ.get("PLUTO_TEST_ALLOW_RESET") == "yes":
        pytest.fail("Use a disposable database, ENVIRONMENT=test and PLUTO_TEST_ALLOW_RESET=yes")
    admin = create_engine(settings.migration_database_url)
    with admin.begin() as db:
        db.execute(text("TRUNCATE users, institutions, rate_limits CASCADE"))
    settings.mail_directory = str(tmp_path)
    yield
    admin.dispose()
    engine.dispose()


@pytest.fixture
def client():
    with TestClient(
        app, base_url="http://localhost:8000", headers={"Origin": settings.web_origin}
    ) as client:
        yield client


@pytest.fixture
def admin_db():
    engine = create_engine(settings.migration_database_url)
    with engine.begin() as db:
        yield db
    engine.dispose()
