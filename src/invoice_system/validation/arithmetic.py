"""Decimal-only arithmetic evidence used by Phase 2 reconciliation."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import re
from typing import Any

from invoice_system.ingestion.models import NormalizedInvoice


def decimal_sum(values: list[Decimal]) -> Decimal:
    """Add monetary values without converting through binary floats."""

    return sum(values, Decimal("0"))


def decimal_subtract(left: Decimal, right: Decimal) -> Decimal:
    return left - right


def decimal_multiply(left: Decimal, right: Decimal) -> Decimal:
    return left * right


def normalize_product_name(value: str | None) -> str:
    """Create a stable identity for consolidation, without changing source names."""

    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def build_arithmetic_evidence(invoice: NormalizedInvoice) -> dict[str, Any]:
    """Return deterministic calculations for an LLM specialist or critic.

    This is evidence, not a replacement for the reconciliation specialist's
    structured conclusion. Missing values remain missing; the tool never
    invents invoice claims.
    """

    lines: list[dict[str, Any]] = []
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"product_name": "", "source_lines": [], "quantities": [], "prices": [], "derived_total": Decimal("0")}
    )
    for index, item in enumerate(invoice.items, start=1):
        calculated = None
        if item.quantity is not None and item.unit_price is not None:
            calculated = decimal_multiply(item.quantity, item.unit_price)
        line = {
            "line": index,
            "field": f"items[{index - 1}]",
            "product_name": item.item_name,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "declared_line_amount": item.line_amount,
            "calculated_line_amount": calculated,
        }
        lines.append(line)

        identity = normalize_product_name(item.item_name)
        if not identity:
            continue
        group = groups[identity]
        group["product_name"] = group["product_name"] or item.item_name or identity
        group["source_lines"].append(index)
        if item.quantity is not None:
            group["quantities"].append(item.quantity)
        if item.unit_price is not None:
            group["prices"].append(item.unit_price)
        if calculated is not None:
            group["derived_total"] += calculated

    consolidated = []
    for identity, group in groups.items():
        prices = group["prices"]
        consolidated.append(
            {
                "product_name": group["product_name"],
                "normalized_product": identity,
                "combined_quantity": decimal_sum(group["quantities"]),
                "source_lines": group["source_lines"],
                "unit_prices": prices,
                "derived_line_total": group["derived_total"] if group["quantities"] and prices else None,
                "conflicting_prices": len(set(prices)) > 1,
            }
        )

    calculated_subtotal = None
    if lines and all(line["calculated_line_amount"] is not None for line in lines):
        calculated_subtotal = decimal_sum([line["calculated_line_amount"] for line in lines])

    calculated_total = None
    subtotal_basis = calculated_subtotal if calculated_subtotal is not None else invoice.subtotal
    if subtotal_basis is not None and invoice.tax_amount is not None:
        calculated_total = subtotal_basis + invoice.tax_amount
        if invoice.shipping is not None:
            calculated_total += invoice.shipping
        if invoice.discount is not None:
            calculated_total -= invoice.discount

    return {
        "lines": lines,
        "consolidated_items": consolidated,
        "calculated_subtotal": calculated_subtotal,
        "declared_subtotal": invoice.subtotal,
        "calculated_total": calculated_total,
        "declared_total": invoice.invoice_total,
        "tax_amount": invoice.tax_amount,
        "shipping": invoice.shipping,
        "discount": invoice.discount,
    }
