"""Create development-only configuration without default or checked-in secrets."""
import os
import secrets
from pathlib import Path


def configure(destination=Path('.env')):
    owner, app = secrets.token_hex(24), secrets.token_hex(24)
    content = f'''# Generated for local Docker development only.
POSTGRES_PASSWORD={owner}
PLUTO_DB_PASSWORD={app}
DATABASE_URL=postgresql+psycopg://pluto_app:{app}@db:5432/pluto
MIGRATION_DATABASE_URL=postgresql+psycopg://pluto_migrator:{owner}@db:5432/pluto
ENVIRONMENT=development
WEB_ORIGIN=http://localhost:3000
API_INTERNAL_URL=http://api:8000
MAIL_DIRECTORY=/app/.dev-mail
'''
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as file:
        file.write(content)
    return content


if __name__ == '__main__':
    configure()
    print('Created .env with unique development credentials. Existing files are never overwritten.')
