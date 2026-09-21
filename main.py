"""Run the end-to-end invoice workflow or an evaluation suite."""

import argparse
import logging
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

# Also allow the case's direct command before an editable install.
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from invoice_system.ingestion.evaluation import run_evaluation
from invoice_system.ingestion.run_logging import create_normal_run_context
from invoice_system.approval.evaluation import run_approval_evaluation
from invoice_system.validation.evaluation import run_validation_evaluation
from invoice_system.workflow_evaluation import run_workflow_evaluation
from invoice_system.workflow import WorkflowStatus, run_invoice_workflow


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Run invoice processing or an evaluation suite")
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
        "--eval-workflow",
        "--eval-end-to-end",
        action="store_true",
        help="Run the live end-to-end workflow evaluation for every invoice fixture",
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
        help="Deprecated compatibility flag; normal invoice runs always perform full validation",
    )
    parser.add_argument(
        "--database-path",
        default=os.getenv("INVENTORY_DATABASE_PATH"),
        help="SQLite inventory database used by the validation stage",
    )
    parser.add_argument(
        "--ledger-path",
        default=os.getenv("INVOICE_LEDGER_PATH"),
        help="SQLite invoice-history/payment ledger used for duplicate and revision checks",
    )
    args = parser.parse_args()
    validation_eval_flags = (args.eval_validation, args.eval_semantic, args.eval_reconciliation)
    if args.eval_ingestion and (args.eval_approval or args.eval_workflow or any(validation_eval_flags)):
        parser.error("choose only one evaluation mode")
    if args.eval_approval and (args.eval_workflow or any(validation_eval_flags)):
        parser.error("choose only one evaluation mode")
    if args.eval_workflow and any(validation_eval_flags):
        parser.error("choose only one evaluation mode")
    if sum(validation_eval_flags) > 1:
        parser.error("choose only one validation evaluation mode")
    if args.eval_ingestion:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        return 0 if run_evaluation(ROOT) else 1
    if args.eval_approval:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        return 0 if run_approval_evaluation(ROOT) else 1
    if args.eval_workflow:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        return 0 if run_workflow_evaluation(ROOT, database_path=args.database_path or ROOT / "inventory.sqlite") else 1
    if any(validation_eval_flags):
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        return 0 if run_validation_evaluation(ROOT) else 1
    if not args.invoice_path:
        parser.error("--invoice_path is required unless an evaluation mode is used")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    context = create_normal_run_context(ROOT / "logs", args.invoice_path)
    database_path = args.database_path or ROOT / "inventory.sqlite"
    result = run_invoice_workflow(
        args.invoice_path,
        database_path=database_path,
        ledger_path=args.ledger_path,
        artifact_context=context,
        progress_callback=print,
    )

    print("\nFinal outcome")
    print(f"Status: {result.status.value}")
    print(f"Invoice: {result.invoice_id or Path(args.invoice_path).name}")
    print(f"Reason: {result.reason}")
    if result.approval is not None:
        print(f"VP review required: {'YES' if result.vp_review_required else 'NO'}")
    if result.payment is not None and result.payment.transaction_id is not None:
        print(f"Payment transaction: {result.payment.transaction_id}")
    print(f"Run artifacts: {context.run_dir}")
    return 0 if result.status == WorkflowStatus.APPROVED_AND_PAID else 1


if __name__ == "__main__":
    raise SystemExit(main())
