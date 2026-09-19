"""Shared Phase 1 Semantic Validation scope contract."""

SEMANTIC_SCOPE_CONTRACT = """
PHASE 1 SEMANTIC SCOPE CONTRACT

Semantic validation answers: "Is the normalized invoice internally
understandable and semantically usable enough to continue to later stages?"

Semantic validation owns:
- invalid or unresolved semantic values, including relative/non-real dates,
  invalid dates, nonnumeric quantities, and impossible values;
- direct contradictions in the normalized invoice, such as an invoice date
  after its due date;
- negative quantities and negative unit prices when no valid semantic meaning
  is supplied; and
- basic line-item structure and other data-usability problems that prevent
  downstream reasoning.

Temporal boundary:
- DO NOT compare invoice dates against the current date, model knowledge
  cutoff, system date, or an assumed present date.
- A future invoice date is NOT by itself a Phase 1 semantic error.
- Phase 1 may only reason about relationships between dates contained within
  the invoice itself. invoice_date > due_date is a semantic contradiction;
  invoice_date > "today" is not a Phase 1 issue.
- Never use the model's knowledge cutoff as temporal evidence.

Required-field policy:
- Only fields explicitly required by the Phase 1 contract may cause a missing
  value denial. The presence of a field in the Pydantic schema does not make it
  semantically required.
- This Phase 1 contract does not universally require invoice_total, amount_due,
  subtotal, tax, payment terms, or any other financial-completeness field.
- Do not invent a required vendor, date, identifier, or payment field. Deny a
  missing field only when the supplied contract explicitly says it is required
  for semantic processing.

Semantic validation must not calculate or reconcile line totals, subtotals,
tax, invoice totals, or amount_due. It must not compare quantity * unit_price
with line_amount, infer a due date from payment terms such as Net 30, query or
compare database values, perform purchase-order or vendor verification, apply
approval/business thresholds, or determine payment eligibility.

Root-cause policy:
- Prefer one canonical issue for one underlying semantic failure. Do not emit
  both a raw-format issue and a missing-field symptom when the missing value is
  caused by the unresolved raw claim.
- For an unresolved relative due date stored as due_date_raw, report one
  relative_date issue with canonical field due_date and retain the raw value as
  evidence. Do not add a second missing_due_date issue unless an independent
  contract rule requires it.
- Use concise stable issue codes and canonical invoice-relative field paths.
"""


def semantic_scope_prompt() -> str:
    """Return the shared contract for inclusion in agent prompts."""

    return SEMANTIC_SCOPE_CONTRACT.strip()
