"""Bounded observe/act validation graph, downstream of the ingestion handoff."""
from pathlib import Path
from typing import Callable, Protocol

from langgraph.graph import END, START, StateGraph

from ..ingestion.models import IngestionResult, Invoice
from .agent import OfflineValidationAgent, ValidationAgent
from .models import (
    AgentDecision, AgentView, CheckStatus, IngestionRecheckRequest, InventoryResult,
    ToolCall, ValidationCheck, ValidationFinding, ValidationReport, ValidationSettings,
    ValidationState, derive_outcome,
)
from .policy import baseline_checks, recheck_is_justified, verify_targeted_result
from .rules import evaluate_business_rules, evaluate_technical_rules
from .tools import SQLiteInventory, consolidate_line_items, recalculate_invoice


class InventoryTool(Protocol):
    def lookup(self, item_names: list[str]) -> InventoryResult: ...


Reingest = Callable[[IngestionResult, IngestionRecheckRequest], IngestionResult]


def build_validation_workflow(
    *, settings: ValidationSettings | None = None, inventory: InventoryTool | None = None,
    inventory_path: str | Path = "inventory.sqlite", agent: ValidationAgent | None = None,
    reingest: Reingest | None = None,
):
    settings = (settings or ValidationSettings()).model_copy(deep=True)
    inventory = inventory if inventory is not None else SQLiteInventory(inventory_path)
    agent = agent if agent is not None else OfflineValidationAgent()

    def decide(state, phase):
        state.agent_turns += 1
        view = AgentView(
            phase=phase, handoff=state.handoff, checks=state.validation_checks,
            findings=state.validation_findings, consolidated_items=state.consolidated_items,
            arithmetic=state.arithmetic, inventory=state.inventory, tool_calls=state.tool_calls,
            remaining_tool_calls=max(0, settings.max_tool_calls - state.validation_tool_calls),
            reingestion_attempts=state.reingestion_attempts,
        )
        try:
            # Deep copies isolate nested lists/fields, not merely top-level models.
            response = agent.decide(view.model_copy(deep=True))
            decision = AgentDecision.model_validate(response.model_dump() if isinstance(response, AgentDecision) else response)
            state.additional_checks = list(dict.fromkeys(state.additional_checks + decision.additional_checks))
            return decision
        except Exception as exc:
            state.operational_issues.append(f"Validation agent failed: {type(exc).__name__}: {exc}")
            return AgentDecision()

    def inspect(state):
        state.validation_checks = baseline_checks(state.handoff.invoice, settings)
        decision = decide(state, "handoff")
        if decision.recheck:
            if recheck_is_justified(decision.recheck, state.handoff):
                state.recheck_request = decision.recheck.model_copy(deep=True)
            else:
                state.operational_issues.append("Agent requested re-ingestion without qualifying extraction evidence")
        state.next_tool = decision.tool

    def recheck(state):
        if state.recheck_request is None:
            return
        if reingest is None:
            state.operational_issues.append("Targeted extraction recheck requested but no re-ingestion adapter is configured")
            return
        # This node has no incoming back edge. The counter is also a hard guard.
        if state.reingestion_attempts >= 1:
            return
        state.reingestion_attempts += 1
        try:
            response = reingest(state.handoff.model_copy(deep=True), state.recheck_request.model_copy(deep=True))
            result = IngestionResult.model_validate(response.model_dump())
            state.recheck_result = result.model_copy(deep=True)
            verify_targeted_result(state.handoff, result, state.recheck_request)
            state.handoff = result.model_copy(deep=True)
        except Exception as exc:
            state.operational_issues.append(f"Targeted re-ingestion failed: {type(exc).__name__}: {exc}")

    def observe(state):
        state.validation_checks, state.validation_findings = evaluate_technical_rules(state, settings)
        if state.handoff.invoice is None:
            state.next_node = "finalize"
            return
        called = {call.tool for call in state.tool_calls}
        mandatory = [tool for tool in ("consolidate_items", "recalculate_invoice", "get_inventory") if tool not in called]
        requested = state.next_tool
        state.next_tool = None
        if requested is None and state.agent_turns < settings.max_agent_turns:
            decision = decide(state, "investigate")
            if decision.recheck:
                state.operational_issues.append("Re-ingestion is only allowed during the initial handoff inspection")
            requested = decision.tool
        elif requested is None and not mandatory:
            state.operational_issues.append("Validation agent turn limit reached before final inspection")
        # A premature agent finish can never omit mandatory deterministic work.
        selected = requested or (mandatory[0] if mandatory else None)
        if selected == "get_inventory" and "consolidate_items" not in called:
            selected = "consolidate_items"
        if selected is None:
            state.next_node = "finalize"
        elif state.validation_tool_calls >= settings.max_tool_calls:
            state.tool_budget_exhausted = True
            state.next_node = "finalize"
        else:
            state.next_tool = selected
            state.next_node = "tool"

    def execute_tool(state):
        tool = state.next_tool
        state.next_tool = None
        state.validation_tool_calls += 1
        call = ToolCall(id=f"validation-tool-{state.validation_tool_calls}", tool=tool)
        try:
            invoice = state.handoff.invoice.model_copy(deep=True)
            if tool == "consolidate_items":
                state.consolidated_items = consolidate_line_items(invoice.line_items)
            elif tool == "recalculate_invoice":
                state.arithmetic = recalculate_invoice(invoice, settings.money_tolerance)
            else:
                names = [item.item for item in state.consolidated_items if item.item is not None]
                response = inventory.lookup(list(names))
                result = InventoryResult.model_validate(response.model_dump())
                # Incomplete responses remain unresolved per item. Conflicting or
                # unsolicited records invalidate the response as trusted facts.
                records = [r.item for r in result.records]
                if (len(records) != len(set(records)) or set(records) & set(result.unknown_items)
                        or not (set(records) | set(result.unknown_items)) <= set(names)):
                    raise ValueError("Inventory response contains conflicting or unsolicited records")
                result.requested_items = list(names)
                state.inventory = result.model_copy(deep=True)
                call.error = result.error
        except Exception as exc:
            call.error = f"{tool} failed: {type(exc).__name__}: {exc}"
            if tool == "get_inventory":
                state.inventory = InventoryResult(error=call.error)
            elif tool == "recalculate_invoice":
                state.arithmetic = None
            else:
                state.consolidated_items = []
        state.tool_calls.append(call)

    def finalize(state):
        checks, findings = evaluate_technical_rules(state, settings)
        business_checks, business_findings = evaluate_business_rules(
            state.handoff.invoice, findings, state.arithmetic, settings,
        )
        for check in business_checks:
            check.tool_calls = [call.id for call in state.tool_calls if call.tool == "recalculate_invoice"]
        checks.extend(business_checks)
        findings.extend(business_findings)
        if state.tool_budget_exhausted:
            reason = "Maximum validation tool-call count reached with requested work remaining"
            checks.append(ValidationCheck(code="TOOL_CALL_BUDGET", status=CheckStatus.UNRESOLVED,
                                          unresolved_reason=reason, finding_codes=["VALIDATION_DATA_UNAVAILABLE"]))
            findings.append(ValidationFinding(code="VALIDATION_DATA_UNAVAILABLE", severity="unresolved", message=reason))
        complete, disposition = derive_outcome(checks, findings, state.tool_budget_exhausted)
        state.validation_checks = checks
        state.validation_findings = findings
        state.validation_complete = complete
        state.report = ValidationReport(
            checks=checks, findings=findings,
            unresolved_questions=list(dict.fromkeys(c.unresolved_reason for c in checks if c.unresolved_reason)),
            validation_complete=complete, disposition=disposition,
            original_invoice=state.original.invoice, invoice=state.handoff.invoice,
            consolidated_items=state.consolidated_items, arithmetic=state.arithmetic, inventory=state.inventory,
            tool_calls=state.tool_calls, recheck_request=state.recheck_request, recheck_result=state.recheck_result,
            reingestion_attempts=state.reingestion_attempts, tool_budget_exhausted=state.tool_budget_exhausted,
        ).model_copy(deep=True)

    def node(handler):
        def run(state):
            handler(state)
            return {name: getattr(state, name) for name in type(state).model_fields}
        return run

    builder = StateGraph(ValidationState)
    for name, handler in (("inspect", inspect), ("recheck", recheck), ("observe", observe),
                          ("tool", execute_tool), ("finalize", finalize)):
        builder.add_node(name, node(handler))
    builder.add_edge(START, "inspect")
    builder.add_edge("inspect", "recheck")
    builder.add_edge("recheck", "observe")
    builder.add_conditional_edges("observe", lambda state: state.next_node, ["tool", "finalize"])
    builder.add_edge("tool", "observe")
    builder.add_edge("finalize", END)
    return builder.compile()


def validate_invoice(
    handoff: IngestionResult | Invoice, *, settings: ValidationSettings | None = None,
    inventory: InventoryTool | None = None, inventory_path: str | Path = "inventory.sqlite",
    agent: ValidationAgent | None = None, reingest: Reingest | None = None,
) -> ValidationReport:
    """Validate an ingestion handoff or an already normalized candidate offline.

    The original handoff and all extension inputs are deep-copied. No ingestion
    workflow or source field is mutated. Re-ingestion requires an explicit adapter
    because the current ingestion API has no targeted field-recheck operation.
    """
    settings = settings or ValidationSettings()
    if isinstance(handoff, Invoice):
        handoff = IngestionResult(run_id="validation-direct", status="ready_for_validation", invoice=handoff)
    state = ValidationState(original=handoff.model_copy(deep=True), handoff=handoff.model_copy(deep=True))
    graph = build_validation_workflow(settings=settings, inventory=inventory, inventory_path=inventory_path,
                                      agent=agent, reingest=reingest)
    final = graph.invoke(state, {"recursion_limit": 2 * settings.max_tool_calls + 10})
    return final["report"]
