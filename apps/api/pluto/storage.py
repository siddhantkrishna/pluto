"""Private filesystem objects; keys contain server-generated UUIDs only."""

import os
from pathlib import Path
from typing import Protocol
from uuid import UUID

from .config import settings


class ObjectStore(Protocol):
    def path(self, institution_id: UUID, file_id: UUID) -> Path: ...


class LocalObjects:
    def path(self, institution_id: UUID, file_id: UUID) -> Path:
        institution_id, file_id = UUID(str(institution_id)), UUID(str(file_id))
        root = Path(settings.object_directory).resolve()
        directory = root / str(institution_id)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink() or directory.resolve().parent != root:
            raise ValueError("Invalid object directory")
        path = directory / str(file_id)
        if path.is_symlink():
            raise ValueError("Invalid object path")
        return path

    def append(self, institution_id, file_id, offset, data):
        path = self.path(institution_id, file_id)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+b") as output:
            # Database progress is authoritative after a crash before commit.
            output.truncate(offset)
            output.seek(offset)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())


objects = LocalObjects()
