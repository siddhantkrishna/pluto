"""Provider tokens remain encrypted; application sessions own connector authorization."""

import base64
import hashlib
import json
import secrets
import time
from datetime import timedelta
from urllib.parse import urlencode
from uuid import UUID

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import Field
from sqlalchemy import delete, select

from . import schemas as s
from .config import settings
from .db import context, database
from .models import (
    ContentChunk,
    Dataset,
    IngestFile,
    IngestJob,
    Institution,
    Membership,
    OAuthFlow,
    SourceConnection,
)
from .repository import scoped
from .security import authenticated, digest, now, tenant
from .services import audit

router = APIRouter(prefix="/api/v1/connectors", tags=["connectors"])
SCOPE = "https://www.googleapis.com/auth/drive.file"
EXPORTS = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
}
FIELDS = "id,name,mimeType,size,md5Checksum,version,modifiedTime,trashed"


def cipher():
    if not settings.credential_encryption_key:
        raise HTTPException(503, "CREDENTIAL_ENCRYPTION_KEY must be configured")
    return Fernet(settings.credential_encryption_key.encode())


def seal(value):
    return cipher().encrypt(json.dumps(value).encode()).decode()


def unseal(value):
    return json.loads(cipher().decrypt(value.encode()))


def redirect_uri():
    return settings.web_origin + "/api/v1/connectors/google/callback"


def google_request(method, url, **kwargs):
    for attempt in range(4):
        try:
            response = httpx.request(method, url, timeout=30, follow_redirects=False, **kwargs)
        except httpx.HTTPError:
            raise HTTPException(502, "Google service is unavailable") from None
        if response.status_code not in (429, 500, 502, 503, 504):
            break
        retry = response.headers.get("retry-after", "")
        delay = min(60, int(retry)) if retry.isdigit() else min(8, 2**attempt)
        time.sleep(delay + secrets.randbelow(100) / 100)
    if (
        response.status_code == 400
        and "oauth2.googleapis.com/token" in url
        and response.json().get("error") == "invalid_grant"
    ):
        raise HTTPException(403, "Google authorization was revoked; reconnect the source")
    if response.status_code in (401, 403):
        raise HTTPException(403, "Google authorization was revoked or does not permit this file")
    if response.status_code == 404:
        raise HTTPException(404, "Provider file is unavailable")
    if not response.is_success:
        raise HTTPException(502, "Google request failed; retry later")
    return (
        response.json()
        if response.content and "application/json" in response.headers.get("content-type", "")
        else {}
    )


def access(connection):
    credentials = unseal(connection.encrypted)
    result = google_request(
        "POST",
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": credentials["refresh_token"],
        },
    )
    return result["access_token"]


class Begin(s.Input):
    pass


@router.post("/{institution_id}/google/authorize", response_model=dict[str, str])
def authorize(
    institution_id: UUID,
    request: Request,
    member=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(503, "Google OAuth environment is not configured")
    cipher()
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    db.add(
        OAuthFlow(
            institution_id=institution_id,
            user_id=request.state.user.id,
            session_id=request.state.session.id,
            state_hash=digest(state),
            verifier=seal({"value": verifier}),
            expires_at=now() + timedelta(minutes=10),
        )
    )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("="),
        "code_challenge_method": "S256",
    }
    return {"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)}


@router.get("/google/callback")
def callback(
    request: Request,
    state: str = Query(max_length=128),
    code: str = Query(max_length=4096),
    user=Depends(authenticated),
    db=Depends(database, scope="function"),
):
    flow = db.scalar(
        select(OAuthFlow)
        .where(OAuthFlow.state_hash == digest(state), OAuthFlow.user_id == user.id)
        .with_for_update()
    )
    if not flow or flow.expires_at <= now() or flow.session_id != request.state.session.id:
        raise HTTPException(400, "Invalid or expired OAuth state")
    member = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id, Membership.institution_id == flow.institution_id
        )
    )
    if not member or member.role not in ("owner", "administrator"):
        raise HTTPException(403, "Institution permission required")
    if db.get(Institution, flow.institution_id).status != "active":
        raise HTTPException(403, "Institution is suspended")
    context(db, "tenant", flow.institution_id)
    result = google_request(
        "POST",
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": unseal(flow.verifier)["value"],
        },
    )
    if "refresh_token" not in result:
        raise HTTPException(400, "Google did not grant offline access; reconnect with consent")
    cursor = google_request(
        "GET",
        "https://www.googleapis.com/drive/v3/changes/startPageToken",
        headers={"Authorization": "Bearer " + result["access_token"]},
    )["startPageToken"]
    connection = SourceConnection(
        institution_id=flow.institution_id,
        provider="google",
        encrypted=seal({"refresh_token": result["refresh_token"]}),
        cursor=cursor,
    )
    db.add(connection)
    db.flush()
    audit(db, request, "google.connected", connection.id, flow.institution_id)
    db.delete(flow)
    return RedirectResponse(
        settings.web_origin + f"/workspace/{flow.institution_id}/imports", status_code=303
    )


