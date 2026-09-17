"""Atomic snapshots and append-only sanitized audit events."""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    fd, name = tempfile.mkstemp(prefix=".snapshot-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def append_event(directory: Path, *, node, counters, model=None, usage=None, latency_ms=0, outcome):
    directory.mkdir(parents=True, exist_ok=True)
    record = dict(timestamp=datetime.now(timezone.utc).isoformat(), node=node, counters=counters.model_dump(), model=model, prompt_version="ingestion-v1",
                  usage=usage or {}, latency_ms=latency_ms, outcome=outcome)
    with (directory / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
