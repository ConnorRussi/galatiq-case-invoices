"""Deterministic predicates over source claims and trusted tool results."""
from datetime import date

from ..ingestion.models import Invoice
from .models import CheckStatus as Status, ValidationCheck, ValidationFinding, ValidationSettings, ValidationState
from .policy import baseline_checks, eligible_rechecks, invoice_fields
from .tools import decimal_value, is_absent, text_value


def _finding(code, message, *, severity="blocking", field=None, subject=None, expected=None, actual=None, evidence=()):
    return ValidationFinding(code=code, severity=severity, message=message, field=field,
                             subject=subject, expected=str(expected) if expected is not None else None,
                             actual=str(actual) if actual is not None else None, evidence=list(evidence))


def _unavailable(message, field=None, evidence=()):
    return _finding("VALIDATION_DATA_UNAVAILABLE", message, severity="unresolved", field=field, evidence=evidence)


def _finish(check, findings, *, skip=None):
    check.finding_codes = list(dict.fromkeys(f.code for f in findings))
    unresolved = [f.message for f in findings if f.severity == "unresolved"]
    # A partially checked set stays unresolved, even when other rows failed.
    if unresolved:
        check.status = Status.UNRESOLVED
        check.unresolved_reason = "; ".join(unresolved)
    elif findings:
        check.status = Status.FAILED
    elif skip:
        check.status = Status.SKIPPED
        check.skip_reason = skip
    else:
        check.status = Status.PASSED


def _required_inputs(invoice):
    findings = []
    required = {"invoice_number": text_value, "vendor": text_value,
                "declared_total": decimal_value, "currency": text_value}
    for name, reader in required.items():
        field = getattr(invoice, name)
        if reader(field) is None:
            findings.append(_unavailable(f"Required input {name} is unavailable", name, field.evidence))
    if not isinstance(invoice.invoice_date.normalized, date):
        findings.append(_unavailable("Invoice date is unavailable", "invoice_date", invoice.invoice_date.evidence))
    if not invoice.line_items:
        findings.append(_unavailable("No line items available", "line_items"))
    for index, row in enumerate(invoice.line_items):
        for name, reader in (("name", text_value), ("quantity", decimal_value), ("unit_price", decimal_value)):
            field = getattr(row, name)
            path = f"line_items[{index}].{name}"
            value = reader(field)
            if value is None:
                findings.append(_unavailable(f"Required input {path} is unavailable", path, field.evidence))
            elif (name == "quantity" and value <= 0) or (name == "unit_price" and value < 0):
                findings.append(_finding("INVALID_LINE_ITEM_VALUE", "Quantity must be positive and price nonnegative",
                                         field=path, actual=value, evidence=field.evidence))
    # Optional-but-present fields that failed normalization must not disappear.
    for path, field in invoice_fields(invoice):
        if not is_absent(field) and field.normalized is None:
            if not any(f.field == path for f in findings):
                findings.append(_unavailable(f"Present source field {path} is unnormalized", path, field.evidence))
    return findings


