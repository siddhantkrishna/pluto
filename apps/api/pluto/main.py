import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from . import auth, catalog, connectors, ingestion, platform, workspaces
from .config import settings
from .db import engine

logger = logging.getLogger("pluto")
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app):
    with engine.connect() as db:
        role = db.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
        ).one()
        owns = db.execute(
            text(
                "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner=current_user"
            )
        ).scalar()
        if role.rolsuper or role.rolbypassrls or owns:
            raise RuntimeError(
                "Application database role must not own tables, be superuser, or bypass RLS"
            )
    yield


app = FastAPI(title="PLUTO Core API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    start = time.monotonic()
    if (
        request.method not in ("GET", "HEAD", "OPTIONS")
        and request.headers.get("origin") != settings.web_origin
    ):
        response = JSONResponse(
            {
                "error": {
                    "message": "Origin validation failed",
                    "request_id": request.state.request_id,
                }
            },
            status_code=403,
        )
    else:
        try:
            response = await call_next(request)
        except Exception as exc:
            response = await unexpected(request, exc)
    response.headers.update(
        {
            "X-Request-ID": request.state.request_id,
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
        }
    )
    if settings.secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    logger.info(
        json.dumps(
            {
                "request_id": request.state.request_id,
                "method": request.method,
                "route": getattr(request.scope.get("route"), "path", "unmatched"),
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - start) * 1000),
            }
        )
    )
    return response


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse(
        {"error": {"message": exc.detail, "request_id": request.state.request_id}},
        status_code=exc.status_code,
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    fields = [".".join(str(p) for p in error["loc"][1:]) for error in exc.errors()]
    return JSONResponse(
        {
            "error": {
                "message": "Invalid fields: " + ", ".join(fields),
                "request_id": request.state.request_id,
            }
        },
        status_code=422,
    )


@app.exception_handler(IntegrityError)
async def conflict(request, exc):
    return JSONResponse(
        {
            "error": {
                "message": "This change conflicts with an existing record",
                "request_id": request.state.request_id,
            }
        },
        status_code=409,
    )


@app.exception_handler(Exception)
async def unexpected(request, exc):
    logger.error(
        json.dumps({"request_id": request.state.request_id, "error_type": type(exc).__name__})
    )
    return JSONResponse(
        {
            "error": {
                "message": "Request could not be completed",
                "request_id": request.state.request_id,
            }
        },
        status_code=500,
    )


@app.get("/health", response_model=dict[str, str])
def health():
    with engine.connect() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok"}


for router in (
    auth.router,
    workspaces.router,
    catalog.router,
    platform.router,
    ingestion.router,
    connectors.router,
):
    app.include_router(router)
