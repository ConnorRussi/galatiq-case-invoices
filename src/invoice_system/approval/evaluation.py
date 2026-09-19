"""Standalone evaluation for the final approval graph.

Approval cases intentionally begin with trusted VALID/PASS upstream results. The
suite measures the approval boundary: business-rule bucket selection, VP
escalation routing, and the final approval bucket.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..ingestion.run_logging import RunContext, make_evaluation_id, now_iso, write_artifact
from .models import ApprovalRequest, ApprovalResult
from .runner import run_approval


@dataclass
class EvalSection:
    name: str
    passed: bool = True
    messages: list[str] = field(default_factory=list)


@dataclass
class ApprovalEval:
    case_id: str
    sections: list[EvalSection]
    result: ApprovalResult | None
    artifact_dir: Path
    error: str | None = None

    @property
    def passed(self) -> bool:
        return all(section.passed for section in self.sections)


def run_approval_evaluation(root: Path) -> bool:
    """Run all approval cases and write one auditable evaluation directory."""

    case_dir = root / "evals" / "approval" / "cases"
    case_files = sorted(case_dir.glob("*.json"))
    if not case_files:
        print("No approval case files found.")
        return False

    evaluation_id = make_evaluation_id()
    evaluation_dir = root / "logs" / "evals" / evaluation_id / "approval"
    evaluation_dir.mkdir(parents=True, exist_ok=False)
    started_at = now_iso()

    cases = [_evaluate_case(path, evaluation_dir) for path in case_files]
    for case in cases:
        status = "PASS" if case.passed else "FAIL"
        detail = "; ".join(message for section in case.sections for message in section.messages)
        print(f"{case.case_id}: EVAL: {status}" + (f" ({detail})" if detail else ""))

    summary = {
        "evaluation_id": evaluation_id,
        "started_at": started_at,
        "completed_at": now_iso(),
        "suite": "approval",
        "case_count": len(cases),
        "passed_cases": [case.case_id for case in cases if case.passed],
        "failed_cases": [case.case_id for case in cases if not case.passed],
        "metrics": {
            "final_status_match": _ratio(cases, "final_status"),
            "decision_source_match": _ratio(cases, "decision_source"),
            "business_route_match": _ratio(cases, "business_route"),
            "vp_route_match": _ratio(cases, "vp_route"),
        },
    }
    write_artifact(evaluation_dir, "summary.json", summary)
    print(f"Approval evaluation artifacts: {evaluation_dir}")
    return all(case.passed for case in cases)


def _evaluate_case(case_path: Path, evaluation_dir: Path) -> ApprovalEval:
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    case_id = case_path.stem
    artifact_dir = evaluation_dir / case_id
    expected = payload.get("expected", {})
    sections: list[EvalSection] = []
    result: ApprovalResult | None = None
    error: str | None = None

    try:
        request = ApprovalRequest.model_validate(payload["request"])
        _require_upstream_pass(request)
        result = run_approval(
            request,
            artifact_context=RunContext(
                run_id=f"{case_id}_approval",
                run_dir=artifact_dir,
            ),
            persist_artifacts=True,
        )
        sections.extend(_score_result(result, expected))
    except Exception as exc:  # Keep one bad case from hiding the rest of the suite.
        error = f"{type(exc).__name__}: {exc}"
        sections.append(EvalSection("execution", False, [error]))
        artifact_dir.mkdir(parents=True, exist_ok=True)

    write_artifact(artifact_dir, "expected.json", expected)
    write_artifact(
        artifact_dir,
        "evaluation.json",
        {
            "case_id": case_id,
            "passed": all(section.passed for section in sections),
            "sections": [
                {"name": section.name, "passed": section.passed, "messages": section.messages}
                for section in sections
            ],
            "error": error,
            "actual": result,
        },
    )
    return ApprovalEval(case_id, sections, result, artifact_dir, error)


def _require_upstream_pass(request: ApprovalRequest) -> None:
    validation_status = _status_value(request.validation_result)
    reconciliation_status = _status_value(request.reconciliation_result)
    if validation_status != "VALID":
        raise ValueError(f"approval case requires validation status VALID, got {validation_status!r}")
    if reconciliation_status != "PASS":
        raise ValueError(f"approval case requires reconciliation status PASS, got {reconciliation_status!r}")


def _status_value(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "status"):
        value = value.status
    if isinstance(value, dict):
        value = value.get("status")
    if hasattr(value, "value"):
        value = value.value
    return str(value).upper() if value is not None else None


def _score_result(result: ApprovalResult, expected: dict[str, Any]) -> list[EvalSection]:
    business_decision = result.business_rule_decision.decision
    actual_vp_decision = result.vp_decision.decision if result.vp_decision else None
    actual_vp_invoked = result.vp_decision is not None
    sections = [
        _match("business_route", expected.get("business_decision"), business_decision),
        _match("vp_route", expected.get("vp_invoked"), actual_vp_invoked),
        _match("vp_decision", expected.get("vp_decision"), actual_vp_decision),
        _match("final_status", expected.get("final_status"), result.final_status),
        _match("decision_source", expected.get("decision_source"), result.decision_source),
    ]
    required_rule = expected.get("triggered_rule_contains")
    if required_rule is not None:
        rules = result.business_rule_decision.triggered_rules
        sections.append(EvalSection(
            "triggered_rule",
            required_rule in rules,
            [] if required_rule in rules else [f"expected rule {required_rule!r}; actual rules: {rules!r}"],
        ))
    return sections


def _match(name: str, expected: Any, actual: Any) -> EvalSection:
    passed = expected == actual
    return EvalSection(
        name,
        passed,
        [] if passed else [f"expected {expected!r}; actual {actual!r}"],
    )


def _ratio(cases: list[ApprovalEval], section_name: str) -> str:
    total = len(cases)
    matched = sum(
        1
        for case in cases
        if any(section.name == section_name and section.passed for section in case.sections)
    )
    return f"{matched}/{total}"
