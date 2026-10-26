"""Logical backup and restore of one Piko schema (Phase 8).

Why this exists instead of pg_dump: a self-hoster on Windows usually has no PostgreSQL client tools, and
a backup that has never been restored is not a backup. This reads every table in one REPEATABLE READ
transaction (so tables agree with each other) and writes gzip-compressed JSON lines. Restore writes into
a schema that is already migrated to the same revision and holds no rows; it never deletes or replaces
anything. A backup contains password hashes, credential hashes and sealed push data: protect the file
like the database itself (it is created with mode 0600 and never overwritten).
"""

import gzip
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, Table, insert, select, text
from sqlalchemy.engine import Connection

from app.db.models import Base

FORMAT = "piko-backup-1"
CHUNK = 500


class BackupError(Exception):
    """Refusal with a message that is safe to show an operator (no row data)."""


@dataclass(frozen=True)
class BackupReport:
    path: Path
    sha256: str
    revision: str
    counts: dict[str, int]


def _tables() -> list[Table]:
    return list(Base.metadata.sorted_tables)  # parents before children


def _revision(conn: Connection) -> str:
    row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
    if row is None:
        raise BackupError("the schema has no migration revision; run the migrations first")
    return str(row[0])


def _encode(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _decode(table: Table, name: str, value: Any) -> Any:
    if value is None:
        return None
    python_type = table.c[name].type.python_type
    if python_type is uuid.UUID:
        return uuid.UUID(value)
    if python_type is datetime:
        return datetime.fromisoformat(value)
    if python_type is Decimal:
        return Decimal(value)
    return value


def backup(engine: Engine, destination: Path) -> BackupReport:
    destination = destination.resolve()
    if destination.exists():
        raise BackupError(f"refusing to overwrite {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with (
            os.fdopen(fd, "wb") as raw,
            gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz,
            engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn,
        ):
            revision = _revision(conn)

            def put(obj: dict[str, Any]) -> None:
                gz.write((json.dumps(obj, separators=(",", ":")) + "\n").encode())

            tables = _tables()
            put(
                {
                    "format": FORMAT,
                    "revision": revision,
                    "created_at": datetime.now(UTC).isoformat(),
                    "tables": [t.name for t in tables],
                }
            )
            for table in tables:
                n = 0
                result = conn.execution_options(stream_results=True).execute(select(table))
                for row in result.mappings():
                    put({"t": table.name, "r": {k: _encode(v) for k, v in row.items()}})
                    n += 1
                counts[table.name] = n
            put({"end": True, "counts": counts})
    except BaseException:
        destination.unlink(missing_ok=True)  # never leave a half-written file that looks real
        raise
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_name(destination.name + ".sha256").write_text(
        f"{digest}  {destination.name}\n", encoding="utf-8"
    )
    return BackupReport(destination, digest, revision, counts)


def restore(engine: Engine, source: Path) -> BackupReport:
    source = source.resolve()
    if not source.is_file():
        raise BackupError(f"no such backup file: {source}")
    sidecar = source.with_name(source.name + ".sha256")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if sidecar.is_file() and sidecar.read_text(encoding="utf-8").split()[0] != digest:
        raise BackupError("the backup file does not match its recorded checksum; it is damaged")
    by_name = {t.name: t for t in _tables()}
    with engine.begin() as conn, gzip.open(source, "rt", encoding="utf-8") as lines:
        header = json.loads(next(lines))
        if header.get("format") != FORMAT:
            raise BackupError("not a Piko backup, or an unsupported backup version")
        if _revision(conn) != header["revision"]:
            raise BackupError(
                f"the backup is at revision {header['revision']} but this schema is at "
                f"{_revision(conn)}; migrate the schema to the backup's revision first"
            )
        if set(header["tables"]) != set(by_name):
            raise BackupError("the backup's tables do not match this version of Piko")
        for table in by_name.values():
            if conn.execute(select(text("1")).select_from(table).limit(1)).first() is not None:
                raise BackupError(
                    f"table {table.name} already holds rows; restore only into an empty schema"
                )
        counts: dict[str, int] = {name: 0 for name in header["tables"]}
        current: Table | None = None
        pending: list[dict[str, Any]] = []
        footer: dict[str, Any] | None = None

        def flush() -> None:
            if current is not None and pending:
                conn.execute(insert(current), pending)
                pending.clear()

        for line in lines:
            obj = json.loads(line)
            if obj.get("end"):
                footer = obj
                break
            table = by_name[obj["t"]]
            if table is not current:
                flush()  # the backup lists whole tables, parents first, so foreign keys hold
                current = table
            pending.append({k: _decode(table, k, v) for k, v in obj["r"].items()})
            counts[table.name] += 1
            if len(pending) >= CHUNK:
                flush()
        flush()
        if footer is None or footer["counts"] != counts:
            raise BackupError("the backup is incomplete or its row counts do not match")
    return BackupReport(source, digest, header["revision"], counts)
