# Normalization Policy

The shared policy is [`src/invoice_system/ingestion/normalization_policy.md`](../../src/invoice_system/ingestion/normalization_policy.md). It governs both normalizer and critic prompts.

Key rules:

- Preserve source claims and evidence; do not invent or calculate totals, taxes, line amounts, or dates.
- Capture explicit currency; an absent currency may use the policy default USD, but conflicting currency claims remain reviewable.
- Normalize representation such as whitespace, unambiguous dates, decimal formatting, and obvious unambiguous OCR corruption.
- Keep ambiguous values in `additional_fields` with descriptive names such as `amount_raw` or `due_date_raw`.
- Preserve line order, repeated items, internal product-name spaces, semantic spelling mistakes, and source notes.
- Never silently correct suspicious business values such as negative quantities.

This is extraction policy, not validation policy. Arithmetic, product existence, stock, approval, and payment belong to later stages.
