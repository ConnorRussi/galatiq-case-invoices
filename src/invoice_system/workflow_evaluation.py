"""Live end-to-end evaluation of every invoice document in the corpus."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ingestion.run_logging import RunContext, make_evaluation_id, now_iso, write_artifact
from .workflow import WorkflowResult, run_invoice_workflow


@dataclass
class EvalSection:
    name: str
    passed: bool
    messages: list[str] = field(default_factory=list)


@dataclass
class WorkflowEval:
    case_id: str
    invoice_path: str
    artifact_dir: Path
    sections: list[EvalSection] = field(default_factory=list)
    result: WorkflowResult | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return bool(self.sections) and all(section.passed for section in self.sections)


def run_workflow_evaluation(root: Path, *, database_path: str | Path | None = None) -> bool:
    """Run the live workflow once for every explicitly expected invoice case."""

    manifest_path = root / "evals" / "workflow" / "cases.json"
    if not manifest_path.exists():
        print(f"Workflow evaluation manifest not found: {manifest_path}")
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = manifest.get("cases", [])
    if not cases:
        print(f"No workflow evaluation cases found in {manifest_path}")
        return False
    expected_sources = {str(case["invoice_path"]) for case in cases}
    actual_sources = {
        path.relative_to(root).as_posix()
        for path in (root / "data" / "invoices").iterdir()
        if path.is_file()
    }
    if expected_sources != actual_sources:
        missing = sorted(actual_sources - expected_sources)
        extra = sorted(expected_sources - actual_sources)
        print(
            "Workflow evaluation manifest does not cover the invoice corpus: "
            f"missing={missing!r}; extra={extra!r}"
        )
        return False

    evaluation_id = make_evaluation_id()
    evaluation_dir = root / "logs" / "evals" / evaluation_id / "workflow"
    evaluation_dir.mkdir(parents=True, exist_ok=False)
    started_at = now_iso()
    results = [
        _evaluate_case(
            case,
            root=root,
            evaluation_dir=evaluation_dir,
            database_path=database_path or root / "inventory.sqlite",
        )
        for case in cases
    ]

    for case in results:
        status = "PASS" if case.passed else "FAIL"
        detail = "; ".join(
            message
            for section in case.sections
            for message in section.messages
        )
        print(f"{case.case_id}: EVAL: {status}" + (f" ({detail})" if detail else ""))

    section_names = [
        "workflow_status",
        "stopped_at",
        "validation_status",
        "validation_denial_stage",
        "approval_status",
        "approval_decision_source",
        "payment_status",
        "vp_invoked",
        "vp_decision",
    ]
    summary = {
        "evaluation_id": evaluation_id,
        "started_at": started_at,
        "completed_at": now_iso(),
        "suite": "workflow",
        "case_count": len(results),
        "passed_cases": [case.case_id for case in results if case.passed],
        "failed_cases": [case.case_id for case in results if not case.passed],
        "metrics": {name: _ratio(results, name) for name in section_names},
        "mismatch_categories": _mismatch_categories(results),
    }
    write_artifact(evaluation_dir, "summary.json", summary)
    print(f"Workflow evaluation artifacts: {evaluation_dir}")
    return all(case.passed for case in results)


def _evaluate_case(
    case: dict[str, Any],
    *,
    root: Path,
    evaluation_dir: Path,
    database_path: str | Path,
) -> WorkflowEval:
    case_id = str(case["case_id"])
    invoice_path = str(case["invoice_path"])
    expected = case.get("expected", {})
    artifact_dir = evaluation_dir / case_id
    artifact_dir.parent.mkdir(parents=True, exist_ok=True)
    evaluation = WorkflowEval(case_id=case_id, invoice_path=invoice_path, artifact_dir=artifact_dir)

    try:
        source_path = root / invoice_path
        result = run_invoice_workflow(
            source_path,
            database_path=database_path,
            artifact_context=RunContext(
                run_id=f"{evaluation_dir.parent.name}_{case_id}",
                run_dir=artifact_dir,
            ),
            persist_artifacts=True,
        )
        evaluation.result = result
        evaluation.events = _read_events(artifact_dir / "events.jsonl")
        evaluation.sections = _score_result(result, evaluation.events, expected)
    except Exception as exc:  # Keep one bad live case from hiding the rest.
        evaluation.error = f"{type(exc).__name__}: {exc}"
        evaluation.sections = [EvalSection("execution", False, [evaluation.error])]
        artifact_dir.mkdir(parents=True, exist_ok=True)

    write_artifact(artifact_dir, "expected.json", expected)
    write_artifact(
        artifact_dir,
        "evaluation.json",
        {
            "case_id": case_id,
            "invoice_path": invoice_path,
            "passed": evaluation.passed,
            "sections": [
                {
                    "name": section.name,
                    "passed": section.passed,
                    "messages": section.messages,
                }
                for section in evaluation.sections
            ],
            "error": evaluation.error,
            "actual": evaluation.result,
        },
    )
    return evaluation


def _score_result(
    result: WorkflowResult,
    events: list[dict[str, Any]],
    expected: dict[str, Any],
) -> list[EvalSection]:
    validation_status = result.validation.status.value if result.validation is not None else None
    denial_stage = (
        result.validation.denied_by.value
        if result.validation is not None and result.validation.denied_by is not None
        else None
    )
    approval_status = result.approval.final_status if result.approval is not None else None
    decision_source = result.approval.decision_source if result.approval is not None else None
    payment_status = result.payment.status.value if result.payment is not None else None
    vp_decision = (
        result.approval.vp_decision.decision
        if result.approval is not None and result.approval.vp_decision is not None
        else None
    )
    vp_invoked = any(
        event.get("stage") == "vp_agent"
        and event.get("event") in {"invoked", "decision"}
        for event in events
    )

    sections = [
        _match("workflow_status", expected.get("workflow_status"), result.status.value),
        _match("stopped_at", expected.get("stopped_at"), result.stopped_at),
        _match("validation_status", expected.get("validation_status"), validation_status),
        _match("validation_denial_stage", expected.get("validation_denial_stage"), denial_stage),
        _match("approval_status", expected.get("approval_status"), approval_status),
        _match("approval_decision_source", expected.get("approval_decision_source"), decision_source),
        _match("payment_status", expected.get("payment_status"), payment_status),
        _match("vp_invoked", expected.get("vp_invoked"), vp_invoked),
        _match("vp_decision", expected.get("vp_decision"), vp_decision),
    ]

    expected_issue_codes = set(expected.get("validation_issue_codes", []))
    if expected_issue_codes:
        actual_issue_codes = {
            issue.code
            for issue in (result.validation.issues if result.validation is not None else [])
        }
        missing = sorted(expected_issue_codes - actual_issue_codes)
        sections.append(
            EvalSection(
                "validation_issue_codes",
                not missing,
                [] if not missing else [f"missing issue code(s): {missing!r}"],
            )
        )
    return sections


def _match(name: str, expected: Any, actual: Any) -> EvalSection:
    passed = expected == actual
    return EvalSection(
        name,
        passed,
        [] if passed else [f"expected {expected!r}; actual {actual!r}"],
    )


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _ratio(results: list[WorkflowEval], section_name: str) -> str:
    matched = sum(
        1
        for result in results
        if any(
            section.name == section_name and section.passed
            for section in result.sections
        )
    )
    return f"{matched}/{len(results)}"


def _mismatch_categories(results: list[WorkflowEval]) -> dict[str, int]:
    categories = {"unexpected_denial": 0, "unexpected_acceptance": 0, "other": 0}
    for result in results:
        if result.passed or result.result is None:
            continue
        expected_status = next(
            (section.messages[0] for section in result.sections if section.name == "workflow_status" and section.messages),
            "",
        )
        if "APPROVED_AND_PAID" in expected_status:
            categories["unexpected_denial"] += 1
        elif "VALIDATION_DENIED" in expected_status or "APPROVAL_REJECTED" in expected_status:
            categories["unexpected_acceptance"] += 1
        else:
            categories["other"] += 1
    return categories
