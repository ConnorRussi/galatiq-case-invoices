# Issue Codes

Issue codes are strings on `ValidationIssue`; stage code is the source of truth. The most important implemented codes include:

| Code | Stage | Meaning |
| --- | --- | --- |
| `PRODUCT_NOT_FOUND` | Database | No inventory row matched any permitted attempted name. |
| `INSUFFICIENT_INVENTORY` | Database | Requested quantity exceeds available stock. |
| `MISSING_QUANTITY` | Database | Stock sufficiency cannot be established. |
| `unresolved_validation` | Validation finalization | Critic disagreement remained after the revision limit. |
| `technical_failure` | Validation technical result | Graph or stage execution failed. |

Semantic and reconciliation issue strings are model/policy outputs and should be read from the saved result rather than inferred from this short index. Use `field`, `message`, `severity`, and `evidence` together; a code alone is not the full finding.
