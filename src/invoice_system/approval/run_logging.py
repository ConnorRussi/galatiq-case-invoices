"""Audit artifacts for approval runs."""

from pathlib import Path

from ..ingestion.run_logging import RunContext, now_iso, write_artifact
from .models import ApprovalRequest, ApprovalResult


class ApprovalRunLogger:
    def __init__(self, context: RunContext):
        self.context = context
        self.context.run_dir.mkdir(parents=True, exist_ok=False)
        write_artifact(self.context.run_dir, "run.json", {"run_id": context.run_id, "started_at": now_iso()})

    def event(self, stage: str, event: str, **details: object) -> None:
        with (self.context.run_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
            import json
            handle.write(json.dumps({"timestamp": now_iso(), "stage": stage, "event": event, **details}, default=str) + "\n")

    def save_context(self, request: ApprovalRequest) -> None:
        write_artifact(self.context.run_dir, "approval_context.json", request)

    def save_result(self, result: ApprovalResult) -> None:
        write_artifact(self.context.run_dir, "approval_result.json", result)

    def save_error(self, error: Exception) -> None:
        write_artifact(
            self.context.run_dir,
            "approval_error.json",
            {"error_type": type(error).__name__, "message": str(error)},
        )
