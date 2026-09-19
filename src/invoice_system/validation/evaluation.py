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
from typing import Any

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
from .models import (
    CriticDecision,
    SemanticResult,
    ValidationResult,
    ValidationStage,
)
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
    actual_codes = [_normalise_code(issue.code) for issue in semantic.issues]
    actual_fields = [_normalise_field(issue.field) for issue in semantic.issues if issue.field]

    expected_codes = [_normalise_code(issue.code) for issue in expected_issues]
    expected_fields = [_normalise_field(issue.field) for issue in expected_issues if issue.field]
    code_coverage = _contains_all(expected_codes, actual_codes)
    field_coverage = _contains_all(expected_fields, actual_fields)

    expected_pairs = {
        (_normalise_code(issue.code), _normalise_field(issue.field))
        for issue in expected_issues
    }
    unexpected_blocking = 0
    for issue in semantic.issues:
        if issue.severity.value != "error":
            continue
        pair = (_normalise_code(issue.code), _normalise_field(issue.field))
        if pair not in expected_pairs:
            unexpected_blocking += 1

    expected_denial_stage = semantic_expectation.get("expected_denial_stage")
    denial_stage_match = True
    if expected_denial_stage is not None:
        actual_stage = result.denied_by.value if result.denied_by is not None else None
        denial_stage_match = actual_stage == str(expected_denial_stage).lower()

    status_match = semantic.status.value == expected_status
    critic_completion = result.critic_result.decision == CriticDecision.AGREE
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


def _contains_all(expected: list[str | None], actual: list[str | None]) -> bool:
    expected_counts = Counter(expected)
    actual_counts = Counter(actual)
    return all(actual_counts[key] >= count for key, count in expected_counts.items())


def _revision_count(artifact_dir: Path) -> int:
    versions = []
    for path in artifact_dir.glob("semantic_v*.json"):
        try:
            versions.append(int(path.stem.removeprefix("semantic_v")))
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
