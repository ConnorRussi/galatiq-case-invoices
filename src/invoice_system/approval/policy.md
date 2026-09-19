# Acme approval policy

- Invoices above **$10,000** require additional scrutiny and must be escalated for VP review.
- Unusual or non-standard payment conditions require additional scrutiny and may be escalated for VP review.
- Unresolved business concerns, including concerns that make payment unsafe or unsupported, require rejection.
- A validated and reconciled invoice with no triggered escalation rule and no unresolved concern may be accepted.

These rules are the source of truth. The Business Rule Agent interprets equivalent
invoice field names and upstream representations against this policy; it must not
invent additional company policy. Missing, contradictory, or unusable upstream
information must be reported as a concern rather than guessed.
