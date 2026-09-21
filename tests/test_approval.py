import json
from pathlib import Path
import shutil

import pytest

from invoice_system.approval import agents
from invoice_system.approval import graph as approval_graph
from invoice_system.approval import runner as approval_runner
from invoice_system.approval.evaluation import run_approval_evaluation
from invoice_system.approval.models import ApprovalRequest, BusinessRuleDecision, VPDecision
from invoice_system.approval.runner import run_approval
from invoice_system.ingestion.run_logging import RunContext


ROOT = Path(__file__).resolve().parents[1]


def _request(invoice_id: str = "approval-test") -> ApprovalRequest:
    request = ApprovalRequest.model_validate({
        "invoice_id": invoice_id,
        "normalization": {
            "invoice": {
                "invoice_number": "TEST-1",
                "vendor": "Test Vendor",
                "currency": "USD",
                "items": [],
                "invoice_total": 12000,
                "amount_due": 12000,
            },
            "evidence": [],
        },
        "validation_result": {"status": "VALID"},
        "reconciliation_result": {"status": "PASS"},
    })
    assert request.validation_result.status == "VALID"
    assert request.reconciliation_result.status == "PASS"
    return request


def test_direct_accept_finishes_in_business_rule_bucket(monkeypatch):
    calls = []
    messages = []

    def fake_invoke(**kwargs):
        calls.append(kwargs["output_model"])
        return BusinessRuleDecision(
            decision="ACCEPT",
            reasoning="Below threshold with standard terms.",
        )

    monkeypatch.setattr(agents, "invoke_structured", fake_invoke)
    result = run_approval(
        _request(),
        persist_artifacts=False,
        progress_callback=messages.append,
    )

    assert result.final_status == "APPROVED"
    assert result.decision_source == "BUSINESS_RULE_AGENT"
    assert result.vp_decision is None
    assert calls == [BusinessRuleDecision]
    assert messages == [
        "[3/4] Business rule decision: ACCEPT",
        "[3/4] VP review required: NO",
    ]


def test_approval_graph_failure_writes_error_artifact(tmp_path, monkeypatch):
    class FailingGraph:
        def stream(self, state, stream_mode):
            raise RuntimeError("approval provider unavailable")

    monkeypatch.setattr(approval_runner, "build_graph", lambda: FailingGraph())
    context = RunContext("approval-failure", tmp_path / "approval")

    with pytest.raises(RuntimeError, match="Approval graph failed"):
        run_approval(_request(), artifact_context=context)

    assert (context.run_dir / "approval_error.json").exists()


def test_approval_appends_to_shared_run_without_overwriting_run_metadata(tmp_path, monkeypatch):
    context = RunContext("shared-run", tmp_path / "run")
    context.run_dir.mkdir()
    (context.run_dir / "run.json").write_text('{"owner": "ingestion"}\n', encoding="utf-8")
    monkeypatch.setattr(
        agents,
        "invoke_structured",
        lambda **kwargs: BusinessRuleDecision(decision="ACCEPT", reasoning="Accept."),
    )

    result = run_approval(_request(), artifact_context=context)

    assert result.final_status == "APPROVED"
    assert json.loads((context.run_dir / "run.json").read_text()) == {"owner": "ingestion"}
    assert (context.run_dir / "approval_context.json").exists()
    assert (context.run_dir / "approval_result.json").exists()


def test_direct_reject_finishes_in_business_rule_bucket_without_vp(monkeypatch):
    calls = []

    def fake_invoke(**kwargs):
        calls.append(kwargs["output_model"])
        return BusinessRuleDecision(
            decision="REJECT",
            triggered_rules=["unresolved unsafe payment concern"],
            reasoning="The beneficiary is unverified and payment is unsupported.",
        )

    monkeypatch.setattr(agents, "invoke_structured", fake_invoke)
    result = run_approval(_request(), persist_artifacts=False)

    assert result.final_status == "REJECTED"
    assert result.decision_source == "BUSINESS_RULE_AGENT"
    assert result.vp_decision is None
    assert calls == [BusinessRuleDecision]


def test_validation_denied_blocks_approval_before_either_agent(monkeypatch):
    request = _request()
    request.validation_result = {"status": "DENIED"}
    calls = []

    monkeypatch.setattr(
        approval_graph,
        "business_rule_agent",
        lambda request: calls.append("business_rule"),
    )
    monkeypatch.setattr(
        approval_graph,
        "vp_agent",
        lambda request, decision: calls.append("vp"),
    )

    with pytest.raises(ValueError, match="validation status VALID"):
        run_approval(request, persist_artifacts=False)

    assert request.validation_result == {"status": "DENIED"}
    assert calls == []


