"""Bounded per-document LangGraph ingestion with an explicit validation handoff."""
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from pydantic import ValidationError

from .models import BatchItemResult, BatchResult, Critique, IngestionResult, InvoiceProposal, Issue, WorkflowState
from .artifacts import append_event, atomic_json
from .config import IngestionSettings, load_settings
from .extraction import InvalidInput, extract, read_source
from .normalization import normalize
from .providers import GeminiProvider, GrokProvider, IngestionModelProvider, ModelContext, ProviderUnavailable, TransportFailure

DEFAULT_RUNS = Path(__file__).with_name("runs")


class DocumentRun:
    def __init__(self, state, settings, provider, directory):
        self.latest = state
        self.settings = settings
        self.provider = provider
        self.directory = directory
        self.pdf = b""  # Never part of graph state, artifacts, or tracing.

    def issue(self, state, code, message):
        if not any(i.code == code for i in state.issues):
            state.issues.append(Issue(code=code, message=message))

    def wrap(self, name, fn):
        def node(state: WorkflowState):
            self.latest = state
            state.counters.graph_steps += 1
            start = perf_counter()
            fn(state)
            if name == "intake":
                state.next_node = self.allow(state, "model")
            elif name == "model":
                state.next_node = self.after_model(state)
            elif name == "normalize":
                state.next_node = self.after_normalize(state)
            append_event(self.directory, node=name, counters=state.counters,
                         latency_ms=round((perf_counter() - start) * 1000), outcome=state.last_outcome or "completed")
            return {key: getattr(state, key) for key in type(state).model_fields}
        return node

    def intake(self, state):
        try:
            state.source, self.pdf = read_source(state.path, self.settings.documents)
            atomic_json(self.directory / "source.json", state.source)
            state.extraction = extract(state.source, self.pdf, self.settings.documents)
            atomic_json(self.directory / "extraction.json", state.extraction)
            state.visual = not state.extraction.usable_text
            state.last_outcome = "visual_route" if state.visual else "text_route"
        except InvalidInput:
            state.status = "invalid_input"
            self.issue(state, "INVALID_INPUT", "Source is not an accessible supported invoice within configured limits")
            state.last_outcome = "invalid_input"

    def model(self, state):
        limits = self.settings.limits
        counters = state.counters
        operation = state.operation
        retrying = state.last_outcome == "retry_transport"
        if not retrying:
            counters.transport_retries = 0
            attr = {"interpret": "interpret_attempts", "critique": "critic_runs", "revise": "revisions", "pro": "pro_escalations"}[operation]
            setattr(counters, attr, getattr(counters, attr) + 1)
        context = ModelContext(state.extraction, self.pdf, state.proposal, state.candidate,
                               state.critique, adjudicate=operation == "pro", visual=state.visual or operation == "pro")
        method = {"interpret": "interpret_visual" if state.visual else "interpret_text",
                  "critique": "critique", "revise": "revise", "pro": "interpret_visual"}[operation]
        schema = Critique if operation == "critique" else InvoiceProposal
        model_name = self.settings.models.pro_model if operation == "pro" else self.settings.models.flash_model
        usage = {}
        start = perf_counter()
        try:
            # Initialize lazily: invalid input is classified without an API key.
            if self.provider is None:
                self.provider = GeminiProvider(self.settings) if self.settings.models.provider == "gemini" else GrokProvider()
            counters.model_requests += 1
            response = getattr(self.provider, method)(context)
            usage = response.usage
            value = schema.model_validate_json(response.payload) if isinstance(response.payload, str) else schema.model_validate(response.payload)
            atomic_json(self.directory / f"{operation}-{counters.model_requests}.json", value)
            if operation == "critique":
                state.critique = value
            else:
                state.proposal = value
                if operation == "pro":
                    state.visual = True
            state.last_outcome = "success"
        except ValidationError:
            state.last_outcome = "malformed_schema"
            self.issue(state, "MALFORMED_MODEL_RESPONSE", "Model response did not satisfy the proposal contract")
        except (TransportFailure, TimeoutError):
            if operation != "pro" and counters.transport_retries < limits.max_transport_retries_per_call:
                counters.transport_retries += 1
                state.last_outcome = "retry_transport"
            else:
                state.status = "technical_failure"
                state.last_outcome = "provider_failure"
                self.issue(state, "PROVIDER_FAILURE", "Provider transport failed after bounded attempts")
        except ProviderUnavailable:
            state.status = "technical_failure"
            state.last_outcome = "provider_failure"
            self.issue(state, "PROVIDER_UNAVAILABLE", "Provider unavailable; verify configuration and GEMINI_API_KEY")
        finally:
            append_event(self.directory, node=operation, counters=counters, model=model_name,
                         usage=usage, latency_ms=round((perf_counter() - start) * 1000), outcome=state.last_outcome)

    def normalize(self, state):
        state.candidate, state.normalization_issues = normalize(state.proposal, state.extraction, visual=state.visual)
        state.last_outcome = "normalized"

    def gate(self, state):
        # Recheck every populated field, including a proposal received at the step limit.
        if state.proposal is not None:
            state.candidate, state.normalization_issues = normalize(state.proposal, state.extraction, visual=state.visual)
        issues = state.issues + state.normalization_issues
        if state.critique:
            issues += state.critique.issues
        if state.critique and state.critique.decision != "accept":
            if state.counters.pro_escalations == 0 or state.last_outcome not in {"normalized", "success"}:
                issues.append(Issue(code="UNRESOLVED_CRITIQUE", message="Critic concerns remain for downstream validation"))
        candidate = state.candidate
        populated = candidate is not None and (
            any(getattr(candidate, key).value is not None for key in type(candidate).model_fields if key != "line_items")
            or any(getattr(row, key).value is not None for row in candidate.line_items for key in type(row).model_fields))
        status = state.status or ("ready_for_validation" if populated else "needs_review")
        if state.proposal and state.proposal.recommend_review and not state.status:
            status = "needs_review"
            issues.append(Issue(code="MODEL_RECOMMENDED_REVIEW", message="Final proposal recommends human review"))
        state.result = IngestionResult(run_id=state.run_id, status=status, source=state.source,
            invoice=candidate, issues=issues, counters=state.counters.model_copy(deep=True))
        state.last_outcome = status

    def persist(self, state):
        atomic_json(self.directory / "source.json", state.source)
        atomic_json(self.directory / "extraction.json", state.extraction)
        state.result.counters = state.counters.model_copy(deep=True)
        atomic_json(self.directory / "result.json", state.result)

    def allow(self, state, next_node):
        if next_node == "gate" or state.status:
            return "gate"
        limits = self.settings.limits
        if state.counters.graph_steps >= limits.max_graph_steps - 2:
            self.issue(state, "INGESTION_BUDGET_EXHAUSTED", "Graph step budget exhausted")
            return "gate"
        if next_node == "model" and state.counters.model_requests >= limits.max_total_model_requests:
            self.issue(state, "INGESTION_BUDGET_EXHAUSTED", "Model request budget exhausted")
            return "gate"
        return next_node

    def escalate(self, state):
        if state.counters.pro_escalations < self.settings.limits.max_pro_escalations:
            state.operation = "pro"
            return self.allow(state, "model")
        self.issue(state, "UNRESOLVED_INTERPRETATION", "No further adjudication is available")
        return "gate"

    def after_model(self, state):
        if state.status:
            return "gate"
        if state.operation == "pro":
            return self.allow(state, "normalize") if state.last_outcome == "success" else "gate"
        if state.last_outcome == "retry_transport":
            return self.allow(state, "model")
        if state.last_outcome == "malformed_schema":
            if state.operation == "interpret" and state.counters.interpret_attempts < self.settings.limits.max_interpret_attempts:
                return self.allow(state, "model")
            return self.escalate(state)
        if state.operation in {"interpret", "revise"}:
            return self.allow(state, "normalize")
        if state.critique.decision == "accept":
            return "gate"
        if (state.critique.decision == "revise" and state.counters.revisions < self.settings.limits.max_flash_revisions
                and state.counters.critic_runs < self.settings.limits.max_flash_critic_runs):
            state.operation = "revise"
            return self.allow(state, "model")
        return self.escalate(state)

    def after_normalize(self, state):
        if state.operation == "pro":
            return "gate"
        if state.counters.critic_runs >= self.settings.limits.max_flash_critic_runs:
            return self.escalate(state)
        state.operation = "critique"
        return self.allow(state, "model")

    def build_graph(self):
        graph = StateGraph(WorkflowState)
        for name in ("intake", "model", "normalize", "gate", "persist"):
            graph.add_node(name, self.wrap(name, getattr(self, name)))
        graph.add_edge(START, "intake")
        graph.add_conditional_edges("intake", lambda s: s.next_node, ["model", "gate"])
        graph.add_conditional_edges("model", lambda s: s.next_node, ["model", "normalize", "gate"])
        graph.add_conditional_edges("normalize", lambda s: s.next_node, ["model", "gate"])
        graph.add_edge("gate", "persist")
        graph.add_edge("persist", END)
        return graph.compile()


