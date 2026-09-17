"""LangSmith golden-dataset synchronization and ingestion evaluation."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv
from langsmith import Client

from .workflow import run_pipeline


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = PROJECT_ROOT.parent
MANIFEST_PATH = Path(__file__).with_name("evals") / "ingestion_golden.json"
DATASET_NAME = "galatiq-ingestion-golden-v1"


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
    return _canonical(getattr(field, "value", field))


def _observed_literal(field: Any) -> Any:
    observed = getattr(field, "observed", None)
    return getattr(observed, "literal", None)


def project_result(result: Any) -> dict[str, Any]:
    """Project rich or compact ingestion results onto the golden contract."""
    invoice = getattr(result, "invoice", None)
    if invoice is None:
        return {
            "invoice": None,
            "issue_codes": sorted(_issue_codes(result)),
            "transformations": [],
            "evidence_present": False,
        }
    if hasattr(invoice.invoice_number, "value"):
        items = []
        for row in invoice.line_items:
            items.append(
                {
                    "source_name": _observed_literal(row.name),
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
        transformations = _rich_transformations(invoice)
        evidence_present = _rich_evidence_present(invoice)
    else:
        invoice_projection = invoice.model_dump(mode="json")
        transformations = [
            {
                "field": item.field,
                "source": item.source,
                "normalized": item.normalized,
            }
            for item in getattr(result, "transformations", [])
        ]
        evidence_present = bool(getattr(result, "evidence", []))
    return {
        "invoice": _canonical(invoice_projection),
        "issue_codes": sorted(_issue_codes(result)),
        "transformations": transformations,
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


def _rich_transformations(invoice: Any) -> list[dict[str, str]]:
    transformations: list[dict[str, str]] = []

    def visit(field: Any, path: str) -> None:
        source = _observed_literal(field)
        normalized = _normalized_value(field)
        meaningful_rules = {
            "ocr_money_O_to_0", "ocr_date_O_to_0", "product_alias",
            "product_description_suffix", "invoice_identifier_format",
        }
        if field.applied_rule in meaningful_rules and source is not None and normalized is not None and str(source) != str(normalized):
            transformations.append(
                {"field": path, "source": str(source), "normalized": str(normalized)}
            )

    for name in type(invoice).model_fields:
        if name != "line_items":
            visit(getattr(invoice, name), name)
    for row in invoice.line_items:
        for name in type(row).model_fields:
            path = "line_items.normalized_name" if name == "name" else f"line_items.{name}"
            visit(getattr(row, name), path)
    return transformations


def _rich_evidence_present(invoice: Any) -> bool:
    fields: list[Any] = []
    for name in type(invoice).model_fields:
        if name == "line_items":
            for row in invoice.line_items:
                fields.extend(getattr(row, child) for child in type(row).model_fields)
        else:
            fields.append(getattr(invoice, name))
    populated = [field for field in fields if _normalized_value(field) is not None]
    return bool(populated) and all(field.observed.evidence for field in populated)


def ingestion_target(inputs: dict[str, Any]) -> dict[str, Any]:
    source = (PROJECT_ROOT / inputs["artifact"]).resolve()
    with tempfile.TemporaryDirectory(prefix="galatiq-eval-") as temporary:
        batch = run_pipeline([source], runs_dir=Path(temporary))
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


def transformations_match(run: Any, example: Any) -> dict[str, Any]:
    return _score(
        run, example, "transformations_match", lambda output: output["transformations"]
    )


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
        for key in ("invoice", "issue_codes", "transformations")
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
    transformations_match,
    evidence_present,
    overall_exact_match,
]


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
