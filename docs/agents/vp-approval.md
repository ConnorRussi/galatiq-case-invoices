# VP Approval Agent

## Purpose

The VP Agent handles the approval graph's escalation branch. It returns `GO`, `NO_GO`, or `HUMAN_REVIEW_REQUIRED` for a validated and reconciled invoice.

## Explicit Non-Responsibilities

It is not a second semantic, arithmetic, or inventory validator. It does not rewrite data, query databases, or authorize an external bank transfer.

## Inputs And Outputs

Input is the same `ApprovalRequest` plus the `BusinessRuleDecision`, including escalation reason, triggered rules, concerns, source, and upstream results. Output is `VPDecision`; approval combines it into `ApprovalResult` with `decision_source=VP_AGENT`.

## Processing Flow

The graph invokes VP only after Business Rule returns `VP_REVIEW`. `GO` completes as approved, `NO_GO` completes as rejected, and human review completes as a terminal workflow stop. When invoice history marks a paid prior version, code overwrites any model `GO` with `HUMAN_REVIEW_REQUIRED` and explains that adjustment, credit, refund, or replacement payment needs a human.

## Critic / Revision Loop

There is no VP critic loop. Provider/schema failure raises through approval and becomes workflow `TECHNICAL_FAILURE`.

## Handoff Contract

Only `GO` permits payment. `NO_GO` and `HUMAN_REVIEW_REQUIRED` never call payment. A human-review result is not an executable approval because this repository has no decision-submission or resume service.

## Relevant Source Files

[`agents.py`](../../src/invoice_system/approval/agents.py), [`graph.py`](../../src/invoice_system/approval/graph.py), [`policy.md`](../../src/invoice_system/approval/policy.md), and [`test_approval.py`](../../tests/test_approval.py).
