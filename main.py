"""Run invoice ingestion or its regression evaluation."""

import argparse
import logging
from pathlib import Path
import sys

from dotenv import load_dotenv

# Also allow the case's direct command before an editable install.
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from invoice_system.ingestion.evaluation import run_evaluation
from invoice_system.ingestion.models import IngestionStatus
from invoice_system.ingestion.run_logging import create_normal_run_context
from invoice_system.ingestion.runner import run_ingestion


def main() -> int:
    parser = argparse.ArgumentParser(description="Run invoice ingestion")
    parser.add_argument("--invoice_path")
    parser.add_argument("--eval-ingestion", action="store_true")
    args = parser.parse_args()
    if args.eval_ingestion:
        load_dotenv(ROOT / ".env")
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        return 0 if run_evaluation(ROOT) else 1
    if not args.invoice_path:
        parser.error("--invoice_path is required unless --eval-ingestion is used")
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    context = create_normal_run_context(ROOT / "logs", args.invoice_path)
    result = run_ingestion(args.invoice_path, artifact_context=context)
    print(f"Final status: {result.status.value}")
    if result.normalization is not None:
        print(result.normalization.invoice.model_dump_json(indent=2))
    if result.error_message:
        logging.error("[error] %s", result.error_message)
    print(f"Run artifacts: {context.run_dir}")
    return 1 if result.status == IngestionStatus.TECHNICAL_FAILURE else 0


if __name__ == "__main__":
    raise SystemExit(main())