def evaluate_technical_rules(state: ValidationState, settings: ValidationSettings):
    invoice = state.handoff.invoice
    checks = baseline_checks(invoice, settings)
    checks = [c for c in checks if c.code != "HIGH_VALUE_POLICY"]
    for code in state.additional_checks:
        if code not in {c.code for c in checks} and not (code == "HIGH_VALUE_POLICY" and settings.high_value_threshold is not None):
            checks.append(ValidationCheck(code=code))
    findings = []
    calls = {name: [c.id for c in state.tool_calls if c.tool == name]
             for name in ("recalculate_invoice", "consolidate_items", "get_inventory")}
    for check in checks:
        current, skip = [], None
        code = check.code
        if code == "INGESTION_HANDOFF":
            if state.handoff.status != "ready_for_validation":
                current.append(_unavailable(f"Ingestion status: {state.handoff.status}"))
            for issue in state.handoff.issues:
                current.append(_finding("INGESTION_ISSUE_UNRESOLVED", f"{issue.code}: {issue.message}",
                                        severity="unresolved", field=issue.field, evidence=issue.evidence))
            for request in eligible_rechecks(state.handoff):
                if not any(f.field == request.fields[0] for f in current):
                    current.append(_unavailable(request.explanation, request.fields[0], request.evidence))
        elif invoice is None:
            current.append(_unavailable("No normalized invoice candidate is available"))
        elif code == "REQUIRED_INPUTS":
            current = _required_inputs(invoice)
        elif code in {"LINE_ITEM_ARITHMETIC", "SUBTOTAL_RECONCILIATION", "INVOICE_TOTAL"}:
            check.tool_calls = calls["recalculate_invoice"]
            facts = state.arithmetic
            if facts is None:
                errors = [c.error for c in state.tool_calls if c.tool == "recalculate_invoice" and c.error]
                current.append(_unavailable(errors[-1] if errors else "Arithmetic tool facts are unavailable"))
            elif code == "LINE_ITEM_ARITHMETIC":
                compared = 0
                if not facts.lines:
                    current.append(_unavailable("No line items available for arithmetic"))
                for line in facts.lines:
                    row = invoice.line_items[line.source_row]
                    path = f"line_items[{line.source_row}].declared_amount"
                    evidence = row.quantity.evidence + row.unit_price.evidence + row.declared_amount.evidence
                    if line.computed_amount is None:
                        current.append(_unavailable("Quantity or price unavailable for line arithmetic", path, evidence))
                    elif line.declared_amount is None:
                        if not is_absent(row.declared_amount):
                            current.append(_unavailable("Declared line amount is unnormalized", path, evidence))
                    else:
                        compared += 1
                        if line.within_tolerance is False:
                            current.append(_finding("LINE_ITEM_TOTAL_MISMATCH", "Declared line amount differs from quantity times price",
                                                    field=path, expected=line.computed_amount, actual=line.declared_amount, evidence=evidence))
                if not compared and not current:
                    skip = "No source rows declare line amounts; products remain available for total reconciliation"
            elif code == "SUBTOTAL_RECONCILIATION":
                if is_absent(invoice.subtotal):
                    skip = "Invoice does not declare a subtotal"
                elif facts.declared_subtotal is None or facts.computed_subtotal is None:
                    current.append(_unavailable("Subtotal inputs are unavailable", "subtotal"))
                else:
                    if facts.subtotal_within_tolerance is False:
                        current.append(_finding("LINE_ITEMS_SUBTOTAL_MISMATCH", "Declared subtotal differs from computed line products",
                                                field="subtotal", expected=facts.computed_subtotal, actual=facts.declared_subtotal,
                                                evidence=invoice.subtotal.evidence))
                    # Also reconcile the claimed line amounts, independently of
                    # their products, so compensating inconsistencies are visible.
                    if facts.declared_lines_subtotal_within_tolerance is False:
                        current.append(_finding("LINE_ITEMS_SUBTOTAL_MISMATCH", "Declared subtotal differs from sum of declared line amounts",
                                                field="subtotal", expected=facts.sum_declared_line_amounts, actual=facts.declared_subtotal,
                                                evidence=invoice.subtotal.evidence))
            elif facts.computed_total is None or facts.declared_total is None:
                current.append(_unavailable("Invoice total inputs are unavailable", "declared_total"))
            elif facts.within_tolerance is False:
                current.append(_finding("TOTAL_MISMATCH", f"Declared total differs from computed total by {facts.variance}",
                                        field="declared_total", expected=facts.computed_total, actual=facts.declared_total,
                                        evidence=invoice.declared_total.evidence))
        elif code == "CONSOLIDATE_ITEMS":
            check.tool_calls = calls["consolidate_items"]
            if not calls["consolidate_items"] or not state.consolidated_items:
                current.append(_unavailable("Consolidated items are unavailable"))
            for item in state.consolidated_items:
                if item.unavailable_fields:
                    current.append(_unavailable(f"Consolidation inputs unavailable: {', '.join(item.unavailable_fields)}", evidence=item.evidence))
        elif code == "INVENTORY_AVAILABILITY":
            check.tool_calls = calls["consolidate_items"] + calls["get_inventory"]
            inventory = state.inventory
            if inventory is None or inventory.error:
                current.append(_unavailable(inventory.error if inventory else "Inventory tool facts are unavailable"))
            elif not state.consolidated_items:
                current.append(_unavailable("Consolidated items are unavailable"))
            else:
                stock = {row.item: row.stock for row in inventory.records}
                for item in state.consolidated_items:
                    if item.item is None or item.quantity is None:
                        current.append(_unavailable("Item identity or complete quantity is unavailable", evidence=item.evidence))
                    elif item.item in inventory.unknown_items:
                        current.append(_finding("UNKNOWN_INVENTORY_ITEM", "Item is absent from trusted inventory",
                                                subject=item.item, actual=item.quantity, evidence=item.evidence))
                    elif item.item not in stock:
                        current.append(_unavailable(f"Inventory response omitted {item.item}", evidence=item.evidence))
                    elif item.quantity > stock[item.item]:
                        current.append(_finding("INSUFFICIENT_INVENTORY", "Requested quantity exceeds available stock",
                                                subject=item.item, expected=stock[item.item], actual=item.quantity, evidence=item.evidence))
        elif code == "DATE_CONSISTENCY":
            start, end = invoice.invoice_date.normalized, invoice.due_date.normalized
            if is_absent(invoice.due_date):
                skip = "Invoice does not declare a due date"
            elif not isinstance(start, date) or not isinstance(end, date):
                current.append(_unavailable("Date comparison inputs are unavailable", "due_date"))
            elif end < start:
                current.append(_finding("INVALID_DATE_ORDER", "Due date precedes invoice date", field="due_date",
                                        expected=f">= {start}", actual=end,
                                        evidence=invoice.invoice_date.evidence + invoice.due_date.evidence))
        else:
            current.append(_unavailable(f"No deterministic validator is registered for requested check {code}"))
        _finish(check, current, skip=skip)
        findings.extend(current)
    if state.operational_issues:
        check = ValidationCheck(code="VALIDATION_OPERATIONS")
        current = [_unavailable(message) for message in state.operational_issues]
        _finish(check, current)
        findings.extend(current)
        checks.append(check)
    return checks, findings


