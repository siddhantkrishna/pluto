from alembic import context
from sqlalchemy import create_engine
from pluto.config import settings
from pluto.models import Base

if context.is_offline_mode():
    context.configure(
        url=settings.migration_database_url, target_metadata=Base.metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(settings.migration_database_url).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
