# Glossary

| Term | Meaning |
| --- | --- |
| Source chunk | Immutable page, row, or text unit captured before field interpretation. |
| Normalization | Mapping explicit source claims into a typed invoice representation with evidence. |
| Critic | A structured reviewer that agrees or requests a bounded revision. |
| Semantic validation | Checks whether claims are usable and coherent without doing arithmetic or inventory. |
| Reconciliation | Product identity interpretation plus line/subtotal/total arithmetic checks. |
| Database validation | Inventory lookup and requested-quantity versus stock comparison. |
| Invoice history | SQLite record of business invoice versions and payment state. |
| Business Rule Agent | Policy interpreter that selects accept, reject, or VP review. |
| VP Agent | Escalation decision agent that selects go, no-go, or human review. |
| Review required | A terminal local status; this repository has no human decision submission path. |
| Mock payment | Local provider call that returns a generated transaction ID without bank side effects. |
| Workflow artifact | JSON or JSONL evidence saved under a run/evaluation directory. |
