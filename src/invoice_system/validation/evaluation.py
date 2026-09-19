"""Isolated Phase 1 semantic validation evaluation.

The primary cases consume the trusted normalized invoice goldens from the
ingestion evaluation.  They do not call ingestion, so a semantic failure is
not obscured by a new extraction result.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Callable

from invoice_system.ingestion.models import (
    IngestionResult,
    IngestionStatus,
    NormalizationResult,
    NormalizedInvoice,
)
from invoice_system.ingestion.run_logging import (
    RunContext,
    make_evaluation_id,
    make_run_id,
    now_iso,
    write_artifact,
)

from .critic import review_stage
from .arithmetic import build_arithmetic_evidence
from .models import (
    CriticDecision,
    ReconciliationResult,
    ValidationStatus,
    SemanticResult,
    ValidationResult,
    ValidationStage,
)
from .reconciliation_evaluation import ReconciliationMetrics, score_reconciliation_result
from .runner import run_validation


@dataclass(frozen=True)
class ExpectedIssue:
    code: str
    field: str | None = None


@dataclass
class SemanticMetrics:
    status_match: bool = False
    expected_issue_code_coverage: bool = False
    expected_issue_field_coverage: bool = False
    unexpected_blocking_issue_count: int = 0
    critic_completion: bool = False
    critic_revision_count: int = 0
    denial_stage_match: bool = True
    overall_semantic_match: bool = False


@dataclass
class SemanticCase:
    case_id: str
    input_reference: dict[str, Any]
    expected: dict[str, Any]
    result: ValidationResult | None
    metrics: SemanticMetrics
    artifact_dir: Path
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and self.metrics.overall_semantic_match and self.metrics.critic_completion


@dataclass
class CriticCase:
    case_id: str
    expected_decision: str
    actual_decision: str | None
    passed: bool
    artifact_dir: Path
    error: str | None = None


def run_semantic_evaluation(root: Path) -> bool:
    """Run isolated Semantic cases and focused critic cases.

    Each case is isolated behind an exception boundary so one malformed case
    or provider failure does not prevent the remaining suite from producing
    artifacts and results.
    """

    expected_dir = root / "evals" / "validation" / "semantic" / "expected"
    expected_files = sorted(expected_dir.glob("*.json"))
    if not expected_files:
        print("No semantic expected files found.")
        return False

    evaluation_id = make_evaluation_id()
    evaluation_dir = root / "logs" / "evals" / evaluation_id
    evaluation_dir.mkdir(parents=True, exist_ok=False)
    started_at = now_iso()

    cases = [_evaluate_case_safely(root, path, evaluation_dir) for path in expected_files]
    critic_cases = _evaluate_critic_cases(root, evaluation_dir)

    _print_results(cases, critic_cases)
    _write_summary(evaluation_dir, evaluation_id, started_at, now_iso(), cases, critic_cases)
    print(f"Evaluation artifacts: {evaluation_dir}")
    return all(case.passed for case in cases) and all(case.passed for case in critic_cases)


def score_semantic_result(
    expected: dict[str, Any],
    result: ValidationResult,
    *,
    critic_revision_count: int = 0,
) -> SemanticMetrics:
    """Compare stable structured Semantic facts, never model prose."""

    semantic = result.semantic_result
    semantic_expectation = expected.get("semantic", expected)
    expected_status = _status_value(semantic_expectation.get("expected_status", "PASS"))
    expected_issues = _expected_issues(semantic_expectation)
    code_coverage = all(
        any(_issue_matches_expected(issue, expected_issue) for issue in semantic.issues)
        for expected_issue in expected_issues
        if expected_issue.code != "__field_only__"
    )
    field_coverage = all(
        any(_issue_matches_expected(issue, expected_issue) for issue in semantic.issues)
        for expected_issue in expected_issues
        if expected_issue.field is not None
    )
    unexpected_blocking = 0
    for issue in semantic.issues:
        if issue.severity.value != "error":
            continue
        expected_match = any(
            _issue_matches_expected(issue, expected_issue)
            for expected_issue in expected_issues
        )
        if not expected_match and (
            expected_status == "PASS" or not _is_supported_semantic_issue(issue, result)
        ):
            unexpected_blocking += 1

    expected_denial_stage = semantic_expectation.get("expected_denial_stage")
    denial_stage_match = True
    if expected_denial_stage is not None:
        actual_stage = result.denied_by.value if result.denied_by is not None else None
        denial_stage_match = actual_stage == str(expected_denial_stage).lower()

    status_match = semantic.status.value == expected_status
    semantic_critic = result.semantic_critic_result
    if semantic_critic is None and result.reconciliation_result is None:
        semantic_critic = result.critic_result
    critic_completion = semantic_critic is not None and semantic_critic.decision == CriticDecision.AGREE
    overall = (
        status_match
        and code_coverage
        and field_coverage
        and unexpected_blocking == 0
        and denial_stage_match
    )
    return SemanticMetrics(
        status_match=status_match,
        expected_issue_code_coverage=code_coverage,
        expected_issue_field_coverage=field_coverage,
        unexpected_blocking_issue_count=unexpected_blocking,
        critic_completion=critic_completion,
        critic_revision_count=critic_revision_count,
        denial_stage_match=denial_stage_match,
        overall_semantic_match=overall,
    )


def _evaluate_case_safely(root: Path, expected_path: Path, evaluation_dir: Path) -> SemanticCase:
    expected: dict[str, Any] = {}
    case_id = expected_path.stem
    artifact_dir = evaluation_dir / case_id
    artifact_dir.mkdir(parents=True, exist_ok=False)
    try:
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        case_id = expected.get("invoice_id", case_id)
        input_reference = expected["input"]
        ingestion = _load_ingestion_input(root, input_reference)
        write_artifact(artifact_dir, "expected.json", expected)
        write_artifact(artifact_dir, "input_reference.json", input_reference)
        context = RunContext(
            run_id=make_run_id(ingestion.source_path, prefix="semantic"),
            run_dir=artifact_dir,
        )
        result = run_validation(ingestion, artifact_context=context)
        revisions = _revision_count(artifact_dir)
        metrics = score_semantic_result(expected, result, critic_revision_count=revisions)
        case = SemanticCase(case_id, input_reference, expected, result, metrics, artifact_dir)
        write_artifact(artifact_dir, "evaluation.json", _semantic_case_payload(case))
        return case
    except Exception as exc:
        error = str(exc)
        metrics = SemanticMetrics()
        case = SemanticCase(case_id, expected.get("input", {}), expected, None, metrics, artifact_dir, error)
        write_artifact(artifact_dir, "evaluation.json", _semantic_case_payload(case))
        return case


def _load_ingestion_input(root: Path, reference: dict[str, Any]) -> IngestionResult:
    kind = reference.get("kind")
    relative_path = reference["path"]
    if kind == "ingestion_golden":
        path = root / "evals" / "ingestion" / "expected" / relative_path
        golden = json.loads(path.read_text(encoding="utf-8"))
        invoice_data = {key: value for key, value in golden.items() if key not in {"fixture", "expected_status"}}
        return IngestionResult(
            status=IngestionStatus.ACCEPT,
            source_path=str(root / "data" / "invoices" / golden["fixture"]),
            normalization=NormalizationResult(
                invoice=NormalizedInvoice.model_validate(invoice_data),
                evidence=[],
            ),
        )
    if kind == "semantic_fixture":
        path = root / "evals" / "validation" / "semantic" / "fixtures" / relative_path
        return IngestionResult.model_validate_json(path.read_text(encoding="utf-8"))
    if kind == "reconciliation_fixture":
        path = root / "evals" / "validation" / "reconciliation" / "fixtures" / relative_path
        return IngestionResult.model_validate_json(path.read_text(encoding="utf-8"))
    raise ValueError(f"Unsupported semantic input kind: {kind!r}")


def _evaluate_critic_cases(root: Path, evaluation_dir: Path) -> list[CriticCase]:
    expected_dir = root / "evals" / "validation" / "semantic" / "critic_expected"
    results: list[CriticCase] = []
    for path in sorted(expected_dir.glob("*.json")):
        expected: dict[str, Any] = {}
        case_id = path.stem
        artifact_dir = evaluation_dir / "critic" / case_id
        artifact_dir.mkdir(parents=True, exist_ok=False)
        try:
            expected = json.loads(path.read_text(encoding="utf-8"))
            case_id = expected.get("case_id", case_id)
            ingestion = _load_ingestion_input(root, expected["input"])
            supplied = SemanticResult.model_validate(expected["supplied_semantic_result"])
            write_artifact(artifact_dir, "expected.json", expected)
            write_artifact(artifact_dir, "validation_input.json", ingestion)
            write_artifact(artifact_dir, "supplied_semantic_result.json", supplied)
            critic = review_stage(ingestion, ValidationStage.SEMANTIC, supplied)
            write_artifact(artifact_dir, "semantic_critic.json", critic)
            expected_decision = _status_value(expected["expected_critic_decision"])
            actual_decision = critic.decision.value
            passed = actual_decision == expected_decision
            result = CriticCase(case_id, expected_decision, actual_decision, passed, artifact_dir)
        except Exception as exc:
            result = CriticCase(
                case_id,
                _status_value(expected.get("expected_critic_decision", "")),
                None,
                False,
                artifact_dir,
                str(exc),
            )
        write_artifact(artifact_dir, "evaluation.json", _critic_case_payload(result))
        results.append(result)
    return results


def _expected_issues(expected: dict[str, Any]) -> list[ExpectedIssue]:
    semantic = expected.get("semantic", expected)
    if "expected_issues" in semantic:
        return [ExpectedIssue(str(item["code"]), item.get("field")) for item in semantic["expected_issues"]]
    return [
        ExpectedIssue(str(code), None)
        for code in semantic.get("expected_issue_codes", [])
    ] + [
        ExpectedIssue("__field_only__", field)
        for field in semantic.get("expected_issue_fields", [])
    ]


def _status_value(value: Any) -> str:
    return str(value).upper()


def _normalise_code(value: str) -> str:
    return value.strip().casefold()


def _normalise_field(value: str | None) -> str | None:
    if value is None:
        return None
    field = value.strip().removeprefix("invoice.")
    return field.replace("line_items[", "items[")


_SEMANTIC_CODE_FAMILIES = {
    "contradictory_dates": "date_order",
    "invoice_date_after_due_date": "date_order",
    "negative_quantity": "negative_quantity",
    "negative_unit_price": "negative_unit_price",
    "negative_invoice_total": "negative_invoice_total",
    "relative_date": "relative_date",
}


def _issue_matches_expected(actual: Any, expected: ExpectedIssue) -> bool:
    if expected.code == "__field_only__":
        return _normalise_field(actual.field) == _normalise_field(expected.field)
    actual_family = _SEMANTIC_CODE_FAMILIES.get(_normalise_code(actual.code), _normalise_code(actual.code))
    expected_family = _SEMANTIC_CODE_FAMILIES.get(_normalise_code(expected.code), _normalise_code(expected.code))
    if actual_family != expected_family:
        return False
    if expected.field is None:
        return True
    actual_field = _normalise_field(actual.field)
    expected_field = _normalise_field(expected.field)
    if actual_field == expected_field:
        return True
    return (
        actual_family == "date_order"
        and actual_field in {"invoice_date", "due_date"}
        and expected_field in {"invoice_date", "due_date"}
    )


def _is_supported_semantic_issue(issue: Any, result: ValidationResult) -> bool:
    """Recognize additional real semantic roots without accepting invented ones."""

    invoice = result.ingestion.normalization.invoice
    family = _SEMANTIC_CODE_FAMILIES.get(_normalise_code(issue.code))
    field = _normalise_field(issue.field)
    if family == "date_order":
        return invoice.invoice_date is not None and invoice.due_date is not None and invoice.invoice_date > invoice.due_date
    if family == "negative_invoice_total":
        return invoice.invoice_total is not None and invoice.invoice_total < 0
    if family in {"negative_quantity", "negative_unit_price"} and field:
        prefix, _, attribute = field.partition("].")
        if prefix.startswith("items[") and attribute in {"quantity", "unit_price"}:
            try:
                index = int(prefix.removeprefix("items["))
            except ValueError:
                return False
            if 0 <= index < len(invoice.items):
                value = getattr(invoice.items[index], attribute)
                return value is not None and value < 0
    if family == "relative_date":
        return bool(invoice.additional_fields.get("due_date_raw"))
    return False


def _contains_all(expected: list[str | None], actual: list[str | None]) -> bool:
    expected_counts = Counter(expected)
    actual_counts = Counter(actual)
    return all(actual_counts[key] >= count for key, count in expected_counts.items())


def _revision_count(artifact_dir: Path, prefix: str = "semantic_v") -> int:
    versions = []
    for path in artifact_dir.glob(f"{prefix}*.json"):
        try:
            versions.append(int(path.stem.removeprefix(prefix)))
        except ValueError:
            continue
    return max(versions, default=1) - 1


def _semantic_case_payload(case: SemanticCase) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "case_id": case.case_id,
        "input": case.input_reference,
        "expected": case.expected,
        "actual": case.result.model_dump(mode="json") if case.result else None,
        "metrics": asdict(case.metrics),
        "passed": case.passed,
    }
    if case.error:
        payload["error"] = case.error
    return payload


def _critic_case_payload(case: CriticCase) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "case_id": case.case_id,
        "expected_decision": case.expected_decision,
        "actual_decision": case.actual_decision,
        "passed": case.passed,
    }
    if case.error:
        payload["error"] = case.error
    return payload


def _write_summary(
    evaluation_dir: Path,
    evaluation_id: str,
    started_at: str,
    completed_at: str,
    cases: list[SemanticCase],
    critic_cases: list[CriticCase],
) -> None:
    expected_code_total = sum(len(_expected_issues(case.expected)) for case in cases)
    expected_field_total = sum(
        sum(issue.field is not None for issue in _expected_issues(case.expected))
        for case in cases
    )
    matched_code_total = sum(
        sum(
            _normalise_code(issue.code) in {
                _normalise_code(actual.code) for actual in case.result.semantic_result.issues
            }
            for issue in _expected_issues(case.expected)
        )
        for case in cases
        if case.result is not None
    )
    matched_field_total = sum(
        sum(
            _normalise_field(issue.field) in {
                _normalise_field(actual.field) for actual in case.result.semantic_result.issues
            }
            for issue in _expected_issues(case.expected)
            if issue.field is not None
        )
        for case in cases
        if case.result is not None
    )
    summary = {
        "evaluation_id": evaluation_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "total": len(cases),
        "passed": sum(case.passed for case in cases),
        "failed": sum(not case.passed for case in cases),
        "metrics": {
            "status_match": f"{sum(case.metrics.status_match for case in cases)}/{len(cases)}",
            "expected_issue_code_coverage": f"{matched_code_total}/{expected_code_total}",
            "expected_issue_field_coverage": f"{matched_field_total}/{expected_field_total}",
            "unexpected_blocking_issue_count": sum(
                case.metrics.unexpected_blocking_issue_count for case in cases
            ),
            "critic_completion": f"{sum(case.metrics.critic_completion for case in cases)}/{len(cases)}",
            "critic_revision_count_total": sum(case.metrics.critic_revision_count for case in cases),
            "overall_semantic_match": f"{sum(case.metrics.overall_semantic_match for case in cases)}/{len(cases)}",
        },
        "cases": [_semantic_case_payload(case) for case in cases],
        "critic_cases": [_critic_case_payload(case) for case in critic_cases],
    }
    write_artifact(evaluation_dir, "summary.json", summary)


def _print_results(cases: list[SemanticCase], critic_cases: list[CriticCase]) -> None:
    print("=" * 50)
    print("SEMANTIC VALIDATION EVALUATION")
    print("=" * 50)
    print()
    print(f"Cases: {len(cases)}")
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case.case_id:<32} {'PASS' if case.passed else 'FAIL'}")
        if not case.passed:
            _print_case_failure(case)
    print()
    print("Critic cases")
    for case in critic_cases:
        print(f"  {case.case_id:<32} {'PASS' if case.passed else 'FAIL'}")
    print()
    print("Summary")
    print("-------")
    print(f"Status match:              {sum(case.metrics.status_match for case in cases)}/{len(cases)}")
    print(
        "Issue code coverage:       "
        f"{sum(case.metrics.expected_issue_code_coverage for case in cases)}/{len(cases)} cases"
    )
    print(
        "Issue field coverage:      "
        f"{sum(case.metrics.expected_issue_field_coverage for case in cases)}/{len(cases)} cases"
    )
    print(
        "Unexpected blocking issue: "
        f"{sum(case.metrics.unexpected_blocking_issue_count for case in cases)}"
    )
    print(f"Critic completion:          {sum(case.metrics.critic_completion for case in cases)}/{len(cases)}")
    print(f"Critic revisions:           {sum(case.metrics.critic_revision_count for case in cases)}")
    print(f"Exact semantic match:       {sum(case.metrics.overall_semantic_match for case in cases)}/{len(cases)}")


def _print_case_failure(case: SemanticCase) -> None:
    if case.error:
        print(f"  error: {case.error}")
        return
    expected_semantic = case.expected.get("semantic", case.expected)
    actual = case.result.semantic_result if case.result else None
    expected_issues = _expected_issues(case.expected)
    actual_issues = [(issue.code, issue.field) for issue in actual.issues] if actual else []
    print(f"  Expected: status={expected_semantic.get('expected_status')}, issues={[(i.code, i.field) for i in expected_issues]}")
    print(f"  Actual:   status={actual.status.value if actual else None}, issues={actual_issues}")
    print(f"  Critic:   {'AGREE' if case.metrics.critic_completion else 'not confirmed'}; revisions={case.metrics.critic_revision_count}")


@dataclass
class ValidationMetrics:
    semantic_match: bool = False
    semantic_critic_completion: bool = False
    semantic_revision_count: int = 0
    reconciliation_evaluated: bool = False
    reconciliation_match: bool = True
    reconciliation_critic_completion: bool = True
    reconciliation_revision_count: int = 0
    route_match: bool = False
    final_status_match: bool = False
    final_stop_match: bool = False
    final_state_match: bool = False
    overall_validation_match: bool = False


@dataclass
class ValidationCase:
    case_id: str
    input_reference: dict[str, Any]
    expected: dict[str, Any]
    result: ValidationResult | None
    semantic_metrics: SemanticMetrics
    reconciliation_metrics: ReconciliationMetrics | None
    metrics: ValidationMetrics
    artifact_dir: Path
    expected_stop: str
    actual_stop: str | None
    differences: list[str]
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and self.metrics.overall_validation_match


def run_validation_evaluation(root: Path) -> bool:
    """Run the one growing Validation Agent evaluation.

    Inputs are trusted normalized goldens or controlled structured fixtures. A
    single full validation graph run handles Semantic first, then routes
    eligible PASS cases through Reconciliation. Later Database and Gate stages
    can extend this case contract without adding another evaluator.
    """

    expected_files = _validation_expected_files(root)
    if not expected_files:
        print("No Validation expected files found.")
        return False

    evaluation_id = make_evaluation_id()
    evaluation_dir = root / "logs" / "evals" / evaluation_id
    evaluation_dir.mkdir(parents=True, exist_ok=False)
    started_at = now_iso()
    print(
        f"Validation Agent evaluation: {len(expected_files)} case(s) "
        "(trusted input; Semantic -> Reconciliation)",
        flush=True,
    )

    cases: list[ValidationCase] = []
    for index, path in enumerate(expected_files, start=1):
        print(f"[{index}/{len(expected_files)}] {path.stem}: started", flush=True)
        case = _evaluate_validation_case_safely(
            root,
            path,
            evaluation_dir,
            progress_callback=lambda message, index=index, total=len(expected_files), path=path: print(
                f"[{index}/{total}] {path.stem}: {message}", flush=True
            ),
        )
        cases.append(case)
        _print_validation_case(case)

    _print_validation_summary(cases)
    _write_validation_summary(
        evaluation_dir,
        evaluation_id,
        started_at,
        now_iso(),
        cases,
    )
    print(f"Evaluation artifacts: {evaluation_dir}")
    return all(case.passed for case in cases)


def run_reconciliation_evaluation(root: Path) -> bool:
    """Backward-compatible name; it now runs the full Validation eval."""

    return run_validation_evaluation(root)


def _validation_expected_files(root: Path) -> list[Path]:
    semantic_dir = root / "evals" / "validation" / "semantic" / "expected"
    reconciliation_dir = root / "evals" / "validation" / "reconciliation" / "expected"
    return sorted(semantic_dir.glob("*.json")) + sorted(reconciliation_dir.glob("*.json"))


def _evaluate_validation_case_safely(
    root: Path,
    expected_path: Path,
    evaluation_dir: Path,
    *,
    progress_callback: Callable[[str], None] | None = None,
) -> ValidationCase:
    expected: dict[str, Any] = {}
    case_id = expected_path.stem
    artifact_dir = evaluation_dir / case_id
    artifact_dir.mkdir(parents=True, exist_ok=False)
    try:
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        case_id = expected.get("invoice_id", case_id)
        input_reference = expected["input"]
        ingestion = _load_ingestion_input(root, input_reference)
        write_artifact(artifact_dir, "expected.json", expected)
        write_artifact(artifact_dir, "expected_semantic.json", expected.get("semantic", {}))
        write_artifact(artifact_dir, "expected_reconciliation.json", expected.get("reconciliation"))
        write_artifact(artifact_dir, "input_reference.json", input_reference)
        write_artifact(artifact_dir, "validation_input.json", ingestion)
        write_artifact(
            artifact_dir,
            "arithmetic_tool_output.json",
            json.loads(
                json.dumps(
                    build_arithmetic_evidence(ingestion.normalization.invoice),
                    default=str,
                )
            ),
        )
        context = RunContext(
            run_id=make_run_id(ingestion.source_path, prefix="validation"),
            run_dir=artifact_dir,
        )
        result = run_validation(
            ingestion,
            artifact_context=context,
            run_reconciliation=True,
            progress_callback=progress_callback,
        )
        semantic_revisions = _revision_count(artifact_dir, "semantic_v")
        semantic_metrics = score_semantic_result(
            expected,
            result,
            critic_revision_count=semantic_revisions,
        )
        semantic_critic_completion = _stage_critic_completed(result, ValidationStage.SEMANTIC)
        semantic_expected_status = _expected_semantic_status(expected)
        reconciliation_expected = expected.get("reconciliation")
        if semantic_expected_status == "PASS" and reconciliation_expected is None:
            raise ValueError("Semantic PASS case is missing its Reconciliation expectation")

        reconciliation_metrics: ReconciliationMetrics | None = None
        reconciliation_revisions = _revision_count(artifact_dir, "reconciliation_v")
        reconciliation_critic_completion = True
        if reconciliation_expected is not None:
            if result.reconciliation_result is None:
                reconciliation_metrics = ReconciliationMetrics()
                reconciliation_critic_completion = False
            else:
                reconciliation_critic_completion = _stage_critic_completed(
                    result,
                    ValidationStage.RECONCILIATION,
                )
                reconciliation_metrics = score_reconciliation_result(
                    expected,
                    result.reconciliation_result,
                    critic_revision_count=reconciliation_revisions,
                    critic_completion=reconciliation_critic_completion,
                )

        expected_stop = _expected_validation_stop(expected)
        actual_stop = _actual_validation_stop(result)
        route_match = _validation_route_matches(
            result,
            semantic_expected_status,
            reconciliation_expected,
        )
        final_status_match = _expected_final_status(expected) == result.status.value
        final_stop_match = expected_stop == actual_stop
        final_state_match = _final_state_matches(
            semantic_metrics,
            semantic_critic_completion,
            reconciliation_metrics,
            reconciliation_critic_completion,
            semantic_expected_status,
        )
        metrics = ValidationMetrics(
            semantic_match=semantic_metrics.overall_semantic_match,
            semantic_critic_completion=semantic_critic_completion,
            semantic_revision_count=semantic_revisions,
            reconciliation_evaluated=reconciliation_expected is not None,
            reconciliation_match=(
                reconciliation_metrics.overall_reconciliation_match
                if reconciliation_metrics is not None
                else reconciliation_expected is None
            ),
            reconciliation_critic_completion=reconciliation_critic_completion,
            reconciliation_revision_count=reconciliation_revisions,
            route_match=route_match,
            final_status_match=final_status_match,
            final_stop_match=final_stop_match,
            final_state_match=final_state_match,
            overall_validation_match=(
                semantic_metrics.overall_semantic_match
                and semantic_critic_completion
                and route_match
                and final_status_match
                and final_stop_match
                and final_state_match
                and (
                    reconciliation_expected is None
                    or (
                        reconciliation_metrics is not None
                        and reconciliation_metrics.overall_reconciliation_match
                        and reconciliation_critic_completion
                    )
                )
            ),
        )
        case = ValidationCase(
            case_id=case_id,
            input_reference=input_reference,
            expected=expected,
            result=result,
            semantic_metrics=semantic_metrics,
            reconciliation_metrics=reconciliation_metrics,
            metrics=metrics,
            artifact_dir=artifact_dir,
            expected_stop=expected_stop,
            actual_stop=actual_stop,
            differences=_validation_case_differences(
                expected,
                result,
                metrics,
                reconciliation_metrics,
            ),
        )
        write_artifact(artifact_dir, "evaluation.json", _validation_case_payload(case))
        return case
    except Exception as exc:
        case = ValidationCase(
            case_id=case_id,
            input_reference=expected.get("input", {}),
            expected=expected,
            result=None,
            semantic_metrics=SemanticMetrics(),
            reconciliation_metrics=None,
            metrics=ValidationMetrics(),
            artifact_dir=artifact_dir,
            expected_stop=_expected_validation_stop(expected),
            actual_stop=None,
            differences=[],
            error=str(exc),
        )
        write_artifact(artifact_dir, "evaluation.json", _validation_case_payload(case))
        return case


def _stage_critic_completed(result: ValidationResult, stage: ValidationStage) -> bool:
    critic = (
        result.semantic_critic_result
        if stage == ValidationStage.SEMANTIC
        else result.reconciliation_critic_result
    )
    return critic is not None and critic.decision == CriticDecision.AGREE


def _expected_semantic_status(expected: dict[str, Any]) -> str:
    return _status_value(expected.get("semantic", {}).get("expected_status", "PASS"))


def _expected_reconciliation_status(expected: dict[str, Any]) -> str | None:
    reconciliation = expected.get("reconciliation")
    if reconciliation is None:
        return None
    return _status_value(reconciliation.get("expected_status", "PASS"))


def _expected_validation_stop(expected: dict[str, Any]) -> str:
    explicit = expected.get("expected_stop")
    if explicit:
        return str(explicit).lower()
    semantic_status = _expected_semantic_status(expected)
    if semantic_status == "DENY":
        return "semantic"
    reconciliation_status = _expected_reconciliation_status(expected)
    if reconciliation_status == "DENY":
        return "reconciliation"
    return "validation"


def _actual_validation_stop(result: ValidationResult) -> str:
    return result.denied_by.value if result.denied_by is not None else "validation"


def _expected_final_status(expected: dict[str, Any]) -> str:
    if _expected_semantic_status(expected) == "DENY":
        return ValidationStatus.DENIED.value
    if _expected_reconciliation_status(expected) == "DENY":
        return ValidationStatus.DENIED.value
    return ValidationStatus.VALID.value


def _validation_route_matches(
    result: ValidationResult,
    expected_semantic_status: str,
    reconciliation_expected: dict[str, Any] | None,
) -> bool:
    if expected_semantic_status == "DENY":
        return result.denied_by == ValidationStage.SEMANTIC and result.reconciliation_result is None
    return (
        result.semantic_result.status.value == "PASS"
        and reconciliation_expected is not None
        and result.reconciliation_result is not None
    )


def _final_state_matches(
    semantic_metrics: SemanticMetrics,
    semantic_critic_completion: bool,
    reconciliation_metrics: ReconciliationMetrics | None,
    reconciliation_critic_completion: bool,
    expected_semantic_status: str,
) -> bool:
    if not semantic_metrics.overall_semantic_match or not semantic_critic_completion:
        return False
    if expected_semantic_status == "DENY":
        return True
    return (
        reconciliation_metrics is not None
        and reconciliation_metrics.overall_reconciliation_match
        and reconciliation_critic_completion
    )


def _validation_case_differences(
    expected: dict[str, Any],
    result: ValidationResult,
    metrics: ValidationMetrics,
    reconciliation_metrics: ReconciliationMetrics | None,
) -> list[str]:
    differences: list[str] = []
    expected_semantic = expected.get("semantic", {})
    actual_semantic = result.semantic_result
    if not metrics.semantic_match:
        differences.append(
            f"Semantic: expected {expected_semantic.get('expected_status')}, "
            f"actual {actual_semantic.status.value}"
        )
        differences.extend(_missing_issue_descriptions(expected_semantic, actual_semantic.issues))
    if not metrics.semantic_critic_completion:
        differences.append("Semantic critic did not AGREE")
    if not metrics.route_match:
        differences.append(
            f"routing: expected stop {_expected_validation_stop(expected)}, "
            f"actual stop {_actual_validation_stop(result)}"
        )
    if reconciliation_metrics is not None:
        expected_reconciliation = expected.get("reconciliation", {})
        actual_reconciliation = result.reconciliation_result
        if actual_reconciliation is None:
            differences.append("Reconciliation: expected a result, but the stage did not run")
        else:
            if not reconciliation_metrics.status_match:
                differences.append(
                    f"Reconciliation: expected {expected_reconciliation.get('expected_status')}, "
                    f"actual {actual_reconciliation.status.value}"
                )
            if not reconciliation_metrics.expected_issue_code_coverage:
                differences.append("Reconciliation: expected issue-code coverage is incomplete")
            if not reconciliation_metrics.expected_issue_field_coverage:
                differences.append("Reconciliation: expected issue-field coverage is incomplete")
            if not reconciliation_metrics.consolidation_accuracy:
                differences.append(
                    "Reconciliation consolidated state mismatch: "
                    f"expected {_expected_consolidated_state(expected_reconciliation)}, "
                    f"actual {_actual_consolidated_state(actual_reconciliation)}"
                )
            if not reconciliation_metrics.arithmetic_accuracy:
                differences.append("Reconciliation arithmetic output mismatch")
            if reconciliation_metrics.unexpected_blocking_issue_count:
                differences.append(
                    "Reconciliation unexpected blocking issues: "
                    f"{reconciliation_metrics.unexpected_blocking_issue_count}"
                )
            if not reconciliation_metrics.critic_completion:
                differences.append("Reconciliation critic did not AGREE")
    if not metrics.final_status_match:
        differences.append(
            f"final status: expected {_expected_final_status(expected)}, "
            f"actual {result.status.value}"
        )
    if not metrics.final_stop_match:
        differences.append(
            f"final stop: expected {metrics_expected_stop(expected)}, "
            f"actual {_actual_validation_stop(result)}"
        )
    return differences


def metrics_expected_stop(expected: dict[str, Any]) -> str:
    """Compatibility-friendly label helper used in readable failure output."""

    return _expected_validation_stop(expected)


def _missing_issue_descriptions(expected: dict[str, Any], actual_issues: list[Any]) -> list[str]:
    expected_issues = _expected_issues(expected)
    descriptions: list[str] = []
    for issue in expected_issues:
        if issue.code == "__field_only__":
            matched = any(_normalise_field(actual.field) == _normalise_field(issue.field) for actual in actual_issues)
        else:
            matched = any(
                _normalise_code(actual.code) == _normalise_code(issue.code)
                and (issue.field is None or _normalise_field(actual.field) == _normalise_field(issue.field))
                for actual in actual_issues
            )
        if not matched:
            descriptions.append(
                f"missing Semantic issue: code={issue.code}, field={issue.field}"
            )
    return descriptions


def _expected_consolidated_state(expected: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "product": item.get("normalized_product") or item.get("product_name"),
            "quantity": item.get("expected_quantity", item.get("combined_quantity")),
            "source_lines": item.get("expected_source_lines"),
            "calculated_line_total": item.get("expected_derived_line_total"),
        }
        for item in expected.get("expected_consolidated_items", [])
    ]


def _actual_consolidated_state(result: ReconciliationResult) -> list[dict[str, Any]]:
    return [
        {
            "product": item.normalized_product or item.product_name,
            "quantity": str(item.combined_quantity),
            "source_lines": item.source_lines,
            "calculated_line_total": (
                str(item.derived_line_total) if item.derived_line_total is not None else None
            ),
        }
        for item in result.consolidated_items
    ]


def _validation_case_payload(case: ValidationCase) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "case_id": case.case_id,
        "input": case.input_reference,
        "expected": case.expected,
        "expected_stop": case.expected_stop,
        "actual_stop": case.actual_stop,
        "actual": case.result.model_dump(mode="json") if case.result else None,
        "semantic_metrics": asdict(case.semantic_metrics),
        "reconciliation_metrics": (
            asdict(case.reconciliation_metrics)
            if case.reconciliation_metrics is not None
            else None
        ),
        "metrics": asdict(case.metrics),
        "differences": case.differences,
        "passed": case.passed,
    }
    if case.error:
        payload["error"] = case.error
    return payload


def _write_validation_summary(
    evaluation_dir: Path,
    evaluation_id: str,
    started_at: str,
    completed_at: str,
    cases: list[ValidationCase],
) -> None:
    semantic_denied = [
        case.case_id
        for case in cases
        if case.result is not None
        and case.result.denied_by == ValidationStage.SEMANTIC
    ]
    reconciliation_denied = [
        case.case_id
        for case in cases
        if case.result is not None
        and case.result.denied_by == ValidationStage.RECONCILIATION
    ]
    summary = {
        "evaluation_id": evaluation_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "total": len(cases),
        "passed": sum(case.passed for case in cases),
        "failed": sum(not case.passed for case in cases),
        "semantic_denied": semantic_denied,
        "reconciliation_denied": reconciliation_denied,
        "passed_current_validation_pipeline": [case.case_id for case in cases if case.passed],
        "evaluation_failures": [case.case_id for case in cases if not case.passed],
        "metrics": {
            "semantic_status_match": f"{sum(case.semantic_metrics.status_match for case in cases)}/{len(cases)}",
            "semantic_critic_completion": f"{sum(case.metrics.semantic_critic_completion for case in cases)}/{len(cases)}",
            "reconciliation_status_match": f"{sum(case.reconciliation_metrics is not None and case.reconciliation_metrics.status_match for case in cases)}/{sum(case.metrics.reconciliation_evaluated for case in cases)}",
            "reconciliation_critic_completion": f"{sum(case.metrics.reconciliation_critic_completion for case in cases if case.metrics.reconciliation_evaluated)}/{sum(case.metrics.reconciliation_evaluated for case in cases)}",
            "semantic_revisions": sum(case.metrics.semantic_revision_count for case in cases),
            "reconciliation_revisions": sum(case.metrics.reconciliation_revision_count for case in cases),
            "route_match": f"{sum(case.metrics.route_match for case in cases)}/{len(cases)}",
            "final_state_match": f"{sum(case.metrics.final_state_match for case in cases)}/{len(cases)}",
            "overall_validation_match": f"{sum(case.passed for case in cases)}/{len(cases)}",
        },
        "cases": [_validation_case_payload(case) for case in cases],
    }
    write_artifact(evaluation_dir, "summary.json", summary)


def _print_validation_case(case: ValidationCase) -> None:
    print()
    print(case.case_id)
    if case.error:
        print(f"ERROR: {case.error}")
        print("EVAL: FAIL")
        return
    result = case.result
    if result is None:
        print("ERROR: no validation result")
        print("EVAL: FAIL")
        return

    semantic = result.semantic_result
    print()
    print("[semantic]")
    print(semantic.status.value)
    for issue in semantic.issues:
        print(f"{issue.code}: {issue.field or 'invoice'}")
    semantic_critic = result.semantic_critic_result
    if semantic_critic is not None:
        print(
            f"critic: {semantic_critic.decision.value}; "
            f"revisions: {case.metrics.semantic_revision_count}"
        )

    if result.reconciliation_result is not None:
        reconciliation = result.reconciliation_result
        print()
        print("[reconciliation]")
        _print_consolidated_items(result, reconciliation)
        _print_reconciliation_calculations(result)
        if reconciliation.issues:
            print("issues:")
            for issue in reconciliation.issues:
                print(f"{issue.code}: {issue.field or 'invoice'}")
        else:
            print("issues: none")
        reconciliation_critic = result.reconciliation_critic_result
        if reconciliation_critic is not None:
            print(
                f"critic: {reconciliation_critic.decision.value}; "
                f"revisions: {case.metrics.reconciliation_revision_count}"
            )
        print(reconciliation.status.value)
    else:
        print(f"Expected stop: {case.expected_stop.title()}")

    print()
    print(f"Expected final state: {'MATCH' if case.metrics.final_state_match else 'MISMATCH'}")
    print(f"EVAL: {'PASS' if case.passed else 'FAIL'}")
    if case.differences and not case.passed:
        for difference in case.differences:
            print(f"  {difference}")


def _print_consolidated_items(result: ValidationResult, reconciliation: ReconciliationResult) -> None:
    invoice = result.ingestion.normalization.invoice
    for item in reconciliation.consolidated_items:
        print(f"{item.product_name}:")
        print(f"  source lines: {item.source_lines}")
        quantities: list[str] = []
        for line in item.source_lines:
            if 0 < line <= len(invoice.items) and invoice.items[line - 1].quantity is not None:
                quantities.append(_format_decimal(invoice.items[line - 1].quantity))
        expression = " + ".join(quantities) if quantities else "?"
        print(f"  quantity: {expression} = {_format_decimal(item.combined_quantity)}")
        if item.derived_line_total is not None:
            print(f"  calculated total: {_format_decimal(item.derived_line_total)}")


def _print_reconciliation_calculations(result: ValidationResult) -> None:
    reconciliation = result.reconciliation_result
    if reconciliation is None:
        return
    evidence = build_arithmetic_evidence(result.ingestion.normalization.invoice)
    if evidence.get("calculated_subtotal") is not None or evidence.get("declared_subtotal") is not None:
        print(
            "subtotal: "
            f"{_format_optional_decimal(evidence.get('calculated_subtotal'))} calculated / "
            f"{_format_optional_decimal(evidence.get('declared_subtotal'))} declared"
        )
    if evidence.get("calculated_total") is not None or evidence.get("declared_total") is not None:
        print(
            "total: "
            f"{_format_optional_decimal(evidence.get('calculated_total'))} calculated / "
            f"{_format_optional_decimal(evidence.get('declared_total'))} declared"
        )
    for calculation in reconciliation.calculations:
        print(
            f"{calculation.check_type.value} {calculation.outcome.value} "
            f"{calculation.field or 'invoice'}: "
            f"calculated={_format_optional_decimal(calculation.calculated)}, "
            f"declared={_format_optional_decimal(calculation.declared)}"
        )


def _format_optional_decimal(value: Any) -> str:
    return "missing" if value is None else _format_decimal(value)


def _format_decimal(value: Any) -> str:
    return format(value, "f")


def _print_validation_summary(cases: list[ValidationCase]) -> None:
    def names(items: list[str]) -> str:
        return ", ".join(items) if items else "none"

    semantic_denied = [
        case.case_id
        for case in cases
        if case.result is not None and case.result.denied_by == ValidationStage.SEMANTIC
    ]
    reconciliation_denied = [
        case.case_id
        for case in cases
        if case.result is not None and case.result.denied_by == ValidationStage.RECONCILIATION
    ]
    passed = [case.case_id for case in cases if case.passed]
    failures = [case.case_id for case in cases if not case.passed]
    print()
    print("Summary")
    print(f"Semantic denied: {names(semantic_denied)}")
    print(f"Reconciliation denied: {names(reconciliation_denied)}")
    print(f"Passed current Validation pipeline: {names(passed)}")
    print(f"Evaluation failures: {names(failures)}")
