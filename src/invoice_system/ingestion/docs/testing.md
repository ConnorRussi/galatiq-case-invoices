# Testing and safe changes

Run the agent suite from the workspace root:

```powershell
python -m pytest galatiq-case-invoices
```

The suite is offline. `tests/conftest.py` blocks socket connections except for tests marked `live`. It uses `FakeProvider` to cover good inputs, malformed schemas, timeout retries, critic disagreement, budget exhaustion, Pro escalation, image-only PDFs, atomic artifact failures, and batch continuation.

The three generated PDFs exercise the main behavior:

| Fixture | What the test protects |
| --- | --- |
| `INV-1011` | A complete clean candidate. |
| `INV-1012` | OCR-style `O` corrections inside valid money/date values, aliases such as `Widget A` to `WidgetA`, and unchanged vendor spelling. |
| `INV-1013` | Eight source rows and the declared total are retained exactly; no aggregation or arithmetic repair. |

When changing extraction, add a locator assertion. When changing a normalization rule, add both accepted and rejected examples. When changing graph routing, add a scripted `FakeProvider` response and assert the counters never exceed the configured limits. When changing model schemas, test both `GeminiProvider` and `FakeProvider` against the same Pydantic contract.

To run a live test deliberately, configure `GEMINI_API_KEY` and opt in with `-m live`. Do not make live tests part of the default suite.
