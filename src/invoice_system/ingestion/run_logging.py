"""Runtime artifacts for ingestion executions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from .models import IngestionResult, IngestionStatus


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def make_run_id(source_path: str | Path, prefix: str | None = None) -> str:
    stem = Path(source_path).stem or "source"
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    parts = [timestamp, stem, uuid4().hex[:4]]
    if prefix:
        parts.insert(0, prefix)
    return "_".join(parts)


def make_evaluation_id() -> str:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{uuid4().hex[:8]}"


def create_run_directory(root: Path) -> Path:
    run_id = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
    directory = root / run_id
    directory.mkdir(parents=True)
    return directory


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(_jsonable(data), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_artifact(directory: Path, filename: str, data: object) -> None:
    write_json(directory / filename, data)


def append_event(directory: Path, stage: str, event: str, **details: object) -> None:
    """Append a stage event using the same schema as ingestion run logs."""

    payload = {"timestamp": now_iso(), "stage": stage, "event": event}
    payload.update({key: _jsonable(value) for key, value in details.items() if value is not None})
    with (directory / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _jsonable(data: object) -> object:
    if isinstance(data, BaseModel):
        return data.model_dump(mode="json")
    if isinstance(data, Path):
        return str(data)
    if isinstance(data, dict):
        return {str(key): _jsonable(value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [_jsonable(item) for item in data]
    return data


@dataclass(frozen=True)
class RunContext:
    run_id: str
    run_dir: Path


class IngestionRunLogger:
    """Writes one ingestion run's artifacts as stages complete."""

    def __init__(self, context: RunContext, source_path: str | Path):
        self.context = context
        self.source_path = str(source_path)
        self.source_filename = Path(source_path).name
        self.started_at = now_iso()
        self.completed_at: str | None = None
        self.status: str | None = None
        self.revision_count = 0
        self.context.run_dir.mkdir(parents=True, exist_ok=False)
        self._write_run()

    @property
    def run_dir(self) -> Path:
        return self.context.run_dir

    def log_event(self, stage: str, event: str, **details: object) -> None:
        append_event(self.run_dir, stage, event, **details)

    def save_source(self, source_document: BaseModel) -> None:
        write_artifact(self.run_dir, "source.json", source_document)

    def save_normalization(self, normalization: BaseModel, version: int) -> None:
        write_artifact(self.run_dir, f"normalized_v{version}.json", normalization)

    def save_critique(self, critique: BaseModel, version: int) -> None:
        write_artifact(self.run_dir, f"critique_v{version}.json", critique)

    def save_result(self, result: IngestionResult) -> None:
        if result.normalization is not None:
            write_artifact(self.run_dir, "normalized.json", result.normalization)
        write_artifact(self.run_dir, "result.json", result)

    def finish(self, result: IngestionResult) -> None:
        self.status = result.status.value
        self.revision_count = result.revision_count
        self.completed_at = now_iso()
        self._write_run()

    def finish_failure(self, revision_count: int = 0) -> None:
        self.status = IngestionStatus.TECHNICAL_FAILURE.value
        self.revision_count = revision_count
        self.completed_at = now_iso()
        self._write_run()

    def _write_run(self) -> None:
        write_artifact(
            self.run_dir,
            "run.json",
            {
                "run_id": self.context.run_id,
                "source_path": self.source_path,
                "source_filename": self.source_filename,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "status": self.status,
                "revision_count": self.revision_count,
            },
        )


def create_normal_run_context(logs_root: Path, source_path: str | Path) -> RunContext:
    run_id = make_run_id(source_path)
    return RunContext(run_id=run_id, run_dir=logs_root / "runs" / run_id)
