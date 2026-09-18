"""Machine-readable snapshots plus a concise report for human diagnosis."""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def atomic_json(path: Path, value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def atomic_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".snapshot-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def append_event(directory: Path, *, stage: str, outcome: str, message: str, details: dict | None = None):
    directory.mkdir(parents=True, exist_ok=True)
    event = {"timestamp": datetime.now(timezone.utc).isoformat(), "stage": stage, "outcome": outcome, "message": message, "details": details or {}}
    with (directory / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")


def write_human_report(directory: Path, result):
    event_path = directory / "events.jsonl"
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()] if event_path.exists() else []
    marker = {"success": "OK", "failed": "FAILED", "skipped": "SKIPPED"}
    lines = ["# Ingestion run report", "", f"**Status:** `{result.status}`", f"**Run ID:** `{result.run_id}`", "", "## Timeline", ""]
    for event in events:
        lines.append(f"- **{marker.get(event['outcome'], event['outcome'].upper())} — {event['stage']}**: {event['message']}")
    lines.extend(["", "## Extracted handoff", ""])
    if result.invoice is None:
        lines.append("No schema-valid invoice was produced.")
    else:
        values = [getattr(result.invoice, name).normalized for name in type(result.invoice).model_fields if name != "line_items"]
        lines.extend([f"- Resolved header/total fields: {sum(value is not None for value in values)}", f"- Extracted line items: {len(result.invoice.line_items)}"])
    if result.issues:
        lines.extend(["", "## Issues", ""])
        lines.extend(f"- `{issue.code}`: {issue.message}" for issue in result.issues)
    lines.extend(["", "## Files", ""])
    files = [
        ("extracted-text.txt", "text provided to the model"),
        ("extraction.json", "text blocks and evidence locators"),
        ("model-response.json", "schema-valid model output"),
        ("events.jsonl", "machine-readable event stream"),
        ("result.json", "final handoff"),
    ]
    for name, description in files:
        availability = description if (directory / name).exists() else f"not written — {description}"
        lines.append(f"- `{name}` — {availability}")
    lines.append("")
    atomic_text(directory / "run-report.md", "\n".join(lines))
