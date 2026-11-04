"""Structured logs: one JSON object per line, carrying the job, dispute and merchant being worked on, so a
single case can be followed through API, worker and agent logs (e.g. in Render's log search)."""
from __future__ import annotations

import contextvars
import json
import logging
from datetime import datetime, timezone

job_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("job_id", default=None)
dispute_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("dispute_id", default=None)
merchant_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("merchant_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
                 "level": record.levelname.lower(), "logger": record.name, "msg": record.getMessage()}
        for key, var in (("job_id", job_id), ("dispute_id", dispute_id), ("merchant_id", merchant_id)):
            if value := var.get():
                entry[key] = value
        for key in ("kind", "outcome", "duration_ms", "error"):
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("sal")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False
