"""Small file artifacts, written as each graph step completes."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel


def create_run_directory(root: Path) -> Path:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid4().hex[:8]
    directory = root / run_id
    directory.mkdir(parents=True)
    return directory


def write_artifact(directory: Path, filename: str, model: BaseModel) -> None:
    (directory / filename).write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
