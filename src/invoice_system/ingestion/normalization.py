"""Only allowlisted deterministic rules can produce trusted values."""
import re
from datetime import date, datetime
from decimal import Decimal

from .models import InvoiceCandidate, InvoiceProposal, Issue, LineItem, NormalizedField
from .extraction import valid_evidence

ALIASES = {"Widget A": "WidgetA", "Widget B": "WidgetB", "Gadget X": "GadgetX"}
MONEY = re.compile(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?")
DATE_FORMATS = (
    (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
    (r"\d{2}-[A-Za-z]{3}-\d{4}", "%d-%b-%Y"),
    (r"\d{2}/\d{2}/\d{4}", "%m/%d/%Y"),
    (r"[A-Za-z]{3} \d{1,2} \d{4}", "%b %d %Y"),
    (r"[A-Za-z]+ \d{1,2}, \d{4}", "%B %d, %Y"),
)
MONEY_FIELDS = {"subtotal", "tax", "shipping", "fees", "declared_total", "unit_price", "declared_amount"}
REQUIRED = {"invoice_number", "vendor", "invoice_date", "declared_total", "name", "quantity", "unit_price"}


def normalize_literal(literal: str, kind: str):
    if kind in MONEY_FIELDS:
        token = literal.strip().removeprefix("$")
        corrected = token.replace("O", "0")
        if not MONEY.fullmatch(corrected) or not any(c.isdigit() for c in token):
            raise ValueError("Unsupported money format")
        return Decimal(corrected.replace(",", "")), "ocr_money_O_to_0" if corrected != token else "decimal_money"
    if kind == "quantity":
        if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", literal):
            raise ValueError("Unsupported quantity")
        return Decimal(literal), "decimal_quantity"
    if kind in {"invoice_date", "due_date"}:
        corrected = re.sub(r"(?<=\d)O(?=\d|$)", "0", literal)
        for pattern, fmt in DATE_FORMATS:
            if re.fullmatch(pattern, corrected):
                return datetime.strptime(corrected, fmt).date(), "ocr_date_O_to_0" if corrected != literal else "controlled_date"
        raise ValueError("Unsupported date")
    if kind == "invoice_number":
        compact = literal.strip().upper().replace(" ", "-")
        if re.fullmatch(r"\d+", compact):
            return f"INV-{compact}", "invoice_identifier_format"
        if re.fullmatch(r"INV-?\d+", compact):
            normalized = f"INV-{re.search(r'\d+', compact).group()}"
            return normalized, "invoice_identifier_format" if normalized != literal else None
        return literal, None
    if kind == "currency" and literal.strip() == "$":
        return "USD", "currency_symbol"
    if kind == "name" and literal in ALIASES:
        return ALIASES[literal], "product_alias"
    if kind == "name" and re.fullmatch(r"(?:WidgetA|WidgetB|GadgetX) \([^)]+\)", literal):
        return literal.split(" ", 1)[0], "product_description_suffix"
    return literal, None


def normalize(proposal: InvoiceProposal, document, *, visual=False):
    issues = []

    def field(observed, kind, path):
        result = NormalizedField(observed=observed)
        code = None
        if observed.alternatives:
            code = "AMBIGUOUS_FIELD"
        elif observed.literal is None:
            if kind in REQUIRED:
                code = "MISSING_FIELD"
        elif not valid_evidence(observed.literal, observed.evidence, document, visual=visual):
            code = "UNSUPPORTED_EVIDENCE"
        else:
            try:
                result.value, result.applied_rule = normalize_literal(observed.literal, kind)
                result.value_type = "decimal" if isinstance(result.value, Decimal) else "date" if isinstance(result.value, date) else "text"
                if observed.transformation and observed.transformation.normalized != str(result.value):
                    issues.append(Issue(code="REJECTED_TRANSFORMATION", field=path,
                        message="Proposed normalization is outside deterministic rules", evidence=observed.evidence))
            except ValueError:
                code = "UNPARSEABLE_FIELD"
        if code:
            issues.append(Issue(code=code, field=path, message="Field remains unresolved", evidence=observed.evidence))
        return result

    fields = {key: field(getattr(proposal, key), key, key) for key in InvoiceCandidate.model_fields if key != "line_items"}
    items = []
    for i, row in enumerate(proposal.line_items):
        items.append(LineItem(**{key: field(getattr(row, key), key, f"line_items[{i}].{key}") for key in LineItem.model_fields}))
    if not items:
        issues.append(Issue(code="MISSING_LINE_ITEMS", field="line_items", message="No line items were interpreted"))
    return InvoiceCandidate(**fields, line_items=items), issues