def run_pipeline(paths, *, settings: IngestionSettings | None = None,
                 provider: IngestionModelProvider | None = None, runs_dir: Path | None = None) -> BatchResult:
    settings = settings or load_settings()
    results = []
    for path in paths:
        state = WorkflowState(run_id=uuid4().hex, path=Path(path))
        directory = Path(runs_dir or DEFAULT_RUNS) / state.run_id
        run = DocumentRun(state, settings, provider, directory)
        artifact = str(directory / "result.json")
        try:
            # Prevent ambient LangSmith settings from exporting source data or prompts.
            with tracing_context(enabled=False):
                final = run.build_graph().invoke(state, {"recursion_limit": settings.limits.max_graph_steps + 1})
            result = final["result"]
        except Exception:
            state = run.latest
            result = IngestionResult(run_id=state.run_id, status="technical_failure", source=state.source,
                invoice=state.candidate, counters=state.counters,
                issues=state.issues + state.normalization_issues + [Issue(code="TECHNICAL_FAILURE", message="Ingestion code or artifact storage failed")])
            try:
                append_event(directory, node="failure", counters=state.counters, outcome="technical_failure")
                atomic_json(directory / "result.json", result)
            except Exception:
                artifact = None
        finally:
            if provider is None and isinstance(run.provider, GeminiProvider):
                try:
                    run.provider.close()
                except Exception:
                    result.status = "technical_failure"
                    result.issues.append(Issue(code="PROVIDER_CLEANUP_FAILURE", message="Provider resource cleanup failed"))
                    try:
                        atomic_json(directory / "result.json", result)
                    except Exception:
                        artifact = None
        results.append(BatchItemResult(artifact=artifact, result=result))
    return BatchResult(status="completed" if all(r.result.status == "ready_for_validation" for r in results)
                       else "completed_with_errors", results=results)
