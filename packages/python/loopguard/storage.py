"""Local storage backend for Loop-Guard sessions and tool events."""

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional


class SessionStore:
    """Stores session execution telemetry in memory and optional SQLite."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self._memory_sessions: Dict[str, Dict[str, Any]] = {}
        if self.db_path:
            self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    state TEXT,
                    trip_reason TEXT,
                    total_cost_usd REAL,
                    current_depth INTEGER,
                    updated_at REAL,
                    payload TEXT
                )
                """
            )
            conn.commit()

    def save_session(self, session_data: Dict[str, Any]):
        session_id = session_data.get("session_id")
        if not session_id:
            return

        self._memory_sessions[session_id] = session_data

        if self.db_path:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO sessions (session_id, state, trip_reason, total_cost_usd, current_depth, updated_at, payload)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(session_id) DO UPDATE SET
                            state=excluded.state,
                            trip_reason=excluded.trip_reason,
                            total_cost_usd=excluded.total_cost_usd,
                            current_depth=excluded.current_depth,
                            updated_at=excluded.updated_at,
                            payload=excluded.payload
                        """,
                        (
                            session_id,
                            session_data.get("state"),
                            session_data.get("trip_reason"),
                            session_data.get("budget", {}).get("total_cost_usd", 0.0),
                            session_data.get("current_depth", 0),
                            time.time(),
                            json.dumps(session_data),
                        )
                    )
                    conn.commit()
            except Exception:
                pass

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        if session_id in self._memory_sessions:
            return self._memory_sessions[session_id]

        if self.db_path:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT payload FROM sessions WHERE session_id = ?", (session_id,))
                row = cur.fetchone()
                if row:
                    return json.loads(row[0])
        return None

    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        # Return newest first
        sessions = list(self._memory_sessions.values())
        sessions.reverse()
        return sessions[:limit]
