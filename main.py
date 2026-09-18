"""Application boundary for the invoice system's command-line interface.

This module selects inputs, starts a top-level pipeline, and reports its result.
Document parsing deliberately lives below this boundary.
"""

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from invoice_system.ingestion.models import BatchResult

PROJECT_ROOT = Path(__file__).resolve().parent
class OrchestrationError(RuntimeError):
    """Raised when the CLI cannot determine a usable input set."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest invoice documents.")
    parser.add_argument(
        "--invoice_path",
        "--invoice-path",
        action="append",
        help="Invoice path; may be repeated.",
    )
    parser.add_argument(
        "--review-file", "--ingest-file", dest="review_file",
        help="Ingest exactly one file and print its result and audit JSON paths.",
    )
    return parser


def _resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _select_inputs(
    paths: Iterable[str | Path],
    *,
    review_file: str | Path | None,
) -> list[Path]:
    """Apply CLI input rules before handing paths to the ingestion package."""

    selected = [_resolve(path) for path in paths]
    if review_file is not None:
        if selected:
            raise OrchestrationError("--review-file cannot be combined with invoice paths")
        return [_resolve(review_file)]
    if not selected:
        raise OrchestrationError("Provide --invoice_path or --review-file")
    return selected


def run(
    paths: Iterable[str | Path],
    *,
    review_file: str | Path | None = None,
) -> "BatchResult":
    """Run one high-level application pipeline for the selected invoice paths."""

    selected = _select_inputs(
        paths,
        review_file=review_file,
    )
    # The CLI knows which documents to process; the ingestion package owns what
    # happens to each document after this call.
    from invoice_system.ingestion import ingest

    return ingest(selected)


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    return value


def _review_output(path: Path, batch: "BatchResult") -> dict[str, Any]:
    """Shape the single-file result for a human inspecting persisted artifacts."""

    item = batch.results[0]
    artifact = Path(item.artifact) if item.artifact else None
    return {
        "input": str(path),
        "artifact_directory": str(artifact.parent) if artifact else None,
        "extraction_file": str(artifact.parent / "extraction.json") if artifact else None,
        "human_report": str(artifact.parent / "run-report.md") if artifact else None,
        "event_log": str(artifact.parent / "events.jsonl") if artifact else None,
        "result_file": str(artifact) if artifact else None,
        "result": _json_value(item.result),
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        batch = run(
            args.invoice_path or [],
            review_file=args.review_file,
        )
    except OrchestrationError as exc:
        parser.error(str(exc))
    # Reporting stays here because it is an application concern. The returned
    # BatchResult remains the handoff object for future validation/approval steps.
    if args.review_file:
        print(json.dumps(_review_output(_resolve(args.review_file), batch), indent=2, default=str))
    else:
        print(json.dumps(_json_value(batch), indent=2, default=str))
    return 0 if getattr(batch, "status", "completed") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
