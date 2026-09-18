"""Single-pass ingestion proof of concept."""
from pathlib import Path
from time import perf_counter
from typing import Iterable
from uuid import uuid4

from pydantic import ValidationError

from . import artifacts
from .config import IngestionSettings, load_settings
from .extraction import InvalidInput, extract, read_source
from .models import BatchItemResult, BatchResult, IngestionResult, Issue, Invoice
from .providers import IngestionModelProvider, ModelContext, ProviderUnavailable, RateLimitFailure, TamuAIProvider, TransportFailure

DEFAULT_RUNS = Path(__file__).with_name("runs")


def ingest(paths: Iterable[str | Path], *, settings: IngestionSettings | None = None, provider: IngestionModelProvider | None = None, runs_dir: Path | None = None, **_ignored) -> BatchResult:
    """Extract each supported source once; failures remain isolated to that source."""
    settings = settings or load_settings()
    results = [_ingest_one(Path(path), settings, provider, runs_dir) for path in paths]
    return BatchResult(status="completed" if all(item.result.status == "ready_for_validation" for item in results) else "completed_with_errors", results=results)


def _ingest_one(path: Path, settings: IngestionSettings, provider: IngestionModelProvider | None, runs_dir: Path | None) -> BatchItemResult:
    run_id, source, invoice, issues = uuid4().hex, None, None, []
    directory, active_provider, status = Path(runs_dir or DEFAULT_RUNS) / run_id, provider, "technical_failure"
    artifact = str(directory / "result.json")
    try:
        source, payload = read_source(path, settings.documents)
        document = extract(source, payload, settings.documents)
        artifacts.atomic_json(directory / "source.json", source)
        artifacts.atomic_json(directory / "extraction.json", document)
        artifacts.atomic_text(directory / "extracted-text.txt", document.text + "\n")
        artifacts.append_event(directory, stage="intake", outcome="success", message="Read source and extracted native text", details={"format": source.path.suffix.lower(), "characters": len(document.text), "blocks": sum(len(page.blocks) for page in document.pages)})

        active_provider = active_provider or TamuAIProvider(settings)
        start = perf_counter()
        response = active_provider.interpret_text(ModelContext(document=document))
        invoice = Invoice.model_validate_json(response.payload) if isinstance(response.payload, str) else Invoice.model_validate(response.payload)
        artifacts.atomic_json(directory / "model-response.json", invoice)
        artifacts.append_event(directory, stage="model extraction", outcome="success", message="One structured extraction response passed the Invoice schema", details={"latency_ms": round((perf_counter() - start) * 1000), "usage": response.usage})

        populated = any(getattr(invoice, name).normalized is not None for name in type(invoice).model_fields if name != "line_items") or bool(invoice.line_items)
        if populated:
            status = "ready_for_validation"
            artifacts.append_event(directory, stage="schema gate", outcome="success", message="A typed extraction handoff is available; no business validation was performed")
        else:
            status = "needs_review"
            issues.append(Issue(code="EMPTY_EXTRACTION", message="The response matched the schema but contained no invoice values"))
            artifacts.append_event(directory, stage="schema gate", outcome="failed", message="The response contained no invoice values")
    except InvalidInput as exc:
        status = "invalid_input"
        issues.append(Issue(code="INVALID_INPUT", message=str(exc)))
        artifacts.append_event(directory, stage="intake", outcome="failed", message=str(exc))
    except ValidationError:
        status = "needs_review"
        issues.append(Issue(code="MALFORMED_MODEL_RESPONSE", message="The one model response did not match the Invoice schema"))
        artifacts.append_event(directory, stage="schema gate", outcome="failed", message="The model response did not match the Invoice schema")
    except RateLimitFailure:
        issues.append(Issue(code="PROVIDER_RATE_LIMITED", message="The provider rejected the one extraction request due to rate limits"))
        artifacts.append_event(directory, stage="model extraction", outcome="failed", message="Provider rate limit reached; no retry was attempted")
    except (TransportFailure, ProviderUnavailable) as exc:
        issues.append(Issue(code="PROVIDER_FAILURE", message=str(exc)))
        artifacts.append_event(directory, stage="model extraction", outcome="failed", message=f"Provider failed; no retry was attempted ({type(exc).__name__})")
    except Exception as exc:
        issues.append(Issue(code="TECHNICAL_FAILURE", message="Ingestion failed while writing an artifact or handling a response"))
        artifacts.append_event(directory, stage="ingestion", outcome="failed", message=f"Unexpected {type(exc).__name__}; inspect the event stream")
    finally:
        result = IngestionResult(run_id=run_id, status=status, source=source, invoice=invoice, issues=issues)
        try:
            artifacts.atomic_json(directory / "result.json", result)
            artifacts.write_human_report(directory, result)
        except Exception:
            artifact = None
        if provider is None and active_provider is not None:
            try:
                active_provider.close()
            except Exception:
                pass
    return BatchItemResult(artifact=artifact, result=result)


run_pipeline = ingest
