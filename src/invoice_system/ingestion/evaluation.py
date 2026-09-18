"""LangSmith golden-dataset synchronization and ingestion evaluation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable
from uuid import uuid4

from dotenv import load_dotenv
from langsmith import Client

from .artifacts import atomic_json
from .config import IngestionSettings, load_settings
from .ingest import ingest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = PROJECT_ROOT.parent
MANIFEST_PATH = Path(__file__).with_name("evals") / "ingestion_golden.json"
DATASET_NAME = "galatiq-ingestion-golden-v1"
DEFAULT_EVALUATION_ROOT = PROJECT_ROOT / "runs" / "evaluations"


class EvaluationConfigurationError(ValueError):
    """Raised when the requested ingestion test scope cannot be selected."""


class EvaluationExecutionError(RuntimeError):
    """Raised when the local evaluation runner cannot complete."""


def _evaluation_directory_name(started_at: datetime, evaluation_id: str) -> str:
    """Return a sortable, human-readable evaluation folder name.

    Keep the identifier suffix so evaluations begun in the same second cannot
    overwrite each other's artifacts.
    """
    return f"{started_at:%Y-%m-%d_%H-%M-%S}__{evaluation_id}"


def load_manifest() -> list[dict[str, Any]]:
    examples = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if len(examples) != 20:
        raise ValueError(f"Expected 20 golden artifacts, found {len(examples)}")
    artifacts = [example["inputs"]["artifact"] for example in examples]
    if len(set(artifacts)) != len(artifacts):
        raise ValueError("Golden manifest contains duplicate artifact paths")
    for artifact in artifacts:
        if not (PROJECT_ROOT / artifact).is_file():
            raise ValueError(f"Golden artifact does not exist: {artifact}")
    return examples


def sync_dataset(client: Client, examples: list[dict[str, Any]]) -> str:
    datasets = list(client.list_datasets(dataset_name=DATASET_NAME))
    dataset = datasets[0] if datasets else client.create_dataset(
        dataset_name=DATASET_NAME,
        description=(
            "Twenty supplied invoice artifacts with human-reviewed ingestion outputs."
        ),
    )
    existing = {
        example.inputs.get("artifact"): example
        for example in client.list_examples(dataset_id=dataset.id)
    }
    for payload in examples:
        artifact = payload["inputs"]["artifact"]
        current = existing.get(artifact)
        if current is None:
            client.create_example(
                dataset_id=dataset.id,
                inputs=payload["inputs"],
                outputs=payload["outputs"],
                metadata=payload["metadata"],
            )
        else:
            client.update_example(
                example_id=current.id,
                inputs=payload["inputs"],
                outputs=payload["outputs"],
                metadata=payload["metadata"],
            )
    return str(dataset.id)


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _canonical(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_canonical(child) for child in value]
    return value


def _normalized_value(field: Any) -> Any:
    if field is None:
        return None
    return _canonical(getattr(field, "normalized", field))


def _original(field: Any) -> Any:
    return getattr(field, "original", None)


def project_result(result: Any) -> dict[str, Any]:
    """Project rich or compact ingestion results onto the golden contract."""
    invoice = getattr(result, "invoice", None)
    if invoice is None:
        return {
            "invoice": None,
            "issue_codes": sorted(_issue_codes(result)),
            "evidence_present": False,
        }
    if hasattr(invoice.invoice_number, "normalized"):
        items = []
        for row in invoice.line_items:
            items.append(
                {
                    "source_name": _original(row.name),
                    "normalized_name": _normalized_value(row.name),
                    "quantity": _decimal_text(_normalized_value(row.quantity), money=False),
                    "unit_price": _decimal_text(_normalized_value(row.unit_price)),
                    "declared_amount": _decimal_text(
                        _normalized_value(row.declared_amount)
                    ),
                    "note": _normalized_value(row.note),
                }
            )
        invoice_projection = {
            "invoice_number": _normalized_value(invoice.invoice_number),
            "revision": _normalized_value(invoice.revision),
            "vendor": _normalized_value(invoice.vendor),
            "invoice_date": _normalized_value(invoice.invoice_date),
            "due_date": _normalized_value(invoice.due_date),
            "currency": _normalized_value(invoice.currency),
            "line_items": items,
            "subtotal": _decimal_text(_normalized_value(invoice.subtotal)),
            "tax": _decimal_text(_normalized_value(invoice.tax)),
            "shipping": _decimal_text(_normalized_value(invoice.shipping)),
            "fees": _decimal_text(_normalized_value(invoice.fees)),
            "declared_total": _decimal_text(_normalized_value(invoice.declared_total)),
            "payment_terms": _normalized_value(invoice.payment_terms),
        }
        evidence_present = _rich_evidence_present(invoice)
    else:
        invoice_projection = invoice.model_dump(mode="json")
        evidence_present = bool(getattr(result, "evidence", []))
    return {
        "invoice": _canonical(invoice_projection),
        "issue_codes": sorted(_issue_codes(result)),
        "evidence_present": evidence_present,
    }


def _decimal_text(value: Any, *, money: bool = True) -> str | None:
    if value is None:
        return None
    number = Decimal(str(value))
    if money:
        return f"{number:.2f}"
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _issue_codes(result: Any) -> list[str]:
    if hasattr(result, "issue_codes"):
        return list(result.issue_codes)
    codes: list[str] = []
    for issue in getattr(result, "issues", []):
        code = issue.code
        if code == "MISSING_FIELD" and issue.field:
            code = f"MISSING_{issue.field.upper()}"
            codes.append(code)
        elif code == "UNPARSEABLE_FIELD" and issue.field == "due_date":
            codes.extend(("AMBIGUOUS_DUE_DATE", "MISSING_DUE_DATE"))
        else:
            codes.append(code)
    return codes


def _rich_evidence_present(invoice: Any) -> bool:
    fields: list[Any] = []
    for name in type(invoice).model_fields:
        if name == "line_items":
            for row in invoice.line_items:
                fields.extend(getattr(row, child) for child in type(row).model_fields)
        else:
            fields.append(getattr(invoice, name))
    populated = [field for field in fields if _normalized_value(field) is not None]
    return bool(populated) and all(field.evidence for field in populated)


def ingestion_target(inputs: dict[str, Any]) -> dict[str, Any]:
    source = (PROJECT_ROOT / inputs["artifact"]).resolve()
    with tempfile.TemporaryDirectory(prefix="galatiq-eval-") as temporary:
        batch = ingest([source], runs_dir=Path(temporary))
    return project_result(batch.results[0].result)


def _diff(expected: Any, actual: Any, path: str = "$") -> list[str]:
    if type(expected) is not type(actual):
        return [f"{path}: expected {expected!r}, got {actual!r}"]
    if isinstance(expected, dict):
        differences: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            if key not in expected:
                differences.append(f"{path}.{key}: unexpected {actual[key]!r}")
            elif key not in actual:
                differences.append(f"{path}.{key}: missing; expected {expected[key]!r}")
            else:
                differences.extend(_diff(expected[key], actual[key], f"{path}.{key}"))
        return differences
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [f"{path}: expected {len(expected)} entries, got {len(actual)}"]
        differences = []
        for index, (left, right) in enumerate(zip(expected, actual)):
            differences.extend(_diff(left, right, f"{path}[{index}]"))
        return differences
    return [] if expected == actual else [f"{path}: expected {expected!r}, got {actual!r}"]


def _score(run: Any, example: Any, key: str, selector) -> dict[str, Any]:
    expected = selector(example.outputs)
    actual = selector(run.outputs)
    differences = _diff(expected, actual)
    return {
        "key": key,
        "score": 0 if differences else 1,
        "comment": "\n".join(differences[:20]) if differences else "Exact match",
    }


def invoice_fields_match(run: Any, example: Any) -> dict[str, Any]:
    fields = (
        "invoice_number", "revision", "vendor", "invoice_date", "due_date",
        "currency", "payment_terms",
    )
    return _score(
        run,
        example,
        "invoice_fields_match",
        lambda output: {name: output["invoice"][name] for name in fields}
        if output.get("invoice") else None,
    )


def line_items_match(run: Any, example: Any) -> dict[str, Any]:
    return _score(
        run, example, "line_items_match",
        lambda output: output["invoice"]["line_items"] if output.get("invoice") else None,
    )


def amounts_match(run: Any, example: Any) -> dict[str, Any]:
    fields = ("subtotal", "tax", "shipping", "fees", "declared_total")
    return _score(
        run,
        example,
        "amounts_match",
        lambda output: {name: output["invoice"][name] for name in fields}
        if output.get("invoice") else None,
    )


def issues_match(run: Any, example: Any) -> dict[str, Any]:
    return _score(run, example, "issues_match", lambda output: output["issue_codes"])


def evidence_present(run: Any, example: Any) -> dict[str, Any]:
    del example
    present = bool(run.outputs.get("evidence_present"))
    return {
        "key": "evidence_present",
        "score": int(present),
        "comment": "Evidence attached" if present else "No evidence attached",
    }


def overall_exact_match(run: Any, example: Any) -> dict[str, Any]:
    expected = {
        key: example.outputs[key]
        for key in ("invoice", "issue_codes")
    }
    actual = {key: run.outputs.get(key) for key in expected}
    differences = _diff(expected, actual)
    return {
        "key": "overall_exact_match",
        "score": 0 if differences else 1,
        "comment": "\n".join(differences[:30]) if differences else "Exact match",
    }


def parity_match(
    inputs: list[dict[str, Any]], outputs: list[dict[str, Any]]
) -> dict[str, Any]:
    by_artifact = {
        source["artifact"]: output.get("invoice") for source, output in zip(inputs, outputs)
    }
    groups = (
        ("invoice_1011.txt", "invoice_1011.pdf"),
        ("invoice_1012.txt", "invoice_1012.pdf"),
        ("invoice_1013.json", "invoice_1013.pdf"),
    )
    fields = (
        "invoice_number", "vendor", "invoice_date", "due_date", "currency",
        "line_items", "declared_total",
    )
    failures: list[str] = []
    for left_name, right_name in groups:
        left_key = f"data/invoices/{left_name}"
        right_key = f"data/invoices/{right_name}"
        left = by_artifact.get(left_key)
        right = by_artifact.get(right_key)
        if left is None or right is None:
            failures.append(f"Missing parity output for {left_name}/{right_name}")
            continue
        differences = _diff(
            {field: left[field] for field in fields},
            {field: right[field] for field in fields},
            path=f"{left_name}<->{right_name}",
        )
        failures.extend(differences)
    return {
        "key": "representation_parity",
        "score": 0 if failures else 1,
        "comment": "\n".join(failures[:30]) if failures else "All parity pairs match",
    }


EVALUATORS = [
    invoice_fields_match,
    line_items_match,
    amounts_match,
    issues_match,
    evidence_present,
    overall_exact_match,
]


def _project_relative(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return None


def _manifest_indexes(examples: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_artifact = {example["inputs"]["artifact"]: example for example in examples}
    by_name: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for example in examples:
        name = Path(example["inputs"]["artifact"]).name
        if name in by_name:
            duplicates.add(name)
        by_name[name] = example
    for name in duplicates:
        by_name.pop(name, None)
    return by_artifact, by_name


def _find_example(path_or_name: str | Path, examples: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_artifact, by_name = _manifest_indexes(examples)
    path = Path(path_or_name)
    normalized = path.as_posix()
    return by_artifact.get(normalized) or by_name.get(path.name)


def _case_from_example(example: dict[str, Any]) -> dict[str, Any]:
    artifact = example["inputs"]["artifact"]
    return {
        "artifact": artifact,
        "path": PROJECT_ROOT / artifact,
        "expected": example["outputs"],
        "metadata": example.get("metadata", {}),
    }


def _case_from_path(path: str | Path, examples: list[dict[str, Any]]) -> dict[str, Any]:
    source = Path(path)
    if not source.is_absolute():
        source = PROJECT_ROOT / source
    source = source.resolve()
    relative = _project_relative(source)
    example = _find_example(relative or source.name, examples)
    if example is not None:
        case = _case_from_example(example)
        case["path"] = source
        return case
    return {
        "artifact": relative or str(source),
        "path": source,
        "expected": None,
        "metadata": {
            "format": source.suffix.lstrip(".").lower(),
            "scenario": "ad hoc execution",
        },
    }


def select_test_cases(
    *,
    settings: IngestionSettings,
    golden: bool = False,
    test_files: Iterable[str | Path] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    requested = list(test_files or [])
    if golden and requested:
        raise EvaluationConfigurationError("--golden cannot be combined with --test-file")
    examples = load_manifest()
    if golden:
        return "golden", [_case_from_example(example) for example in examples]
    if requested:
        return "specific", [_case_from_path(path, examples) for path in requested]

    cases: list[dict[str, Any]] = []
    for configured in settings.evaluation.smoke_cases:
        example = _find_example(configured, examples)
        if example is None:
            raise EvaluationConfigurationError(
                f"Configured smoke case is not in ingestion_golden.json: {configured}"
            )
        cases.append(_case_from_example(example))
    return "smoke", cases


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def _evaluation_scores(expected: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    run = SimpleNamespace(outputs=actual)
    example = SimpleNamespace(outputs=expected)
    return [evaluator(run, example) for evaluator in EVALUATORS]


def _aggregate_counters(results: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for result in results:
        counters = result.get("pipeline_counters") or {}
        for key, value in counters.items():
            totals[key] = totals.get(key, 0) + int(value or 0)
    return totals


def _score_percent(results: list[dict[str, Any]], key: str) -> int | None:
    scored = [
        score["score"]
        for result in results
        for score in result["evaluators"]
        if score["key"] == key
    ]
    if not scored:
        return None
    return round(sum(scored) * 100 / len(scored))


def _representation_parity_result(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    required_pairs = (
        ("data/invoices/invoice_1011.txt", "data/invoices/invoice_1011.pdf"),
        ("data/invoices/invoice_1012.txt", "data/invoices/invoice_1012.pdf"),
        ("data/invoices/invoice_1013.json", "data/invoices/invoice_1013.pdf"),
    )
    by_artifact = {result["artifact"]: result for result in results}
    selected_inputs: list[dict[str, Any]] = []
    selected_outputs: list[dict[str, Any]] = []
    for left, right in required_pairs:
        if left in by_artifact and right in by_artifact:
            for artifact in (left, right):
                selected_inputs.append({"artifact": artifact})
                selected_outputs.append(by_artifact[artifact]["actual"])
    if not selected_inputs:
        return None
    return parity_match(selected_inputs, selected_outputs)


def _status_label(result: dict[str, Any]) -> str:
    if result["expected"] is None:
        return "EXECUTION ONLY"
    return "PASS" if result["passed"] else "FAIL"


def _format_difference(score: dict[str, Any]) -> str:
    if score["score"]:
        return ""
    return score.get("comment", "")


def _print_terminal_report(summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    width = 50
    title = {
        "smoke": "INGESTION SMOKE TEST",
        "golden": "INGESTION GOLDEN EVALUATION",
        "specific": "INGESTION SPECIFIC FILE EVALUATION",
    }[summary["scope"]]
    print("=" * width)
    print(title)
    print("=" * width)
    print()
    if summary["scope"] == "golden":
        print(f"Artifacts evaluated:          {summary['cases']}")
        print(f"Exact matches:                {summary['exact_matches']} / {summary['evaluated_cases']}")
        for key, label in (
            ("invoice_fields_match", "Invoice fields"),
            ("line_items_match", "Line items"),
            ("amounts_match", "Amounts"),
            ("issues_match", "Issues"),
            ("evidence_present", "Evidence coverage"),
        ):
            percent = summary["score_percentages"].get(key)
            if percent is not None:
                print(f"{label + ':':30}{percent}%")
        if summary.get("representation_parity"):
            status = "PASS" if summary["representation_parity"]["score"] else "FAIL"
            print(f"{'Representation parity:':30}{status}")
        counters = summary["pipeline_counters"]
        print()
        print(f"Model calls:                  {counters.get('model_requests', 0)}")
        print(f"Critic calls:                 {counters.get('critic_runs', 0)}")
        print(f"Revisions:                    {counters.get('revisions', 0)}")
    else:
        print(f"Cases: {summary['cases']}")
        print()
        for index, result in enumerate(results, start=1):
            print(f"[{index}/{summary['cases']}] {Path(result['artifact']).name:<20} {_status_label(result)}")

    failures = [result for result in results if result["expected"] is not None and not result["passed"]]
    execution_only = [result for result in results if result["expected"] is None]
    if failures or execution_only:
        print()
    for result in failures:
        print("-" * width)
        print(Path(result["artifact"]).name)
        print()
        for score in result["evaluators"]:
            print(f"{score['key']:<30}{'PASS' if score['score'] else 'FAIL'}")
        first_failure = next((score for score in result["evaluators"] if not score["score"]), None)
        if result["issues"]:
            print(f"Issues: {', '.join(result['issues'])}")
        if first_failure:
            print()
            print("Difference:")
            print(_format_difference(first_failure))
        print("-" * width)
    for result in execution_only:
        print("-" * width)
        print(Path(result["artifact"]).name)
        print()
        print("EXECUTION ONLY")
        print("NO GOLDEN EXPECTATION AVAILABLE")
        print(f"Status: {result['ingestion_status']}")
        if result["issues"]:
            print(f"Issues: {', '.join(result['issues'])}")
        print("-" * width)
    print()
    print(f"Passed: {summary['passed_cases']} / {summary['evaluated_cases']}")
    print(f"Failed: {summary['failed_cases']}")
    print()
    print(f"OVERALL: {summary['overall_status']}")
    print("=" * width)


def run_local_evaluation(
    *,
    golden: bool = False,
    test_files: Iterable[str | Path] | None = None,
    trace_langsmith: bool = False,
    settings: IngestionSettings | None = None,
    evaluation_root: Path | None = None,
    pipeline_runner: Callable[..., Any] | None = None,
    print_report: bool = True,
) -> dict[str, Any]:
    settings = settings or load_settings()
    scope, cases = select_test_cases(settings=settings, golden=golden, test_files=test_files)
    evaluation_id = uuid4().hex
    started_at = datetime.now().astimezone()
    timestamp = started_at.astimezone(timezone.utc).isoformat()
    root = Path(evaluation_root or DEFAULT_EVALUATION_ROOT) / _evaluation_directory_name(
        started_at, evaluation_id
    )
    runs_dir = root / "runs"
    runner = pipeline_runner or ingest
    paths = [case["path"] for case in cases]
    metadata_by_path = {
        str(case["path"].resolve()): {
            "evaluation_id": evaluation_id,
            "invoice_id": case["metadata"].get("invoice_id"),
            "test_scope": scope,
            "scenario": case["metadata"].get("scenario"),
            "pipeline_version": "ingestion-v1",
            "git_commit": _git_commit(),
        }
        for case in cases
    }
    try:
        batch = runner(
            paths,
            settings=settings,
            runs_dir=runs_dir,
            trace_langsmith=trace_langsmith,
            trace_metadata={
                "evaluation_id": evaluation_id,
                "test_scope": scope,
                "pipeline_version": "ingestion-v1",
                "git_commit": _git_commit(),
            },
            trace_metadata_by_path=metadata_by_path,
            trace_tags=["test", scope],
        )
    except TypeError:
        batch = runner(paths)
    except Exception as exc:
        raise EvaluationExecutionError(str(exc)) from exc

    if len(batch.results) != len(cases):
        raise EvaluationExecutionError(
            f"Pipeline returned {len(batch.results)} results for {len(cases)} test cases"
        )

    results: list[dict[str, Any]] = []
    for case, item in zip(cases, batch.results):
        actual = project_result(item.result)
        expected = case["expected"]
        evaluators = _evaluation_scores(expected, actual) if expected is not None else []
        passed = all(score["score"] == 1 for score in evaluators) if evaluators else None
        results.append(
            {
                "artifact": case["artifact"],
                "source_path": str(case["path"]),
                "expected": expected,
                "actual": actual,
                "evaluators": evaluators,
                "passed": passed,
                "execution_only": expected is None,
                "ingestion_status": item.result.status,
                "issues": _issue_codes(item.result),
                "pipeline_counters": item.result.counters.model_dump(),
                "run_id": item.result.run_id,
                "artifact_path": item.artifact,
                "metadata": case["metadata"],
            }
        )

    parity = _representation_parity_result(results)
    if parity is not None and parity["score"] == 0:
        for result in results:
            if result["expected"] is not None:
                result["passed"] = False

    evaluated = [result for result in results if result["expected"] is not None]
    execution_only = [result for result in results if result["expected"] is None]
    failed = [result for result in evaluated if not result["passed"]]
    technical_execution_failures = [
        result for result in execution_only if result["ingestion_status"] == "technical_failure"
    ]
    overall_status = "PASS"
    exit_code = 0
    if technical_execution_failures:
        overall_status = "ERROR"
        exit_code = 2
    elif failed:
        overall_status = "FAIL"
        exit_code = 1
    summary = {
        "evaluation_id": evaluation_id,
        "timestamp": timestamp,
        "scope": scope,
        "trace_langsmith": trace_langsmith,
        "cases": len(results),
        "evaluated_cases": len(evaluated),
        "execution_only_cases": len(execution_only),
        "passed_cases": sum(1 for result in evaluated if result["passed"]),
        "failed_cases": len(failed),
        "exact_matches": sum(
            1
            for result in evaluated
            for score in result["evaluators"]
            if score["key"] == "overall_exact_match" and score["score"] == 1
        ),
        "score_percentages": {
            key: _score_percent(results, key)
            for key in [score.__name__ for score in EVALUATORS]
        },
        "representation_parity": parity,
        "pipeline_counters": _aggregate_counters(results),
        "tested_files": [result["artifact"] for result in results],
        "overall_status": overall_status,
        "exit_code": exit_code,
        "report_directory": str(root),
    }
    report = {"summary": summary, "results": results}
    atomic_json(root / "summary.json", summary)
    atomic_json(root / "results.json", results)
    if print_report:
        _print_terminal_report(summary, results)
    return report


def run_evaluation(*, sync: bool = True, experiment_prefix: str = "ingestion") -> Any:
    load_dotenv(WORKSPACE_ROOT / ".env")
    if not os.getenv("LANGSMITH_API_KEY") and os.getenv("langsmith_API"):
        os.environ["LANGSMITH_API_KEY"] = os.environ["langsmith_API"]
    client = Client()
    examples = load_manifest()
    if sync:
        sync_dataset(client, examples)
    return client.evaluate(
        ingestion_target,
        data=DATASET_NAME,
        evaluators=EVALUATORS,
        summary_evaluators=[parity_match],
        experiment_prefix=experiment_prefix,
        blocking=True,
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync and evaluate the Galatiq ingestion golden dataset."
    )
    parser.add_argument("--no-sync", action="store_true")
    parser.add_argument("--sync-only", action="store_true")
    parser.add_argument("--experiment-prefix", default="ingestion")
    args = parser.parse_args(list(argv) if argv is not None else None)
    load_dotenv(WORKSPACE_ROOT / ".env")
    if not os.getenv("LANGSMITH_API_KEY") and os.getenv("langsmith_API"):
        os.environ["LANGSMITH_API_KEY"] = os.environ["langsmith_API"]
    if not os.getenv("LANGSMITH_API_KEY"):
        parser.error("LANGSMITH_API_KEY is required")
    if args.sync_only:
        dataset_id = sync_dataset(Client(), load_manifest())
        print(json.dumps({"dataset": DATASET_NAME, "dataset_id": dataset_id}, indent=2))
        return 0
    results = run_evaluation(
        sync=not args.no_sync, experiment_prefix=args.experiment_prefix
    )
    print(f"LangSmith experiment: {results.experiment_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
