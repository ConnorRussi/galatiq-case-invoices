"""Structured Reconciliation scoring helpers for the Validation Agent eval.

The end-to-end evaluator lives in :mod:`invoice_system.validation.evaluation`.
This module intentionally contains only the reusable Phase 2 comparison
contract so callers and existing tests do not create a second stage evaluator.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .arithmetic import normalize_product_name
from .models import (
    ReconciliationCheckOutcome,
    ReconciliationCheckType,
    ReconciliationResult,
)


@dataclass
class ReconciliationMetrics:
    status_match: bool = False
    expected_issue_code_coverage: bool = False
    expected_issue_field_coverage: bool = False
    consolidation_accuracy: bool = True
    arithmetic_accuracy: bool = True
    unexpected_blocking_issue_count: int = 0
    critic_completion: bool = False
    critic_revision_count: int = 0
    overall_reconciliation_match: bool = False


def score_reconciliation_result(
    expected: dict[str, Any],
    result: ReconciliationResult,
    *,
    critic_revision_count: int = 0,
    critic_completion: bool = False,
) -> ReconciliationMetrics:
    """Compare stable Phase 2 facts, never natural-language prose."""

    reconciliation = expected.get("reconciliation", expected)
    expected_status = str(reconciliation.get("expected_status", "PASS")).upper()
    expected_issues = _expected_issues(reconciliation)
    expected_codes = [_normalise_code(issue["code"]) for issue in expected_issues if issue["code"] != "__field_only__"]
    expected_fields = [_normalise_field(issue.get("field")) for issue in expected_issues if issue.get("field")]
    expected_pairs = {
        (_normalise_code(issue["code"]), _normalise_field(issue.get("field")))
        for issue in expected_issues
        if issue["code"] != "__field_only__"
    }
    expected_codes_with_wildcard_field = {
        _normalise_code(issue["code"])
        for issue in expected_issues
        if issue["code"] != "__field_only__" and not issue.get("field")
    }
    expected_field_only = {
        _normalise_field(issue.get("field"))
        for issue in expected_issues
        if issue["code"] == "__field_only__"
    }
    status_match = result.status.value == expected_status
    code_coverage = all(
        any(_normalise_code(issue.code) == code for issue in result.issues)
        for code in expected_codes
    )
    field_coverage = all(
        any(_normalise_field(issue.field) == field for issue in result.issues)
        for field in expected_fields
    )
    unexpected = sum(
        issue.severity.value == "error"
        and not _issue_is_expected(
            issue.code,
            issue.field,
            expected_pairs,
            expected_codes_with_wildcard_field,
            expected_field_only,
        )
        and (
            expected_status == "PASS"
            or not _issue_is_supported_by_check(issue.code, issue.field, result)
        )
        for issue in result.issues
    )
    consolidation = _compare_consolidation(
        reconciliation.get("expected_consolidated_items", []),
        result,
    )
    arithmetic = _compare_arithmetic(reconciliation.get("expected_calculations", []), result)
    overall = status_match and code_coverage and field_coverage and unexpected == 0 and consolidation and arithmetic
    return ReconciliationMetrics(
        status_match=status_match,
        expected_issue_code_coverage=code_coverage,
        expected_issue_field_coverage=field_coverage,
        consolidation_accuracy=consolidation,
        arithmetic_accuracy=arithmetic,
        unexpected_blocking_issue_count=unexpected,
        critic_completion=critic_completion,
        critic_revision_count=critic_revision_count,
        overall_reconciliation_match=overall,
    )


def _expected_issues(reconciliation: dict[str, Any]) -> list[dict[str, Any]]:
    if "expected_issues" in reconciliation:
        return list(reconciliation["expected_issues"])
    return [
        {"code": code}
        for code in reconciliation.get("expected_issue_codes", [])
    ] + [
        {"code": "__field_only__", "field": field}
        for field in reconciliation.get("expected_issue_fields", [])
    ]


def _compare_consolidation(
    expected: list[dict[str, Any]],
    result: ReconciliationResult,
) -> bool:
    if not expected:
        return True
    actual = {
        _normalise_product(item.normalized_product or item.product_name): item
        for item in result.consolidated_items
    }
    expected_products: set[str] = set()
    for item in expected:
        product = _normalise_product(item.get("normalized_product") or item.get("product_name"))
        expected_products.add(product)
        found = actual.get(product)
        if found is None:
            return False
        quantity = item.get("expected_quantity", item.get("combined_quantity"))
        if quantity is not None and found.combined_quantity != Decimal(str(quantity)):
            return False
        if "expected_source_lines" in item and found.source_lines != item["expected_source_lines"]:
            return False
        if "expected_unit_price" in item and found.unit_price != Decimal(str(item["expected_unit_price"])):
            return False
        if "expected_unit_prices" in item and found.unit_prices != [
            Decimal(str(value)) for value in item["expected_unit_prices"]
        ]:
            return False
        if "expected_derived_line_total" in item and found.derived_line_total != Decimal(str(item["expected_derived_line_total"])):
            return False
    return set(actual) == expected_products


def _compare_arithmetic(expected: list[dict[str, Any]], result: ReconciliationResult) -> bool:
    if not expected:
        return True
    for item in expected:
        matches = [
            calculation
            for calculation in result.calculations
            if calculation.check_type.value
            == str(item.get("check_type", item.get("code"))).upper()
        ]
        if item.get("field") is not None:
            matches = [
                calculation
                for calculation in matches
                if _normalise_field(calculation.field) == _normalise_field(item["field"])
            ]
        if not matches:
            return False
        match = matches[0]
        if "outcome" in item and match.outcome.value != str(item["outcome"]).upper():
            return False
        for key in ("calculated", "declared"):
            if key in item and getattr(match, key) != Decimal(str(item[key])):
                return False
    return True


_MISMATCH_CHECK_TYPES = {
    "line_total_mismatch": ReconciliationCheckType.LINE_TOTAL,
    "subtotal_mismatch": ReconciliationCheckType.SUBTOTAL,
    "total_mismatch": ReconciliationCheckType.TOTAL,
}


def _issue_is_supported_by_check(
    code: str,
    field: str | None,
    result: ReconciliationResult,
) -> bool:
    """Allow additional real arithmetic findings, but not invented blockers."""

    check_type = _MISMATCH_CHECK_TYPES.get(_normalise_code(code))
    if check_type is None:
        return False
    return any(
        check.check_type == check_type
        and check.outcome == ReconciliationCheckOutcome.MISMATCH
        and (field is None or _normalise_field(check.field) == _normalise_field(field))
        for check in result.calculations
    )


def _issue_is_expected(
    code: str,
    field: str | None,
    expected_pairs: set[tuple[str, str | None]],
    expected_codes_with_wildcard_field: set[str],
    expected_field_only: set[str | None],
) -> bool:
    normalized_code = _normalise_code(code)
    normalized_field = _normalise_field(field)
    return (
        (normalized_code, normalized_field) in expected_pairs
        or normalized_code in expected_codes_with_wildcard_field
        or normalized_field in expected_field_only
    )


def _normalise_product(value: str | None) -> str:
    return normalize_product_name(value)


def _normalise_code(value: str) -> str:
    return value.strip().casefold()


def _normalise_field(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().removeprefix("invoice.").replace("line_items[", "items[")


def _contains_all(expected: list[str | None], actual: list[str | None]) -> bool:
    expected_counts = Counter(expected)
    actual_counts = Counter(actual)
    return all(actual_counts[key] >= count for key, count in expected_counts.items())
