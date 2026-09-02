from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class CompletedJob:
    id: int
    source_hash: str
    output_path: Path
    archive_path: Path | None


class JobStore:
    def __init__(self, database_path: Path):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = database_path
        self._schema_lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._schema_lock, self._session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_hash TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    output_path TEXT,
                    archive_path TEXT,
                    duplicate_of INTEGER,
                    metrics_json TEXT,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    FOREIGN KEY(duplicate_of) REFERENCES jobs(id)
                );
                CREATE INDEX IF NOT EXISTS jobs_hash_status
                    ON jobs(source_hash, status);
                CREATE INDEX IF NOT EXISTS jobs_started_at
                    ON jobs(started_at);
                """
            )

    def find_completed(self, source_hash: str) -> CompletedJob | None:
        with self._session() as connection:
            row = connection.execute(
                """SELECT id, source_hash, output_path, archive_path
                   FROM jobs
                   WHERE source_hash = ? AND status = 'completed'
                   ORDER BY id DESC LIMIT 1""",
                (source_hash,),
            ).fetchone()
        if not row or not row["output_path"]:
            return None
        return CompletedJob(
            id=int(row["id"]),
            source_hash=str(row["source_hash"]),
            output_path=Path(row["output_path"]),
            archive_path=Path(row["archive_path"]) if row["archive_path"] else None,
        )

    def start(self, source: Path, source_hash: str) -> int:
        now = datetime.now(UTC).isoformat()
        with self._session() as connection:
            cursor = connection.execute(
                """INSERT INTO jobs
                   (source_hash, source_name, source_path, status, started_at)
                   VALUES (?, ?, ?, 'processing', ?)""",
                (source_hash, source.name, str(source), now),
            )
            return int(cursor.lastrowid)

    def finish(
        self,
        job_id: int,
        output: Path,
        archived: Path,
        metrics: dict[str, object],
    ) -> None:
        with self._session() as connection:
            connection.execute(
                """UPDATE jobs
                   SET status = 'completed', output_path = ?, archive_path = ?,
                       metrics_json = ?, finished_at = ?
                   WHERE id = ?""",
                (
                    str(output),
                    str(archived),
                    json.dumps(metrics, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                    job_id,
                ),
            )

    def finish_duplicate(
        self, job_id: int, completed_job_id: int, output: Path, archived: Path
    ) -> None:
        with self._session() as connection:
            connection.execute(
                """UPDATE jobs
                   SET status = 'duplicate', duplicate_of = ?, output_path = ?,
                       archive_path = ?, finished_at = ?
                   WHERE id = ?""",
                (
                    completed_job_id,
                    str(output),
                    str(archived),
                    datetime.now(UTC).isoformat(),
                    job_id,
                ),
            )

    def fail(self, job_id: int, error: str, archived: Path | None = None) -> None:
        with self._session() as connection:
            connection.execute(
                """UPDATE jobs
                   SET status = 'failed', error = ?, archive_path = ?, finished_at = ?
                   WHERE id = ?""",
                (
                    error,
                    str(archived) if archived else None,
                    datetime.now(UTC).isoformat(),
                    job_id,
                ),
            )

    def recent(self, limit: int = 20) -> list[dict[str, object]]:
        with self._session() as connection:
            rows = connection.execute(
                """SELECT id, source_name, status, output_path, archive_path,
                          error, started_at, finished_at
                   FROM jobs ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
