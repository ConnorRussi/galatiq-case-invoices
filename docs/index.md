# Documentation Index

Start with the [reviewer guide](README.md). It is the canonical overview for someone who has not seen the repository. This index routes readers through the maintained topic hierarchy.

## Current System

The normal CLI path is:

```text
main.py
  -> workflow.run_invoice_workflow
       -> ingestion.run_ingestion
       -> InvoiceLedger.register
       -> validation.run_validation(full graph)
       -> approval.run_approval
       -> payment.run_payment(mock provider)
       -> WorkflowResult and shared artifacts
```

The code and tests are the source of truth. These pages explain the current implementation without creating a second specification.

## Documentation Map

| Area | Pages |
| --- | --- |
| Architecture | [Overview](architecture/overview.md), [pipeline](architecture/pipeline.md), [contracts](architecture/agent-contracts.md), [models](architecture/data-models.md), [state flow](architecture/state-and-data-flow.md), [design decisions](architecture/design-decisions.md) |
| Agents | [Ingestion](agents/ingestion.md), [Validation](agents/validation.md), [Business Rules](agents/business-rules.md), [VP Approval](agents/vp-approval.md), [Decision routing](agents/decision.md), [Invoice history](agents/invoice-history.md), [Payment](agents/payment.md), [Dashboard](agents/dashboard.md) |
| Evaluation | [Overview](evaluation/overview.md), [Ingestion](evaluation/ingestion-eval.md), [Validation](evaluation/validation-eval.md), [Approval](evaluation/approval-eval.md), [Running](evaluation/running-evals.md) |
| Development | [Setup](development/setup.md), [Running](development/running.md), [Configuration](development/configuration.md), [Debugging](development/debugging.md), [Repository structure](development/repository-structure.md) |
| Reference | [Issue codes](reference/issue-codes.md), [Normalization policy](reference/normalization-policy.md), [Glossary](reference/glossary.md) |

## Scope Labels

- **Implemented** means the current source has an execution path and tests or evaluator coverage.
- **Simulated** means the behavior is intentionally local and has no external side effect, as with payment.
- **Read-only** means the component displays saved state but cannot change it, as with the dashboard.
- **Not built** means the code does not claim to provide the capability, such as OCR or dashboard-driven human decisions.
