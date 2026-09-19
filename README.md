# Galatiq Case: Invoice Processing Automation

## Current implementation

The application preserves invoice source content, normalizes claims with separate
source evidence, validates Semantic/Reconciliation/Database concerns, routes valid
invoices through Business Rule/optional VP approval, and executes a local mock
payment only after approval. One normal CLI command runs the full workflow.

Supported sources: PDF (native pdfplumber text), TXT, Markdown, CSV, JSON, XML.
Source chunks are immutable. CSV headers and rows remain in order; JSON and XML
are checked for syntax and retained as source text. No invoice fields are parsed
by the reader. Text is decoded as UTF-8 with optional BOM; invalid encoding fails
explicitly. PDFs with a page lacking meaningful text fail with an OCR-required
message; OCR is not installed by this application.

Install with Python 3.13 or later:

```bash
python -m pip install -e ".[ingestion]"
python main.py --invoice_path=data/invoices/invoice_1001.txt
python main.py --invoice_path=data/invoices/invoice_1001.txt --database-path=inventory.sqlite
```

Each CLI run creates `logs/runs/<run_id>/`. The CLI prints concise progress for
ingestion, validation, approval, optional VP review, and payment. Stage artifacts
are retained as work completes, and `workflow_result.json` records the terminal
status, stop point, and reason. Only `APPROVED_AND_PAID` returns exit code 0.
Dates serialize as ISO dates and Decimal values serialize as strings.

Copy `.env.example` to `.env` and set `TAMUS_AI_CHAT_API_KEY` and
`TAMUS_AI_CHAT_MODEL` to your institution's key and exact model ID. The endpoint
defaults to `https://chat-api.tamu.ai`; override `TAMUS_AI_CHAT_API_ENDPOINT` if
your institution uses another endpoint. The runtime calls `/api/chat/completions`
with bearer authentication. It supplies the JSON schema in the system message
and checks the returned JSON with Pydantic. Server-side schema enforcement is
not assumed. Invalid output raises a technical error without a correction loop.
Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` to enable optional tracing.
See [PHASE1_HANDOFF.md](PHASE1_HANDOFF.md) for exact schemas, prompt, decisions,
and the historical Phase 1 verification record. Current architecture is in
[`docs/index.md`](docs/index.md).

The original case narrative below is implemented as a local prototype; payment
is simulated and has no external banking side effect.

## Background

Acme Corp is a PE-backed manufacturing firm losing **$2M/year** on manual invoice processing. Invoices arrive via email as PDFs in messy formats with frequent errors. Staff manually extract data, validate against a legacy inventory database (inconsistent), obtain VP approval (via email chains), and process payment (via a banking API).

**Current pain points:**
- 30% error rate
- 5-day processing delays
- Frustrated stakeholders

## Objective

Build a **multi-agent system** that automates the end-to-end invoice processing workflow. The system must run as a working prototype — not just designs or slides.

> **Repository status:** The human-facing CLI runs ingestion, full validation,
> approval, optional VP review, and local mock payment end to end.

## Repository Documentation

The active implementation lives in `src/invoice_system/ingestion/`, with the shared
LLM runtime in `src/invoice_system/agent_runtime.py` and the CLI in `main.py`.

## Workflow

The system should handle four stages:

1. **Ingestion** — Extract structured data from invoice documents (PDFs, text files). Fields include: Vendor, Amount, Items (with quantities), and Due Date. Expect unstructured text, typos, missing data, and potentially fraudulent entries.

2. **Validation** — Verify extracted data against a mock inventory database (SQLite). Flag mismatches such as quantity exceeding available stock or items not found in inventory.

3. **Approval** — Simulate VP-level review with rule-based decision-making (e.g., invoices over $10K require additional scrutiny). The agent should reason through approval/rejection with a reflection or critique loop.

4. **Payment** — If approved, call a mock payment function. If rejected, log the rejection with reasoning.

## Technical Requirements

- **LLM Integration**: Use xAI's Grok as the core reasoning engine (via the xAI API at https://grok.x.ai). Other models are acceptable if you don't have an API key.
- **Multi-Agent Orchestration**: Use a framework such as LangGraph, CrewAI, AutoGen, or a custom solution.
- **Agent Capabilities**: Function calling / tool use, structured outputs, and self-correction loops.
- **Runtime**: Assume no internet for external APIs — simulate everything locally.
- **Tech Stack**: Python (preferred), with libraries like `langchain`, `crewai`, `autogen`, `pdfplumber`, `PyMuPDF`, etc. Run locally — no cloud deployment.

## Provided Resources

### Mock Invoice Data

Sample invoices are provided in the `data/invoices/` directory in various formats (PDF, CSV, JSON, TXT). Use these as inputs for testing. The data intentionally includes a mix of clean entries and problematic ones — identifying and handling issues is part of the challenge.

### Mock Inventory Database (Required Setup)

Before running the system, you **must** create a local SQLite database that the validation agent will check invoices against. The sample invoices in `data/invoices/` reference specific items and quantities — your database needs to contain matching inventory records so the validation stage can flag mismatches, out-of-stock items, and unknown products.

Below is a starter schema and seed data that covers the core items referenced across the provided invoices:

```python
import sqlite3

