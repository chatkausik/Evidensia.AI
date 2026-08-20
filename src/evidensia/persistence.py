from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalStateStore:
    """Small SQLite state store for durable local product workflows."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = str(Path(path).resolve()) if path else ":memory:"
        if path:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._create_schema()

    def _create_schema(self) -> None:
        statements = [
            "CREATE TABLE IF NOT EXISTS research_runs (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS research_events (run_id TEXT NOT NULL, position INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (run_id, position))",
            "CREATE INDEX IF NOT EXISTS idx_research_events_run_id ON research_events(run_id)",
            "CREATE TABLE IF NOT EXISTS experiments (experiment_id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS feedback (feedback_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)",
            "CREATE INDEX IF NOT EXISTS idx_feedback_run_id ON feedback(run_id)",
            "CREATE TABLE IF NOT EXISTS saved_searches (search_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS collections (collection_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)",
        ]
        with self._lock, self._connection:
            for statement in statements:
                self._connection.execute(statement)
            self._connection.execute("PRAGMA optimize")

    @staticmethod
    def _json(payload: Any) -> str:
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json")
        return json.dumps(payload, ensure_ascii=False, default=str)

    def save_run(self, run_id: str, payload: Any) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO research_runs(run_id, payload, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (run_id, self._json(payload), _now()),
            )

    def list_runs(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute("SELECT payload FROM research_runs ORDER BY updated_at DESC").fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def save_event(self, run_id: str, position: int, payload: Any) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO research_events(run_id, position, payload, created_at) VALUES (?, ?, ?, ?)",
                (run_id, position, self._json(payload), _now()),
            )

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM research_events WHERE run_id = ? ORDER BY position", (run_id,)
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def add_experiment(self, payload: Any) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO experiments(payload, created_at) VALUES (?, ?)", (self._json(payload), _now())
            )

    def list_experiments(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute("SELECT payload FROM experiments ORDER BY experiment_id DESC").fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def add_feedback(self, run_id: str, payload: Any) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO feedback(run_id, payload, created_at) VALUES (?, ?, ?)",
                (run_id, self._json(payload), _now()),
            )

    def save_named(self, table: str, identifier_field: str, identifier: str, payload: Any) -> None:
        if (table, identifier_field) not in {("saved_searches", "search_id"), ("collections", "collection_id")}:
            raise ValueError("Unsupported state table")
        sql = (
            f"INSERT INTO {table}({identifier_field}, payload, updated_at) VALUES (?, ?, ?) "
            f"ON CONFLICT({identifier_field}) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at"
        )
        with self._lock, self._connection:
            self._connection.execute(sql, (identifier, self._json(payload), _now()))

    def list_named(self, table: str) -> list[dict[str, Any]]:
        if table not in {"saved_searches", "collections"}:
            raise ValueError("Unsupported state table")
        with self._lock:
            rows = self._connection.execute(f"SELECT payload FROM {table} ORDER BY updated_at DESC").fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def get_named(self, table: str, identifier_field: str, identifier: str) -> dict[str, Any] | None:
        if (table, identifier_field) not in {("saved_searches", "search_id"), ("collections", "collection_id")}:
            raise ValueError("Unsupported state table")
        with self._lock:
            row = self._connection.execute(
                f"SELECT payload FROM {table} WHERE {identifier_field} = ?", (identifier,)
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def delete_named(self, table: str, identifier_field: str, identifier: str) -> bool:
        if (table, identifier_field) not in {("saved_searches", "search_id"), ("collections", "collection_id")}:
            raise ValueError("Unsupported state table")
        with self._lock, self._connection:
            cursor = self._connection.execute(f"DELETE FROM {table} WHERE {identifier_field} = ?", (identifier,))
        return cursor.rowcount > 0
