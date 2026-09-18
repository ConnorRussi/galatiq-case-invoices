# Approval

**State:** planned — no approval or critic-of-decision stage currently runs.

## Purpose and contract

Approval will convert a complete validation report into `approved`, `rejected`, or `needs_review`. It must explain how every blocking or review finding was addressed. A separate critic should check decision completeness and policy consistency, allowing only a bounded revision before routing unresolved cases to human review.

It receives the normalized candidate, ingestion issues, validation report, applicable policy output, and prior critic feedback. It produces a typed decision, reason list, addressed finding codes, human-review questions, and a `payment_authorized` flag. It must not re-extract data, alter validation evidence, call payment, or invent policy.

## Build prerequisites

Do not implement this area until Validation has stable findings and a versioned rule/policy boundary. The approval decision needs a deterministic policy baseline, including treatment for high-value invoices and unresolved evidence. Any human override must be structured and audited.

After implementation, document the exact decision schema, policy versioning, critic limit, and the route to [Payment](../payment/README.md).
