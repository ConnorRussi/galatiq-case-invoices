"""Deterministic baseline and extraction-recheck eligibility."""
from ..ingestion.models import IngestionResult, Invoice as InvoiceCandidate
from .models import IngestionRecheckRequest, ValidationCheck, ValidationSettings


def invoice_fields(invoice: InvoiceCandidate):
    for name in type(invoice).model_fields:
        if name != "line_items":
            yield name, getattr(invoice, name)
    for index, row in enumerate(invoice.line_items):
        for name in type(row).model_fields:
            yield f"line_items[{index}].{name}", getattr(row, name)


def baseline_checks(invoice: InvoiceCandidate | None, settings: ValidationSettings) -> list[ValidationCheck]:
    # Keep missing prerequisites visible, rather than deleting their checks.
    codes = ["INGESTION_HANDOFF", "REQUIRED_INPUTS", "LINE_ITEM_ARITHMETIC",
             "SUBTOTAL_RECONCILIATION", "INVOICE_TOTAL", "CONSOLIDATE_ITEMS",
             "INVENTORY_AVAILABILITY", "DATE_CONSISTENCY"]
    if settings.high_value_threshold is not None:
        codes.append("HIGH_VALUE_POLICY")
    return [ValidationCheck(code=code) for code in codes]


def eligible_rechecks(handoff: IngestionResult) -> list[IngestionRecheckRequest]:
    """Only extraction issues authorize a recheck, never business-rule findings."""
    if handoff.invoice is None:
        return []
    fields = dict(invoice_fields(handoff.invoice))
    requests = {}
    issue_reasons = {
        "AMBIGUOUS_FIELD": "AMBIGUOUS_EXTRACTION",
        "AMBIGUOUS_EXTRACTION": "AMBIGUOUS_EXTRACTION",
        "SOURCE_CONTRADICTION": "SOURCE_CONTRADICTION",
        "UNSUPPORTED_EVIDENCE": "MISSING_EXPECTED_EVIDENCE",
        "MISSING_EXPECTED_EVIDENCE": "MISSING_EXPECTED_EVIDENCE",
    }
    for issue in handoff.issues:
        if issue.code in issue_reasons and issue.field in fields:
            requests[issue.field] = IngestionRecheckRequest(
                fields=[issue.field], reason_code=issue_reasons[issue.code],
                explanation=issue.message, evidence=issue.evidence or fields[issue.field].evidence,
            )
    return list(requests.values())


def recheck_is_justified(request: IngestionRecheckRequest, handoff: IngestionResult) -> bool:
    eligible = {r.fields[0]: r for r in eligible_rechecks(handoff)}
    if not all(path in eligible and eligible[path].reason_code == request.reason_code for path in request.fields):
        return False
    evidence = [e for path in request.fields for e in eligible[path].evidence]
    return all(e in evidence for e in request.evidence)


def verify_targeted_result(before: IngestionResult, after: IngestionResult, request: IngestionRecheckRequest):
    """Re-ingestion may revise only requested fields, on the same source document."""
    if before.source != after.source:
        raise ValueError("Re-ingestion changed the source document")
    if before.invoice is None or after.invoice is None:
        raise ValueError("Re-ingestion did not return an invoice candidate")
    old, new = dict(invoice_fields(before.invoice)), dict(invoice_fields(after.invoice))
    if old.keys() != new.keys():
        raise ValueError("Targeted re-ingestion changed the source row structure")
    for path, field in old.items():
        if path not in request.fields and new[path] != field:
            raise ValueError(f"Re-ingestion changed an untargeted field: {path}")
    for issue in before.issues:
        if issue.field not in request.fields and issue not in after.issues:
            raise ValueError("Re-ingestion removed an untargeted ingestion issue")
