"""Run invoice ingestion or an evaluation suite."""

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
from invoice_system.approval.evaluation import run_approval_evaluation
from invoice_system.validation import ValidationStatus, run_validation
from invoice_system.validation.evaluation import run_validation_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description="Run invoice ingestion or evaluation")
    parser.add_argument("--invoice_path")
    parser.add_argument("--eval-ingestion", action="store_true")
    parser.add_argument(
        "--eval-approval",
        action="store_true",
        help="Run the standalone final approval evaluation",
    )
    parser.add_argument(
        "--eval-validation",
        action="store_true",
        help="Run the end-to-end Validation Agent evaluation",
    )
    parser.add_argument(
        "--eval-semantic",
        action="store_true",
        help="Compatibility alias for --eval-validation",
    )
    parser.add_argument(
        "--eval-reconciliation",
        action="store_true",
        help="Compatibility alias for --eval-validation",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run Semantic, Reconciliation, and Database validation after ingestion",
    )
    args = parser.parse_args()
    validation_eval_flags = (args.eval_validation, args.eval_semantic, args.eval_reconciliation)
    if args.eval_ingestion and (args.eval_approval or any(validation_eval_flags)):
        parser.error("choose only one evaluation mode")
    if args.eval_approval and any(validation_eval_flags):
        parser.error("choose only one evaluation mode")
    if sum(validation_eval_flags) > 1:
        parser.error("choose only one validation evaluation mode")
    if args.eval_ingestion:
        load_dotenv(ROOT / ".env")
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        return 0 if run_evaluation(ROOT) else 1
    if args.eval_approval:
        load_dotenv(ROOT / ".env")
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        return 0 if run_approval_evaluation(ROOT) else 1
    if any(validation_eval_flags):
        load_dotenv(ROOT / ".env")
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        return 0 if run_validation_evaluation(ROOT) else 1
    if not args.invoice_path:
        parser.error("--invoice_path is required unless an evaluation mode is used")
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
    if result.status == IngestionStatus.TECHNICAL_FAILURE:
        return 1
    if args.validate:
        validation = run_validation(
            result,
            artifact_context=context,
            run_reconciliation=True,
            run_database=True,
        )
        print(f"Validation status: {validation.status.value}")
        print(validation.model_dump_json(indent=2))
        return 1 if validation.status == ValidationStatus.DENIED else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
