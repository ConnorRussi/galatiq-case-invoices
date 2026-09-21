"""Durable invoice identity, revision, and payment-history boundary.

The ledger is deliberately separate from the inventory database.  Inventory
answers what can be fulfilled; this store answers whether a business invoice
version has already been processed or paid.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Literal

from pydantic import BaseModel

from .ingestion.models import IngestionResult


LedgerDisposition = Literal[
    "NEW",
    "RETRY_UNPAID",
    "DUPLICATE_SUPPRESSED",
    "HUMAN_REVIEW_PENDING",
    "REVISION_BEFORE_PAYMENT",
    "REVISION_AFTER_PAYMENT",
    "UNIDENTIFIED",
]


class InvoiceHistoryDecision(BaseModel):
    """The deterministic identity decision supplied to approval and UI layers."""

    case_key: str | None = None
    vendor: str | None = None
    invoice_number: str | None = None
    current_revision: str | None = None
    source_hash: str
    disposition: LedgerDisposition
    requires_human_review: bool = False
    prior_version_id: int | None = None
    prior_revision: str | None = None
    prior_amount: Decimal | None = None
    current_amount: Decimal | None = None
    adjustment_amount: Decimal | None = None
    prior_payment_transaction_id: str | None = None
    prior_payment_status: str | None = None
    reason: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split()).strip()
    return value.casefold() or None


def source_hash(ingestion: IngestionResult) -> str:
    """Hash source content, independent of the local filename or path."""

    document = ingestion.source_document
    if document is None:
        return hashlib.sha256(ingestion.source_path.encode("utf-8")).hexdigest()
    payload = {
        "file_type": document.file_type,
        "chunks": [{"id": chunk.id, "text": chunk.text} for chunk in document.chunks],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def revision_from_ingestion(ingestion: IngestionResult) -> str | None:
    """Read an explicit revision while retaining source truth outside the LLM."""

    if ingestion.normalization is not None:
        additional = ingestion.normalization.invoice.additional_fields
        for key in ("revision", "invoice_revision", "version"):
            value = additional.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()
    document = ingestion.source_document
    if document is None:
        return None
    text = "\n".join(chunk.text for chunk in document.chunks)
    patterns = (
        r'(?i)["\'](?:revision|invoice_revision|version)["\']\s*:\s*["\']([^"\']+)',
        r"(?im)^\s*(?:revision|invoice\s+revision|version)\s*[:=]\s*([^\s,]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def invoice_amount(ingestion: IngestionResult) -> Decimal | None:
    if ingestion.normalization is None:
        return None
    invoice = ingestion.normalization.invoice
    return invoice.amount_due if invoice.amount_due is not None else invoice.invoice_total


class InvoiceLedger:
    """SQLite-backed invoice history and payment claim store."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self.path), timeout=30)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS invoice_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_key TEXT,
                vendor TEXT,
                invoice_number TEXT,
                revision TEXT,
                source_hash TEXT NOT NULL,
                source_path TEXT NOT NULL,
                received_at TEXT NOT NULL,
                workflow_status TEXT,
                payment_status TEXT NOT NULL DEFAULT 'NOT_ATTEMPTED',
                payment_transaction_id TEXT,
                amount TEXT,
                currency TEXT,
                supersedes_version_id INTEGER,
                FOREIGN KEY (supersedes_version_id) REFERENCES invoice_versions(id),
                UNIQUE(case_key, source_hash)
            );
            CREATE INDEX IF NOT EXISTS idx_invoice_versions_case
                ON invoice_versions(case_key, received_at);
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "InvoiceLedger":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def register(self, ingestion: IngestionResult) -> InvoiceHistoryDecision:
        if ingestion.normalization is None:
            raise ValueError("Invoice history requires a normalized invoice")
        invoice = ingestion.normalization.invoice
        vendor = invoice.vendor.strip() if invoice.vendor else None
        invoice_number = invoice.invoice_number.strip() if invoice.invoice_number else None
        digest = source_hash(ingestion)
        revision = revision_from_ingestion(ingestion)
        amount = invoice_amount(ingestion)
        currency = invoice.currency

        if not vendor or not invoice_number:
            return InvoiceHistoryDecision(
                source_hash=digest,
                disposition="UNIDENTIFIED",
                reason="Vendor and invoice number are required for duplicate detection.",
                current_amount=amount,
            )

        case_key = f"{_canonical(vendor)}::{_canonical(invoice_number)}"
        existing = self._connection.execute(
            "SELECT * FROM invoice_versions WHERE case_key = ? AND source_hash = ?",
            (case_key, digest),
        ).fetchone()
        if existing is not None:
            if existing["payment_status"] in {"CLAIMED", "SUCCESS"} or existing["workflow_status"] == "APPROVED_AND_PAID":
                return self._decision(
                    case_key=case_key,
                    vendor=vendor,
                    invoice_number=invoice_number,
                    revision=revision,
                    digest=digest,
                    disposition="DUPLICATE_SUPPRESSED",
                    existing=existing,
                    amount=amount,
                    reason="This exact invoice version has already been paid; no second payment will be attempted.",
                )
            if existing["workflow_status"] == "HUMAN_REVIEW_REQUIRED":
                return self._decision(
                    case_key=case_key,
                    vendor=vendor,
                    invoice_number=invoice_number,
                    revision=revision,
                    digest=digest,
                    disposition="HUMAN_REVIEW_PENDING",
                    existing=existing,
                    amount=amount,
                    requires_human_review=True,
                    reason="This invoice version is already awaiting human review; it cannot be retried for payment.",
                )
            return self._decision(
                case_key=case_key,
                vendor=vendor,
                invoice_number=invoice_number,
                revision=revision,
                digest=digest,
                disposition="RETRY_UNPAID",
                existing=existing,
                amount=amount,
                reason="This invoice version was seen before but has not been paid.",
            )

        prior = self._connection.execute(
            "SELECT * FROM invoice_versions WHERE case_key = ? ORDER BY id DESC LIMIT 1",
            (case_key,),
        ).fetchone()
        prior_paid = prior is not None and prior["payment_status"] in {"CLAIMED", "SUCCESS"}
        disposition: LedgerDisposition = (
            "REVISION_AFTER_PAYMENT" if prior_paid else "REVISION_BEFORE_PAYMENT"
        ) if prior is not None else "NEW"
        review = disposition == "REVISION_AFTER_PAYMENT"
        reason = (
            "A new invoice version arrived after a prior version was paid; human review is required."
            if review
            else "A new version supersedes an unpaid prior version."
            if prior is not None
            else "No prior invoice version was found."
        )
        self._connection.execute(
            """INSERT INTO invoice_versions
               (case_key, vendor, invoice_number, revision, source_hash, source_path,
                received_at, amount, currency, supersedes_version_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (case_key, vendor, invoice_number, revision, digest, ingestion.source_path,
             _now(), str(amount) if amount is not None else None, currency,
             prior["id"] if prior is not None else None),
        )
        self._connection.commit()
        return InvoiceHistoryDecision(
            case_key=case_key,
            vendor=vendor,
            invoice_number=invoice_number,
            current_revision=revision,
            source_hash=digest,
            disposition=disposition,
            requires_human_review=review,
            prior_version_id=prior["id"] if prior is not None else None,
            prior_revision=prior["revision"] if prior is not None else None,
            prior_amount=Decimal(prior["amount"]) if prior is not None and prior["amount"] else None,
            current_amount=amount,
            adjustment_amount=(amount - Decimal(prior["amount"])) if prior is not None and prior["amount"] and amount is not None else None,
            prior_payment_transaction_id=prior["payment_transaction_id"] if prior is not None else None,
            prior_payment_status=prior["payment_status"] if prior is not None else None,
            reason=reason,
        )

    def claim_payment(self, decision: InvoiceHistoryDecision) -> bool:
        """Atomically claim the current version for one payment attempt."""

        if not decision.case_key:
            return True
        cursor = self._connection.execute(
            """UPDATE invoice_versions SET payment_status = 'CLAIMED'
               WHERE case_key = ? AND source_hash = ?
               AND payment_status NOT IN ('CLAIMED', 'SUCCESS')""",
            (decision.case_key, decision.source_hash),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def complete(
        self,
        decision: InvoiceHistoryDecision,
        *,
        workflow_status: str,
        payment_status: str | None = None,
        transaction_id: str | None = None,
    ) -> None:
        if not decision.case_key:
            return
        self._connection.execute(
            """UPDATE invoice_versions SET workflow_status = ?,
               payment_status = COALESCE(?, payment_status), payment_transaction_id = ?
               WHERE case_key = ? AND source_hash = ?""",
            (workflow_status, payment_status, transaction_id, decision.case_key, decision.source_hash),
        )
        if workflow_status == "APPROVED_AND_PAID" and decision.prior_version_id is not None:
            self._connection.execute(
                "UPDATE invoice_versions SET workflow_status = 'SUPERSEDED' WHERE id = ? AND payment_status = 'NOT_ATTEMPTED'",
                (decision.prior_version_id,),
            )
        self._connection.commit()

    def _decision(self, *, case_key: str, vendor: str, invoice_number: str,
                  revision: str | None, digest: str, disposition: LedgerDisposition,
                  existing: sqlite3.Row, amount: Decimal | None,
                  requires_human_review: bool = False, reason: str) -> InvoiceHistoryDecision:
        prior_amount = Decimal(existing["amount"]) if existing["amount"] else None
        return InvoiceHistoryDecision(
            case_key=case_key,
            vendor=vendor,
            invoice_number=invoice_number,
            current_revision=revision,
            source_hash=digest,
            disposition=disposition,
            requires_human_review=requires_human_review,
            prior_version_id=existing["id"],
            prior_revision=existing["revision"],
            prior_amount=prior_amount,
            current_amount=amount,
            prior_payment_transaction_id=existing["payment_transaction_id"],
            prior_payment_status=existing["payment_status"],
            reason=reason,
        )
