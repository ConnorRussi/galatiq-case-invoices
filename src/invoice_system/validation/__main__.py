"""Validate a persisted ingestion result without invoking extraction or an LLM."""
import argparse
from pathlib import Path

from ..ingestion.models import IngestionResult
from .models import ValidationSettings
from .workflow import validate_invoice


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path, help="Ingestion result.json path")
    parser.add_argument("--inventory-db", type=Path, default=Path("inventory.sqlite"))
    parser.add_argument("--max-tool-calls", type=int, default=6)
    args = parser.parse_args(argv)
    try:
        handoff = IngestionResult.model_validate_json(args.handoff.read_text(encoding="utf-8"))
        settings = ValidationSettings(max_tool_calls=args.max_tool_calls)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    report = validate_invoice(handoff, settings=settings, inventory_path=args.inventory_db)
    print(report.model_dump_json(indent=2))
    # Exit status describes invocation success, not a payment decision.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
