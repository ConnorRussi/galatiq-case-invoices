# Shared normalization policy

Normalization converts source claims into a consistent representation while preserving their meaning. It may standardize representation, including obvious unambiguous OCR/formatting errors, but it must not derive, validate, or invent business information.

- Only populate fields supported by the source.
- Capture an explicitly stated currency code from the source (for example, USD
  or EUR), or map an explicit `$` symbol to USD. Preserve the currency in
  `currency` and never convert monetary values. If the source has no currency
  claim, the authorized policy default is USD. A policy-default USD value is
  not a source claim and does not require source evidence. If source claims
  conflict, preserve the claims and mark the invoice for review; do not choose
  USD or any other currency to resolve the conflict.
- Do not calculate or derive missing business values such as totals, subtotals, line amounts, tax, or dates.
- Explicit labels are source claims, not derived values: map `Total Amount`,
  `Grand Total`, `Invoice Total`, or `Total` to `invoice_total`; map `Amount Due`,
  `Balance Due`, or `Total Due` to `amount_due`.
- When a source states a percentage tax rate, normalize it to a decimal fraction (`6%` → `0.06`).
- Normalize representation without changing meaning:
  - trim whitespace;
  - normalize currency and decimal formatting;
  - normalize unambiguous dates;
  - normalize obvious OCR character corruption when the intended value is unambiguous, especially numeric characters such as `O` → `0` inside an otherwise numeric value.
- Ambiguous values must not be forced into typed fields. Preserve meaningful raw claims in `additional_fields`.
- Empty or blank source values normalize to `null`.
- Preserve meaningful fields that do not fit the primary schema in `additional_fields`.
- Use canonical `additional_fields` names for known concepts where possible.
  - Use `payment_terms` for payment terms, `former_vendor_name` for a prior vendor name, and `due_date_raw` for an ambiguous due-date claim retained outside the typed date field.
  - Use a descriptive `*_raw` name for a meaningful claim whose business concept is ambiguous (for example, `amount_raw` for an unlabeled `Amt` value).
- Preserve actual source mistakes; do not silently fix semantic typos or business data.
- Numeric values are compared semantically: `225`, `225.0`, and `225.00` are equivalent.
- Never correct suspicious business values such as negative quantities during normalization.
- Evidence must point to the actual source claim, not a derived calculation.
- Quote the original source text, including OCR corruption, using paths such as `additional_fields.due_date_raw`. Evidence is required for every populated field, including currency. Empty values retained in additional_fields must be null, not empty strings.
- Preserve line order and repeated items, internal product-name spaces, and semantic spelling mistakes. Keep line-specific notes on their line. Use `notes`, `vendor_address`, `customer_name`, `customer_attention`, and `purchase_order` for those known additional concepts. Extract `purchase_order` only when the source clearly identifies an actual PO identifier; phrases such as `PO amendment` are not identifiers. Preserve full source notes unchanged even when a valid identifier is also extracted.