conn = sqlite3.connect('inventory.sqlite')  # Persist to file so all agents can access it
cursor = conn.cursor()

cursor.execute('CREATE TABLE IF NOT EXISTS inventory (item TEXT PRIMARY KEY, stock INTEGER)')
cursor.execute("""
    INSERT INTO inventory VALUES
    ('WidgetA', 15),
    ('WidgetB', 10),
    ('GadgetX', 5),
    ('FakeItem', 0)
""")
conn.commit()
```

**Why this matters:** The sample invoices are designed to test your validation logic against this database. For example:

| Scenario | Invoice | What should happen |
|---|---|---|
| Normal order within stock | INV-1001, INV-1004, INV-1006 | Items found, quantities valid — passes validation |
| Quantity exceeds stock | INV-1002 (requests 20× GadgetX, only 5 in stock) | Flagged as stock mismatch |
| Fraudulent / zero-stock item | INV-1003 (references FakeItem, 0 stock) | Flagged as out of stock or suspicious |
| Item not in database at all | INV-1008 (SuperGizmo, MegaSprocket), INV-1016 (WidgetC) | Flagged as unknown item |
| Invalid data | INV-1009 (negative quantity) | Flagged as data integrity issue |

You may extend the seed data with additional items or columns (e.g., unit price, category) to support richer validation — the above is the minimum needed to exercise the provided test invoices. If you want your system to also validate pricing or vendor information, consider adding tables for those as well.

### Mock Payment API

```python
def mock_payment(vendor, amount):
    print(f"Paid {amount} to {vendor}")
    return {"status": "success"}
```

### Grok API Setup

```python
from xai import Grok

client = Grok(api_key="your_key")
response = client.chat.completions.create(
    model="grok-3",
    messages=[{"role": "user", "content": "Reason about this..."}]
)
```

## Running the System

The system should be executable from the command line:

```bash
python main.py --invoice_path=data/invoices/invoice1.txt
```

Output should include structured logs and results.

## Evaluation Criteria

- **Functionality** — Does the system work end-to-end?
- **Code Quality** — Clean, testable, well-structured code with error handling and observability
- **Agentic Sophistication** — LLM integration, multi-agent flow, tool use, self-correction loops
- **Shipping Mindset** — Valuable MVP delivered under ambiguity; scope ruthlessly cut where needed
- **Presentation** — Clear translation of technical decisions to business impact
- **Above/Beyond** - Have you made it your own? Implemented additional features that make the solution feel great? Expanded assumptions? Added to test cases?
- **UI/UX** - Users will understand and enjoy using this system.

## Submission

Submit your solution as a link to a public GitHub repository — GitHub only (github.com).
