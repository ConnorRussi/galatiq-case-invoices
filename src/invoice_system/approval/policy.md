# Acme approval policy

- Invoices above **$10,000** require additional scrutiny and must be escalated for VP review.
- Unusual or non-standard payment conditions require additional scrutiny and may be escalated for VP review.
- Unresolved business concerns, including concerns that make payment unsafe or unsupported, require rejection.
- A validated and reconciled invoice with no triggered escalation rule and no unresolved concern may be accepted.
- An exact invoice version that has already been paid must be suppressed without a second payment.
- A changed invoice version received after a prior version was paid must be routed through VP triage and marked for human review. It must not authorize a second full payment.
- A human reviewer may later authorize an adjustment, credit, refund, or rejection. The adjustment candidate is the revised payable amount minus the prior paid amount when the revised invoice represents a new total.

These rules are the source of truth. The Business Rule Agent interprets equivalent
invoice field names and upstream representations against this policy; it must not
invent additional company policy. Missing, contradictory, or unusable upstream
information must be reported as a concern rather than guessed.
