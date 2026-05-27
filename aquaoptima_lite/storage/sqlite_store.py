"""SQLite-backed audit store.

The store appends one row per cycle.  Every column is a string and the
heavy payloads are JSON.  Cycles are append-only: there is no update
or delete API at this layer.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Tuple


_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def schema_sql() -> str:
    """Return the on-disk schema as a single SQL string."""

    return _SCHEMA_PATH.read_text(encoding="utf-8")


def _isoformat_utc(when: Optional[datetime] = None) -> str:
    if when is None:
        when = datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.isoformat()


def _to_jsonable(value: Any) -> Any:
    """Recursively convert dataclasses/tuples to JSON-friendly primitives."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_jsonable(v) for v in value]
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(_to_jsonable(value), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class AuditRecord:
    """A row in the ``audit_cycle`` table after deserialisation."""

    id: int
    created_at: str
    site_id: str
    runtime_mode: str
    config_hash: str
    snapshot: Mapping[str, Any] = field(default_factory=dict)
    quality: Mapping[str, Any] = field(default_factory=dict)
    recommendation: Mapping[str, Any] = field(default_factory=dict)
    authority: Mapping[str, Any] = field(default_factory=dict)
    learner_shadow: Mapping[str, Any] = field(default_factory=dict)


class SQLiteAuditStore:
    """Thin wrapper around :mod:`sqlite3` for the audit table.

    The store owns its connection.  Passing ``":memory:"`` (the default)
    is convenient for tests; production callers should pass a filesystem
    path.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._path = str(path) if not isinstance(path, str) else path
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(schema_sql())

    # ------------------------------------------------------------------
    # Lifecycle

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SQLiteAuditStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Writes

    def record_cycle(
        self,
        *,
        site_id: str,
        runtime_mode: str,
        config_hash: str,
        snapshot: Any,
        quality: Any,
        recommendation: Any,
        authority: Any,
        learner_shadow: Any = None,
        created_at: Optional[str] = None,
    ) -> int:
        ts = created_at or _isoformat_utc()
        with self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO audit_cycle (
                    created_at, site_id, runtime_mode, config_hash,
                    snapshot_json, quality_json, recommendation_json, authority_json,
                    learner_shadow_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    site_id,
                    runtime_mode,
                    config_hash,
                    _json_dumps(snapshot),
                    _json_dumps(quality),
                    _json_dumps(recommendation),
                    _json_dumps(authority),
                    None if learner_shadow is None else _json_dumps(learner_shadow),
                ),
            )
        return int(cur.lastrowid)

    def attach_learner_shadow(self, audit_id: int, learner_shadow: Any) -> None:
        """Attach shadow-only learner evidence to an existing audit row."""

        with self._conn:
            self._conn.execute(
                "UPDATE audit_cycle SET learner_shadow_json = ? WHERE id = ?",
                (_json_dumps(learner_shadow), int(audit_id)),
            )

    # ------------------------------------------------------------------
    # Reads

    def _row_to_record(self, row: sqlite3.Row) -> AuditRecord:
        return AuditRecord(
            id=int(row["id"]),
            created_at=str(row["created_at"]),
            site_id=str(row["site_id"]),
            runtime_mode=str(row["runtime_mode"]),
            config_hash=str(row["config_hash"]),
            snapshot=json.loads(row["snapshot_json"]),
            quality=json.loads(row["quality_json"]),
            recommendation=json.loads(row["recommendation_json"]),
            authority=json.loads(row["authority_json"]),
            learner_shadow=(
                {}
                if "learner_shadow_json" not in row.keys()
                or row["learner_shadow_json"] is None
                else json.loads(row["learner_shadow_json"])
            ),
        )

    def count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM audit_cycle")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def latest(self, site_id: Optional[str] = None) -> Optional[AuditRecord]:
        if site_id is None:
            cur = self._conn.execute(
                "SELECT * FROM audit_cycle ORDER BY id DESC LIMIT 1"
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM audit_cycle WHERE site_id = ? ORDER BY id DESC LIMIT 1",
                (site_id,),
            )
        row = cur.fetchone()
        return None if row is None else self._row_to_record(row)

    def list_records(
        self,
        *,
        site_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditRecord]:
        if limit <= 0:
            return []
        if site_id is None:
            cur = self._conn.execute(
                "SELECT * FROM audit_cycle ORDER BY id DESC LIMIT ?",
                (int(limit),),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM audit_cycle WHERE site_id = ? ORDER BY id DESC LIMIT ?",
                (site_id, int(limit)),
            )
        return [self._row_to_record(r) for r in cur.fetchall()]

    def iter_records(self) -> Iterable[AuditRecord]:
        cur = self._conn.execute("SELECT * FROM audit_cycle ORDER BY id ASC")
        for row in cur.fetchall():
            yield self._row_to_record(row)

    # ------------------------------------------------------------------
    # Helpers (for tests/introspection)

    def tables(self) -> Tuple[str, ...]:
        cur = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
        return tuple(str(r[0]) for r in cur.fetchall())
