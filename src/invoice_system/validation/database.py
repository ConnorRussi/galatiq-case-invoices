"""Inventory/database specialist with bounded, agent-directed lookup rounds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable, Sequence

from invoice_system.agent_runtime import invoke_structured
from invoice_system.ingestion.models import IngestionResult, NormalizedLineItem
from pydantic import BaseModel, Field

from .config import MAX_PRODUCT_LOOKUP_ROUNDS
from .database_tool import DEFAULT_DATABASE_PATH, InventoryLookup, lookup_inventory_bulk
from .models import (
    DatabaseResult,
    DatabaseStatus,
    DatabaseValidationResult,
    ValidationIssue,
)


DATABASE_SCOPE_CONTRACT = """
DATABASE LOOKUP SCOPE CONTRACT

The inventory database stores product identifiers without spaces. Components
are joined together and each component begins with a capital letter, forming a
PascalCase-style identifier. This is context for deliberate lookup decisions,
not a command to rewrite every input.

The database specialist owns:
- exact inventory lookup requests;
- reasonable, meaning-preserving retry candidates when the first lookup is
  unresolved;
- requested quantity versus available stock; and
- an auditable record of every attempted name and the authoritative matched
  database value.

Do not treat a materially different product as a formatting variation. A
failed lookup is not permission to substitute a different known product.
""".strip()


def database_scope_prompt() -> str:
    return DATABASE_SCOPE_CONTRACT


def _database_prompt() -> str:
    return f"""You are the inventory database validation specialist.

Use the exact bulk lookup tool supplied by the application. The tool trims
outer whitespace only; it does not normalize product identity.

{database_scope_prompt()}

Execution rules:
- Prefer one bulk lookup round containing all unresolved products.
- Retry only unresolved products, and use at most the configured number of
  lookup rounds (maximum {MAX_PRODUCT_LOOKUP_ROUNDS}).
- Choose retry candidates as an agent decision based on apparent identity and
  the database naming convention. Do not blindly strip punctuation, alter
  spelling, or map one materially different product to another.
- Preserve requested_name, every attempted_names entry, matched_item,
  requested_quantity, available_stock, product_found, and
  inventory_sufficient for every requested product.
- The matched database value is authoritative after a supported match.
- Return the stage exactly as "database" and use stable issue codes such as
  PRODUCT_NOT_FOUND and INSUFFICIENT_INVENTORY.
"""


class DatabaseRetryProposal(BaseModel):
    requested_name: str
    candidate_names: list[str] = Field(default_factory=list)


class DatabaseRetryPlan(BaseModel):
    proposals: list[DatabaseRetryProposal] = Field(default_factory=list)


RetryProposer = Callable[[list[DatabaseResult]], list[DatabaseRetryProposal]]


def _default_retry_proposer(
    unresolved: list[DatabaseResult],
    *,
    revision_feedback: str | None = None,
) -> list[DatabaseRetryProposal]:
    content = json.dumps(
        {
            "unresolved_products": [item.model_dump(mode="json") for item in unresolved],
            "revision_feedback": revision_feedback,
            "retry_plan_schema": DatabaseRetryPlan.model_json_schema(),
        },
        ensure_ascii=False,
    )
    plan = invoke_structured(
        system_prompt=_database_prompt(),
        content=content,
        output_model=DatabaseRetryPlan,
    )
    return plan.proposals


def _items_from_ingestion(ingestion: IngestionResult) -> list[NormalizedLineItem]:
    if ingestion.normalization is None:
        raise ValueError("Database validation requires an ingestion normalization")
    return [item for item in ingestion.normalization.invoice.items if item.item_name]


def _initial_results(items: Sequence[NormalizedLineItem]) -> list[DatabaseResult]:
    return [
        DatabaseResult(
            requested_name=item.item_name or "",
            attempted_names=[item.item_name or ""],
            requested_quantity=item.quantity,
            product_found=False,
            inventory_sufficient=None,
        )
        for item in items
    ]


def _apply_lookups(
    results: list[DatabaseResult],
    lookup_by_request: Iterable[InventoryLookup],
) -> None:
    by_name = {lookup.requested_name: lookup for lookup in lookup_by_request}
    for index, result in enumerate(results):
        lookup = by_name.get(result.attempted_names[-1].strip())
        if lookup is None:
            continue
        if not lookup.product_found:
            continue
        sufficient = (
            result.requested_quantity is None
            or lookup.available_stock is None
            or result.requested_quantity <= lookup.available_stock
        )
        results[index] = result.model_copy(
            update={
                "matched_item": lookup.matched_item,
                "available_stock": lookup.available_stock,
                "product_found": True,
                "inventory_sufficient": sufficient,
            }
        )


def _unresolved(results: Sequence[DatabaseResult]) -> list[DatabaseResult]:
    return [result for result in results if not result.product_found]


def _proposals_for(
    proposals: Sequence[DatabaseRetryProposal],
    unresolved: Sequence[DatabaseResult],
) -> list[tuple[DatabaseResult, str]]:
    by_name = {proposal.requested_name: proposal for proposal in proposals}
    selected: list[tuple[DatabaseResult, str]] = []
    for result in unresolved:
        proposal = by_name.get(result.requested_name)
        if proposal is None:
            continue
        for candidate in proposal.candidate_names:
            candidate = candidate.strip()
            if candidate and candidate not in result.attempted_names:
                selected.append((result, candidate))
                break
    return selected


def resolve_inventory(
    ingestion: IngestionResult,
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
    max_rounds: int = MAX_PRODUCT_LOOKUP_ROUNDS,
    retry_proposer: RetryProposer | None = None,
    revision_feedback: str | None = None,
) -> DatabaseValidationResult:
    """Resolve invoice products using bulk rounds and preserve lookup history."""

    if max_rounds < 1:
        raise ValueError("max_rounds must be at least 1")
    results = _initial_results(_items_from_ingestion(ingestion))
    proposer = retry_proposer or (
        lambda unresolved: _default_retry_proposer(
            unresolved,
            revision_feedback=revision_feedback,
        )
    )

    for round_number in range(max_rounds):
        pending_names = [result.attempted_names[-1] for result in _unresolved(results)]
        if not pending_names:
            break
        _apply_lookups(results, lookup_inventory_bulk(pending_names, db_path=db_path))
        unresolved = _unresolved(results)
        if not unresolved or round_number + 1 >= max_rounds:
            break
        selections = _proposals_for(proposer(unresolved), unresolved)
        if not selections:
            break
        for result, candidate in selections:
            index = next(index for index, current in enumerate(results) if current is result)
            results[index] = result.model_copy(update={"attempted_names": [*result.attempted_names, candidate]})

    issues: list[ValidationIssue] = []
    for result in results:
        if not result.product_found:
            issues.append(
                ValidationIssue(
                    code="PRODUCT_NOT_FOUND",
                    field="requested_name",
                    message=f"No inventory record was found for {result.requested_name!r}.",
                    evidence=result.attempted_names,
                )
            )
        elif result.inventory_sufficient is False:
            issues.append(
                ValidationIssue(
                    code="INSUFFICIENT_INVENTORY",
                    field="requested_quantity",
                    message="Requested quantity exceeds available inventory.",
                    evidence=[result.matched_item or result.requested_name],
                )
            )
    return DatabaseValidationResult(
        status=DatabaseStatus.DENY if issues else DatabaseStatus.PASS,
        issues=issues,
        summary="Inventory lookup completed." if not issues else "Inventory lookup found blocking issue(s).",
        results=results,
    )


validate_inventory = resolve_inventory
