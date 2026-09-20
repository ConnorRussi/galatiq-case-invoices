# Payment boundary

The payment boundary is a local simulation implemented in
[`src/invoice_system/payment/`](../src/invoice_system/payment/). It exists to
demonstrate the case workflow without contacting a bank or external API.

`PaymentRequest` receives an approved invoice ID, vendor, positive amount, and
required three-letter ISO currency code. The workflow selects `amount_due` first
and falls back to `invoice_total`; a missing vendor or amount blocks payment
explicitly before the provider is called. An absent source currency is resolved
to the authorized USD policy default during normalization; unresolved currency
conflicts still block payment.

`run_payment()` passes vendor, amount, and currency to the injectable
`mock_payment()` provider and returns a typed
`PaymentResult`. Success includes a mock transaction ID. Provider exceptions and
non-success responses become `FAILED` results rather than escaping as fabricated
successes.

Within the end-to-end workflow, payment appends events to the shared
`events.jsonl` and writes `payment_input.json` and `payment_result.json`. Validation
denial and approval rejection cannot reach this boundary.