def test_vp_go_finishes_approved_in_vp_bucket(monkeypatch):
    messages = []

    def fake_invoke(**kwargs):
        if kwargs["output_model"] is BusinessRuleDecision:
            return BusinessRuleDecision(
                decision="VP_REVIEW",
                triggered_rules=["amount threshold"],
                reasoning="Amount requires VP review.",
            )
        return VPDecision(decision="GO", reasoning="Approved after review.")

    monkeypatch.setattr(agents, "invoke_structured", fake_invoke)
    result = run_approval(
        _request(),
        persist_artifacts=False,
        progress_callback=messages.append,
    )

    assert result.final_status == "APPROVED"
    assert result.decision_source == "VP_AGENT"
    assert result.vp_decision is not None
    assert result.vp_decision.decision == "GO"
    assert messages[-1] == "[3/4] VP decision: GO"


def test_vp_no_go_finishes_rejected_in_vp_bucket(monkeypatch):
    def fake_invoke(**kwargs):
        if kwargs["output_model"] is BusinessRuleDecision:
            return BusinessRuleDecision(
                decision="VP_REVIEW",
                triggered_rules=["amount threshold"],
                reasoning="Amount requires VP review.",
            )
        return VPDecision(decision="NO_GO", reasoning="Do not authorize.")

    monkeypatch.setattr(agents, "invoke_structured", fake_invoke)
    result = run_approval(_request(), persist_artifacts=False)

    assert result.final_status == "REJECTED"
    assert result.decision_source == "VP_AGENT"
    assert result.vp_decision is not None
    assert result.vp_decision.decision == "NO_GO"


def test_vp_invocation_is_logged_before_vp_decision(tmp_path, monkeypatch):
    def fake_invoke(**kwargs):
        if kwargs["output_model"] is BusinessRuleDecision:
            return BusinessRuleDecision(decision="VP_REVIEW", reasoning="Escalate.")
        return VPDecision(decision="GO", reasoning="Authorize.")

    monkeypatch.setattr(agents, "invoke_structured", fake_invoke)
    context = RunContext("vp-audit", tmp_path / "approval")
    run_approval(_request(), artifact_context=context)

    events = [
        json.loads(line)
        for line in (context.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    vp_events = [event for event in events if event["stage"] == "vp_agent"]
    assert [event["event"] for event in vp_events] == ["invoked", "decision"]


def test_approval_does_not_pass_cross_provider_model_overrides(monkeypatch):
    calls = []

    def fake_invoke(**kwargs):
        calls.append(kwargs)
        if kwargs["output_model"] is BusinessRuleDecision:
            return BusinessRuleDecision(decision="VP_REVIEW", reasoning="Escalate.")
        return VPDecision(decision="GO", reasoning="Authorize.")

    monkeypatch.setenv("LLM_PROVIDER", "tamu")
    monkeypatch.setenv("TAMUS_AI_CHAT_MODEL", "tamu-model")
    monkeypatch.setenv("XAI_MODEL", "must-not-be-used")
    monkeypatch.setenv("VP_REASONING_MODEL", "strong-reasoning-model")
    monkeypatch.setenv("VP_MODEL", "legacy-vp-model")
    monkeypatch.setenv("BUSINESS_RULE_MODEL", "business-model")
    monkeypatch.setattr(agents, "invoke_structured", fake_invoke)
    run_approval(_request(), persist_artifacts=False)

    assert len(calls) == 2
    assert all("model" not in call for call in calls)


def test_approval_evaluation_scores_final_buckets_without_live_model(tmp_path, monkeypatch):
    case_dir = tmp_path / "evals" / "approval" / "cases"
    case_dir.mkdir(parents=True)
    source_dir = ROOT / "evals" / "approval" / "cases"
    for source in source_dir.glob("*.json"):
        shutil.copy2(source, case_dir / source.name)

    def fake_invoke(**kwargs):
        request = json.loads(kwargs["content"])
        invoice_id = request["invoice_id"]
        if kwargs["output_model"] is BusinessRuleDecision:
            if invoice_id == "approval_under_threshold_accept":
                return BusinessRuleDecision(decision="ACCEPT", reasoning="Accept.")
            if invoice_id == "approval_direct_policy_reject":
                return BusinessRuleDecision(decision="REJECT", reasoning="Reject.")
            return BusinessRuleDecision(decision="VP_REVIEW", reasoning="Escalate.")
        if invoice_id == "approval_over_threshold_vp_go":
            return VPDecision(decision="GO", reasoning="Authorize.")
        return VPDecision(decision="NO_GO", reasoning="Reject.")

    monkeypatch.setattr(agents, "invoke_structured", fake_invoke)
    assert run_approval_evaluation(tmp_path)

    summaries = list((tmp_path / "logs" / "evals").glob("*/approval/summary.json"))
    assert len(summaries) == 1
    summary = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert summary["failed_cases"] == []
    assert summary["metrics"]["final_status_match"] == "5/5"
    assert summary["metrics"]["vp_route_match"] == "5/5"
