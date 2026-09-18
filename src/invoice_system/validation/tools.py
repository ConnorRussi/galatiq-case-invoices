"""Trusted transformations and read-only data access; no agent-generated SQL."""
from __future__ import annotations

from contextlib import closing
from decimal import Context, Decimal, DivisionByZero, Inexact, InvalidOperation, Overflow, localcontext
from pathlib import Path
import sqlite3

from ..ingestion.models import Invoice as InvoiceCandidate, LineItem, ExtractedField as NormalizedField
from .models import ArithmeticResult, ConsolidatedItem, InventoryRecord, InventoryResult, LineArithmetic


def exact_context():
    # No ambient rounding/trap settings and no silent precision loss. Inputs
    # beyond this generous financial precision fail as unavailable tool facts.
    return localcontext(Context(prec=64, traps=[InvalidOperation, DivisionByZero, Overflow, Inexact]))


def decimal_value(field: NormalizedField) -> Decimal | None:
    value = field.normalized
    return value if isinstance(value, Decimal) and value.is_finite() else None


def text_value(field: NormalizedField) -> str | None:
    value = field.normalized
    return value if isinstance(value, str) and value.strip() else None


def is_absent(field: NormalizedField) -> bool:
    return field.normalized is None and field.original is None


def consolidate_line_items(items: list[LineItem]) -> list[ConsolidatedItem]:
    """Exact normalized names are identities; source row indices are zero-based.

    Missing names remain separate groups. Incomplete or invalid quantities make
    the entire group's quantity unavailable, never a misleading partial sum.
    """
    groups: dict[str | int, ConsolidatedItem] = {}
    with exact_context():
        for index, row in enumerate(items):
            name, quantity = text_value(row.name), decimal_value(row.quantity)
            key = name if name is not None else index
            if key not in groups:
                groups[key] = ConsolidatedItem(item=name, quantity=Decimal(0), source_rows=[])
            group = groups[key]
            group.source_rows.append(index)
            group.evidence.extend(row.name.evidence + row.quantity.evidence)
            if name is None:
                group.unavailable_fields.append(f"line_items[{index}].name")
            if quantity is None or quantity <= 0:
                group.unavailable_fields.append(f"line_items[{index}].quantity")
                group.quantity = None
            elif group.quantity is not None:
                group.quantity += quantity
    return list(groups.values())


def recalculate_invoice(invoice: InvoiceCandidate, tolerance: Decimal = Decimal("0.01")) -> ArithmeticResult:
    """Compare unrounded Decimal products with an explicit absolute tolerance.

    Only present tax/shipping/fees are added. Absent components remain None and
    are listed explicitly; present but unnormalized components block the total.
    The source schema has no tax rate or invoice-level discount.
    """
    if not isinstance(tolerance, Decimal) or not tolerance.is_finite() or tolerance < 0:
        raise ValueError("Money tolerance must be a finite nonnegative Decimal")
    result = ArithmeticResult(tolerance=tolerance)
    with exact_context():
        for index, row in enumerate(invoice.line_items):
            quantity, price, amount = map(decimal_value, (row.quantity, row.unit_price, row.declared_amount))
            computed = quantity * price if quantity is not None and price is not None else None
            variance = amount - computed if amount is not None and computed is not None else None
            result.lines.append(LineArithmetic(
                source_row=index, quantity=quantity, unit_price=price, declared_amount=amount,
                computed_amount=computed, variance=variance,
                within_tolerance=abs(variance) <= tolerance if variance is not None else None,
            ))
            for name in ("quantity", "unit_price"):
                if decimal_value(getattr(row, name)) is None:
                    result.unavailable_fields.append(f"line_items[{index}].{name}")
        if result.lines and all(line.computed_amount is not None for line in result.lines):
            result.computed_subtotal = sum((line.computed_amount for line in result.lines), Decimal(0))
        if result.lines and all(line.declared_amount is not None for line in result.lines):
            result.sum_declared_line_amounts = sum((line.declared_amount for line in result.lines), Decimal(0))
        result.declared_subtotal = decimal_value(invoice.subtotal)
        result.declared_total = decimal_value(invoice.declared_total)
        if result.declared_subtotal is not None and result.computed_subtotal is not None:
            result.subtotal_variance = result.declared_subtotal - result.computed_subtotal
            result.subtotal_within_tolerance = abs(result.subtotal_variance) <= tolerance
        if result.declared_subtotal is not None and result.sum_declared_line_amounts is not None:
            result.declared_lines_subtotal_variance = result.declared_subtotal - result.sum_declared_line_amounts
            result.declared_lines_subtotal_within_tolerance = abs(result.declared_lines_subtotal_variance) <= tolerance
        additions = []
        for name in ("tax", "shipping", "fees"):
            field = getattr(invoice, name)
            value = decimal_value(field)
            setattr(result, name, value)
            if is_absent(field):
                result.absent_components.append(name)
            elif value is None:
                result.unavailable_fields.append(name)
            else:
                additions.append(value)
        if result.computed_subtotal is not None and not result.unavailable_fields:
            result.computed_total = result.computed_subtotal + sum(additions, Decimal(0))
        if result.computed_total is not None and result.declared_total is not None:
            result.variance = result.declared_total - result.computed_total
            result.within_tolerance = abs(result.variance) <= tolerance
    return result


class SQLiteInventory:
    """Fixed inventory(item TEXT PRIMARY KEY, stock INTEGER) repository schema."""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()

    def lookup(self, item_names: list[str]) -> InventoryResult:
        names = list(dict.fromkeys(item_names))
        result = InventoryResult(requested_items=names, source=str(self.path))
        if not names:
            return result
        try:
            # mode=ro prevents accidental creation and writes; Path.as_uri quotes
            # spaces, #, and ? safely. One transaction gives a consistent snapshot.
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=2)) as conn:
                conn.execute("PRAGMA query_only = ON")
                conn.execute("BEGIN")
                for start in range(0, len(names), 500):
                    batch = names[start:start + 500]
                    placeholders = ",".join("?" for _ in batch)
                    rows = conn.execute(
                        f"SELECT item, stock FROM inventory WHERE item IN ({placeholders})", batch,
                    ).fetchall()
                    for item, stock in rows:
                        if not isinstance(stock, int) or stock < 0:
                            raise ValueError("Inventory stock must be a nonnegative SQLite integer")
                        result.records.append(InventoryRecord(item=item, stock=Decimal(stock)))
            known = {row.item for row in result.records}
            result.unknown_items = [name for name in names if name not in known]
        except (sqlite3.Error, ValueError) as exc:
            result.records = []
            result.unknown_items = []
            result.error = f"Inventory data unavailable: {type(exc).__name__}: {exc}"
        return result


def get_inventory(item_names: list[str], db_path: str | Path = "inventory.sqlite") -> InventoryResult:
    """Safe convenience contract used by callers and future tool wrappers."""
    return SQLiteInventory(db_path).lookup(item_names)
