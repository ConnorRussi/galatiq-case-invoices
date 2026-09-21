# Invoice review dashboard

Build and open a local, display-only snapshot:

```bash
python dashboard.py
```

Open `runs/dashboard.html` in a browser. Rebuild after processing new invoices.
No server, installation, credentials, external assets, or model calls are needed.
Optional `--logs-root` and `--output` arguments select the artifact tree and output.

The dashboard owns presentation only. It reads completed `workflow_result.json`
files and workflow `summary.json` files under `logs/`, including evaluation runs.
It never directly changes workflow state or submits payments. The workflow and
invoice ledger remain the source of truth; a future interactive dashboard can
send explicit human-review commands back through a controlled service boundary.
The generated HTML contains the invoice data; treat it as a copy of those records.

The invoice list groups evaluation invoices by run, newest run first, and puts
review outcomes first within each group. Individual invoice runs have their own
group. Each repeated run retains its artifact path and saved-file timestamp.
Search, evaluation-run, and outcome filters narrow the list. Click anywhere on
an invoice row to select it, or use its invoice button with the keyboard. Failed/denied outcomes share a business-facing Needs
review label while retaining their exact underlying reason. All paid outcomes
are labeled simulated. No additional currency or source facts are inferred.
Original lines, consolidated quantities, prices, totals, inventory checks,
approval reasoning, invoice-history decisions, source text, and recorded
evidence are available together. Paid revisions show the prior payment,
revised amount, and adjustment candidate.

The evaluation tab shows completed workflow suite summaries. A passing expected
denial is distinct from payment success. Older runs describe historical behavior,
not necessarily current code. Partial runs without a terminal workflow artifact
are omitted; malformed artifacts are skipped with a visible warning. A missing
artifact directory produces an empty state. Offline coverage is in
[`test_dashboard.py`](../tests/test_dashboard.py), including repeated runs and
escaping untrusted source text embedded in HTML.

## Deferred decisions

Human decision recording and workflow resumption are not implemented yet. The
current snapshot displays `DUPLICATE_SUPPRESSED` and
`HUMAN_REVIEW_REQUIRED` cases, but a human action endpoint remains a future
step. Content hashing and duplicate-payment prevention are owned by the
invoice ledger rather than inferred by the dashboard.

Summary totals reflect the currently displayed invoices after search, run, and
outcome filters; an empty result displays zero in all three totals.
