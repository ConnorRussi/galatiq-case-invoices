# Payment boundary

The payment boundary is a local simulation implemented in
[`src/invoice_system/payment/`](../src/invoice_system/payment/). It exists to
demonstrate the case workflow without contacting a bank or external API.

Invoice identity and payment history are tracked separately in
[`src/invoice_system/invoice_ledger.py`](../src/invoice_system/invoice_ledger.py).
The ledger keys a case by normalized vendor and invoice number, hashes the
immutable source content, suppresses exact versions already paid, and records
when a changed version follows a paid version. A paid revision becomes
`HUMAN_REVIEW_REQUIRED`; it cannot authorize another full payment. The revised
total minus the prior paid amount is exposed as an adjustment candidate for a
future human decision.

`PaymentRequest` receives an approved invoice ID, vendor, positive amount, and
required three-letter ISO currency code. The workflow selects `amount_due` first
and falls back to `invoice_total`; a missing vendor or amount blocks payment
explicitly before the provider is called. An absent source currency is resolved
to the authorized USD policy default during normalization; unresolved currency
conflicts still block payment.

`run_payment()` passes vendor, amount, and currency to the injectable
`mock_payment()` provider and returns a typed `PaymentResult`. The workflow also
derives an idempotency key from the invoice case and source version; a future
external provider must receive that key on the payment request. Success includes
a mock transaction ID. Provider exceptions and
non-success responses become `FAILED` results rather than escaping as fabricated
successes.

Within the end-to-end workflow, payment appends events to the shared
`events.jsonl` and writes `payment_input.json` and `payment_result.json`. Validation
denial and approval rejection cannot reach this boundary.
