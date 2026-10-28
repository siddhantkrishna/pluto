"""Allowlisted, DNS-pinned PostgreSQL access; SQL identifiers are never interpolated."""

import ipaddress
import json
import socket

import psycopg
from fastapi import HTTPException
from psycopg import sql

from .config import settings


def connect(credentials):
    host = credentials["host"]
    if host not in settings.postgres_allowed_hosts.split(","):
        raise HTTPException(
            422, "Database hostname is not allowlisted by the installation operator"
        )
    addresses = {
        item[4][0]
        for item in socket.getaddrinfo(host, credentials.get("port", 5432), type=socket.SOCK_STREAM)
    }
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise HTTPException(422, "Database target must resolve exclusively to public addresses")
    connection = psycopg.connect(
        host=host,
        hostaddr=sorted(addresses)[0],
        port=credentials.get("port", 5432),
        dbname=credentials["database"],
        user=credentials["username"],
        password=credentials["password"],
        connect_timeout=10,
        sslmode="verify-full",
        sslrootcert="system",
        options="-c default_transaction_read_only=on -c statement_timeout=30000 -c lock_timeout=5000",
    )
    connection.read_only = True
    return connection


def discover(credentials):
    with connect(credentials) as db:
        role = db.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()
        if role[0]:
            raise ValueError("Use a non-superuser read-only database account")
        writable = db.execute(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_type='BASE TABLE' AND table_schema NOT IN ('pg_catalog','information_schema') AND has_table_privilege(format('%I.%I',table_schema,table_name),'INSERT,UPDATE,DELETE,TRUNCATE'))"
        ).fetchone()[0]
        if writable:
            raise ValueError("Database account has write privileges; provide a SELECT-only account")
        return [
            {"schema": row[0], "table": row[1]}
            for row in db.execute(
                "SELECT table_schema,table_name FROM information_schema.tables WHERE table_type='BASE TABLE' AND table_schema NOT IN ('pg_catalog','information_schema') ORDER BY 1,2 LIMIT 500"
            )
        ]


def retrieve(credentials, metadata, path):
    schema, table = metadata["schema"], metadata["table"]
    last_cursor = metadata.get("after")
    if {"schema": schema, "table": table} not in discover(credentials):
        raise ValueError("Table is not an authorized base table")
    with (
        connect(credentials) as db,
        db.cursor(name="pluto_import") as cursor,
        path.open("w", encoding="utf-8") as output,
    ):
        cursor.itersize = 128
        query = sql.SQL("SELECT * FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table))
        column = metadata.get("cursor_column")
        params = []
        if column:
            primary = db.execute(
                "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey) WHERE i.indrelid=to_regclass(%s) AND i.indisprimary AND i.indnatts=1",
                (sql.Identifier(schema, table).as_string(db),),
            ).fetchone()
            if not primary or primary[0] != column:
                raise ValueError(
                    "Incremental cursor must be a single-column primary key; append-only sources only"
                )
            if last_cursor is not None:
                query += sql.SQL(" WHERE {} > %s").format(sql.Identifier(column))
                params.append(last_cursor)
            query += sql.SQL(" ORDER BY {}").format(sql.Identifier(column))
        if column:
            query += sql.SQL(" LIMIT 100000")
        cursor.execute(query, params)
        names = [column.name for column in cursor.description]
        for row in cursor:
            line = (
                json.dumps(dict(zip(names, row, strict=True)), default=str, ensure_ascii=False)
                + "\n"
            )
            if len(line.encode()) > settings.max_record_bytes:
                raise ValueError("Database row exceeds configured record limit")
            output.write(line)
            if column:
                last_cursor = str(row[names.index(column)])
            if output.tell() > settings.max_upload_bytes:
                raise ValueError("Database snapshot exceeds configured import limit")

    return last_cursor