@router.get("/{institution_id}", response_model=list[dict])
def connections(
    institution_id: UUID, member=Depends(tenant("catalog")), db=Depends(database, scope="function")
):
    return [
        {"id": c.id, "provider": c.provider, "state": c.state}
        for c in db.scalars(
            select(SourceConnection).where(SourceConnection.institution_id == institution_id)
        ).all()
    ]


@router.post("/{institution_id}/{connection_id}/picker", response_model=dict)
def picker(
    institution_id: UUID,
    connection_id: UUID,
    member=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    if not settings.google_picker_api_key or not settings.google_project_number:
        raise HTTPException(
            503, "GOOGLE_PICKER_API_KEY and GOOGLE_PROJECT_NUMBER must be configured"
        )
    connection = scoped(db, SourceConnection, institution_id, connection_id)
    if connection.state != "active" or connection.provider != "google":
        raise HTTPException(409, "Active Google connection required")
    # Google Picker requires a short-lived access token; refresh tokens/client secrets stay server-side.
    return {
        "access_token": access(connection),
        "api_key": settings.google_picker_api_key,
        "app_id": settings.google_project_number,
    }


@router.get("/{institution_id}/{connection_id}/files", response_model=dict)
def browse(
    institution_id: UUID,
    connection_id: UUID,
    page_token: str = Query("", max_length=2048),
    member=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    connection = scoped(db, SourceConnection, institution_id, connection_id)
    if connection.provider != "google" or connection.state != "active":
        raise HTTPException(409, "Active Google connection required")
    return google_request(
        "GET",
        "https://www.googleapis.com/drive/v3/files",
        headers={"Authorization": "Bearer " + access(connection)},
        params={
            "pageSize": 100,
            "pageToken": page_token,
            "fields": f"nextPageToken,files({FIELDS})",
            "q": "trashed = false",
        },
    )


class Selection(s.Input):
    dataset_id: UUID
    file_ids: list[str] = Field(min_length=1, max_length=100)


@router.post("/{institution_id}/{connection_id}/import", response_model=dict)
def import_files(
    institution_id: UUID,
    connection_id: UUID,
    body: Selection,
    request: Request,
    member=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    scoped(db, Dataset, institution_id, body.dataset_id)
    connection = scoped(db, SourceConnection, institution_id, connection_id)
    if connection.provider != "google" or connection.state != "active":
        raise HTTPException(409, "Active Google connection required")
    token = access(connection)
    ids = []
    for file_id in body.file_ids:
        if not file_id.isalnum() and any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for c in file_id
        ):
            raise HTTPException(422, "Invalid provider file identifier")
        info = google_request(
            "GET",
            "https://www.googleapis.com/drive/v3/files/" + file_id,
            headers={"Authorization": "Bearer " + token},
            params={"fields": FIELDS},
        )
        if info.get("trashed"):
            continue
        suffix = EXPORTS.get(info["mimeType"], ("", ""))[1]
        name = str(info["name"])[:240] + suffix
        from .parsers import SUPPORTED

        if name.rsplit(".", 1)[-1].lower() not in SUPPORTED:
            raise HTTPException(422, "Selected format is not supported")
        metadata = {"connection_id": str(connection_id), "provider_id": file_id, **info}
        existing = db.scalar(
            select(IngestFile).where(
                IngestFile.institution_id == institution_id,
                IngestFile.dataset_id == body.dataset_id,
                IngestFile.source_metadata["provider_id"].astext == file_id,
                IngestFile.state != "cancelled",
            )
        )
        if existing and existing.source_metadata.get("version") == info.get("version"):
            ids.append(str(existing.id))
            continue
        if existing:
            existing.state = "cancelled"
            db.execute(
                delete(ContentChunk).where(
                    ContentChunk.file_id == existing.id,
                    ContentChunk.institution_id == institution_id,
                )
            )
        record = IngestFile(
            institution_id=institution_id,
            dataset_id=body.dataset_id,
            name=name,
            size=max(1, int(info.get("size", 1))),
            received=0,
            checksum="",
            state="queued",
            source_metadata=metadata,
        )
        db.add(record)
        db.flush()
        db.add(IngestJob(institution_id=institution_id, file_id=record.id))
        ids.append(str(record.id))
    audit(db, request, "google.import_registered", connection_id, institution_id)
    return {"file_ids": ids}


@router.delete("/{institution_id}/{connection_id}", response_model=s.Message)
def disconnect(
    institution_id: UUID,
    connection_id: UUID,
    request: Request,
    member=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    connection = scoped(db, SourceConnection, institution_id, connection_id)
    if connection.state == "revoked":
        return {"message": "Source is already disconnected"}
    if connection.provider == "google":
        credentials = unseal(connection.encrypted)
        try:
            google_request(
                "POST",
                "https://oauth2.googleapis.com/revoke",
                data={"token": credentials["refresh_token"]},
            )
        except HTTPException:
            pass
    for record in db.scalars(
        select(IngestFile).where(
            IngestFile.institution_id == institution_id,
            IngestFile.source_metadata["connection_id"].astext == str(connection_id),
        )
    ):
        record.state = "cancelled"
        db.execute(
            delete(ContentChunk).where(
                ContentChunk.file_id == record.id, ContentChunk.institution_id == institution_id
            )
        )
    connection.state = "revoked"
    connection.encrypted = ""
    audit(db, request, "source.disconnected", connection_id, institution_id)
    return {"message": "Source disconnected; imported content access removed"}


@router.post("/{institution_id}/{connection_id}/sync", response_model=dict)
def synchronize(
    institution_id: UUID,
    connection_id: UUID,
    request: Request,
    member=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    connection = scoped(db, SourceConnection, institution_id, connection_id)
    if connection.provider == "postgres" and connection.state == "active":
        records = db.scalars(
            select(IngestFile)
            .where(
                IngestFile.institution_id == institution_id,
                IngestFile.source_metadata["connection_id"].astext == str(connection_id),
                IngestFile.state == "ready",
            )
            .order_by(IngestFile.created_at.desc())
        ).all()
        seen = set()
        count = 0
        for record in records:
            meta = record.source_metadata
            key = (str(record.dataset_id), meta["schema"], meta["table"])
            if key in seen or not meta.get("cursor_column"):
                continue
            seen.add(key)
            table_import(
                institution_id,
                connection_id,
                TableSelection(
                    dataset_id=record.dataset_id,
                    schema_name=meta["schema"],
                    table=meta["table"],
                    cursor_column=meta["cursor_column"],
                    after=meta.get("next_cursor"),
                ),
                request,
                member,
                db,
            )
            count += 1
        return {"updated": count, "has_more": False}
    if connection.state != "active" or connection.provider != "google":
        raise HTTPException(409, "Active Google connection required")
    token = access(connection)
    result = google_request(
        "GET",
        "https://www.googleapis.com/drive/v3/changes",
        headers={"Authorization": "Bearer " + token},
        params={
            "pageToken": connection.cursor,
            "pageSize": 100,
            "fields": f"nextPageToken,newStartPageToken,changes(fileId,removed,file({FIELDS}))",
        },
    )
    imported = 0
    for change in result.get("changes", []):
        records = db.scalars(
            select(IngestFile).where(
                IngestFile.institution_id == institution_id,
                IngestFile.source_metadata["connection_id"].astext == str(connection_id),
                IngestFile.source_metadata["provider_id"].astext == change["fileId"],
                IngestFile.state != "cancelled",
            )
        ).all()
        for record in records:
            if change.get("removed") or change.get("file", {}).get("trashed"):
                record.state = "cancelled"
                db.execute(
                    delete(ContentChunk).where(
                        ContentChunk.file_id == record.id,
                        ContentChunk.institution_id == institution_id,
                    )
                )
            elif change.get("file", {}).get("version") != record.source_metadata.get("version"):
                import_files(
                    institution_id,
                    connection_id,
                    Selection(dataset_id=record.dataset_id, file_ids=[change["fileId"]]),
                    request,
                    member,
                    db,
                )
                imported += 1
    connection.cursor = result.get(
        "nextPageToken", result.get("newStartPageToken", connection.cursor)
    )
    audit(db, request, "google.synchronized", connection_id, institution_id)
    return {"updated": imported, "has_more": bool(result.get("nextPageToken"))}


def retrieve_google(db, record, path):
    metadata = record.source_metadata
    connection = scoped(
        db, SourceConnection, record.institution_id, UUID(metadata["connection_id"])
    )
    if connection.state != "active":
        raise ValueError("Source access revoked")
    token = access(connection)
    file_id = metadata["provider_id"]
    export = EXPORTS.get(metadata["mimeType"])
    url = "https://www.googleapis.com/drive/v3/files/" + file_id + ("/export" if export else "")
    params = {"mimeType": export[0]} if export else {"alt": "media"}
    sha = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    size = 0
    with httpx.stream(
        "GET",
        url,
        params=params,
        headers={"Authorization": "Bearer " + token},
        timeout=60,
        follow_redirects=False,
    ) as response:
        if not response.is_success:
            raise ValueError("Provider content unavailable; reconnect or check permission")
        with path.open("wb") as output:
            for block in response.iter_bytes(1024 * 1024):
                size += len(block)
                if size > settings.max_upload_bytes:
                    raise ValueError("Retrieved file exceeds configured size limit")
                output.write(block)
                sha.update(block)
                md5.update(block)
    if not export and metadata.get("md5Checksum") and md5.hexdigest() != metadata["md5Checksum"]:
        raise ValueError("Provider content checksum mismatch")
    return size, sha.hexdigest()


class PostgresCredentials(s.Input):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=63)
    username: str = Field(min_length=1, max_length=63)
    password: str = Field(min_length=1, max_length=4096)


@router.post("/{institution_id}/postgres", response_model=dict)
def postgres_connect(
    institution_id: UUID,
    body: PostgresCredentials,
    request: Request,
    member=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    from .postgres_source import discover

    cipher()
    tables = discover(body.model_dump())
    connection = SourceConnection(
        institution_id=institution_id, provider="postgres", encrypted=seal(body.model_dump())
    )
    db.add(connection)
    db.flush()
    audit(db, request, "postgres.connected", connection.id, institution_id)
    return {"id": connection.id, "tables": tables}


@router.get("/{institution_id}/{connection_id}/tables", response_model=list[dict])
def tables(
    institution_id: UUID,
    connection_id: UUID,
    member=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    from .postgres_source import discover

    connection = scoped(db, SourceConnection, institution_id, connection_id)
    if connection.provider != "postgres" or connection.state != "active":
        raise HTTPException(409, "Active PostgreSQL connection required")
    return discover(unseal(connection.encrypted))


class TableSelection(s.Input):
    cursor_column: str = Field(default="", max_length=63)
    after: str | None = Field(default=None, max_length=256)
    dataset_id: UUID
    schema_name: str = Field(min_length=1, max_length=63)
    table: str = Field(min_length=1, max_length=63)


@router.post("/{institution_id}/{connection_id}/table-import", response_model=dict)
def table_import(
    institution_id: UUID,
    connection_id: UUID,
    body: TableSelection,
    request: Request,
    member=Depends(tenant("catalog")),
    db=Depends(database, scope="function"),
):
    from .postgres_source import discover

    connection = scoped(db, SourceConnection, institution_id, connection_id)
    scoped(db, Dataset, institution_id, body.dataset_id)
    if connection.provider != "postgres" or connection.state != "active":
        raise HTTPException(409, "Active PostgreSQL connection required")
    if {"schema": body.schema_name, "table": body.table} not in discover(
        unseal(connection.encrypted)
    ):
        raise HTTPException(422, "Authorized base table required")
    record = IngestFile(
        institution_id=institution_id,
        dataset_id=body.dataset_id,
        name=body.table + ".jsonl",
        size=1,
        received=0,
        checksum="",
        state="queued",
        source_metadata={
            "connection_id": str(connection_id),
            "schema": body.schema_name,
            "table": body.table,
            "provider": "postgres",
            "cursor_column": body.cursor_column,
            "after": body.after,
        },
    )
    db.add(record)
    db.flush()
    db.add(IngestJob(institution_id=institution_id, file_id=record.id))
    audit(db, request, "postgres.import_registered", record.id, institution_id)
    return {"file_id": record.id}


def remote_download(db, record):
    from urllib.parse import quote

    from fastapi.responses import StreamingResponse
    from starlette.background import BackgroundTask

    metadata = record.source_metadata
    connection = scoped(
        db, SourceConnection, record.institution_id, UUID(metadata["connection_id"])
    )
    if connection.state != "active":
        raise HTTPException(403, "Source access revoked")
    export = EXPORTS.get(metadata["mimeType"])
    token = access(connection)
    url = (
        "https://www.googleapis.com/drive/v3/files/"
        + metadata["provider_id"]
        + ("/export" if export else "")
    )
    client = httpx.Client(timeout=60, follow_redirects=False)
    try:
        response = client.send(
            client.build_request(
                "GET",
                url,
                params={"mimeType": export[0]} if export else {"alt": "media"},
                headers={"Authorization": "Bearer " + token},
            ),
            stream=True,
        )
        if not response.is_success:
            response.close()
            raise HTTPException(403, "Provider file is no longer available")
    except Exception:
        client.close()
        raise

    def close():
        response.close()
        client.close()

    def stream():
        try:
            yield from response.iter_bytes(1024 * 1024)
        finally:
            close()

    return StreamingResponse(
        stream(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(record.name)},
        background=BackgroundTask(close),
    )
