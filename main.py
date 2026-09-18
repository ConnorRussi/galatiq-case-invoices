"""Run one invoice through Phase 1 ingestion."""

import argparse
import logging
from pathlib import Path
import sys
import traceback

from dotenv import load_dotenv

# Also allow the case's direct command before an editable install.
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from invoice_system.ingestion.graph import build_graph
from invoice_system.ingestion.run_logging import create_run_directory, write_artifact


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize one invoice with source evidence")
    parser.add_argument("--invoice_path", required=True)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    directory = None
    try:
        directory = create_run_directory(ROOT / "runs")
        print(f"Run artifacts: {directory}", file=sys.stderr)
        state = {"source_path": args.invoice_path, "source_document": None, "normalization": None}
        for update in build_graph().stream(state, stream_mode="updates"):
            if "read_source" in update:
                write_artifact(directory, "source.json", update["read_source"]["source_document"])
            if "normalize" in update:
                result = update["normalize"]["normalization"]
                write_artifact(directory, "normalized.json", result)
                print(result.invoice.model_dump_json(indent=2))
        return 0
    except Exception as exc:
        logging.error("[error] %s", exc)
        if directory is not None:
            (directory / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
