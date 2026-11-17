"""Append-only audit log: one JSON line per run, drilldown and refusal (spec section 7).

Keys: timestamp, role, action, inputs, success, message. This is the only file the API writes.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "audit.jsonl"
KEYS = ("timestamp", "role", "action", "inputs", "success", "message")


class AuditLog:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else DEFAULT_LOG_PATH
        self._lock = threading.Lock()

    def write(self, role: Any, action: str, inputs: dict[str, Any], success: bool, message: str) -> dict[str, Any]:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "action": action,
            "inputs": inputs,
            "success": bool(success),
            "message": message,
        }
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        return entry

    def read(self, limit: int = 50) -> list[dict[str, Any]]:
        """Most recent entries first."""
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        out = []
        for line in reversed(lines):
            if len(out) >= limit:
                break
            if line.strip():
                out.append(json.loads(line))
        return out