def evaluate_business_rules(invoice: Invoice | None, validation_findings=(), trusted_facts=None, settings: ValidationSettings | None = None):
    """USD > 10,000 requires scrutiny, not a payment decision or a rejection.

    Compare both claimed and computed totals so under-declaration cannot bypass
    configured policy. Other currencies need a future trusted FX/policy tool.
    """
    settings = settings or ValidationSettings()
    if settings.high_value_threshold is None:
        return [], []
    check = ValidationCheck(code="HIGH_VALUE_POLICY")
    findings = []
    if invoice is None or text_value(invoice.currency) != settings.policy_currency:
        findings.append(_unavailable("High-value policy requires an invoice in the configured policy currency", "currency"))
    else:
        declared = decimal_value(invoice.declared_total)
        computed = trusted_facts.computed_total if trusted_facts else None
        amounts = [value for value in (declared, computed) if value is not None]
        if not amounts:
            findings.append(_unavailable("High-value policy amount is unavailable", "declared_total"))
        elif max(amounts) > settings.high_value_threshold:
            findings.append(_finding("HIGH_VALUE_REVIEW_REQUIRED", "Configured high-value threshold requires additional scrutiny",
                                     severity="warning", field="declared_total", expected=f"<= {settings.high_value_threshold}",
                                     actual=max(amounts), evidence=invoice.declared_total.evidence))
    _finish(check, findings)
    return [check], findings
