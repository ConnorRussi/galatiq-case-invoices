"""Deterministic fixture interpreter and scripted failure provider, for tests only."""
import re
from collections import deque

from .models import Critique, InvoiceProposal, Issue, ObservedField, ProposedLineItem
from .providers import ModelResponse


def fixture_proposal(document):
    proposal = InvoiceProposal()
    patterns = {
        "invoice_number": r"(?:Invoice Number:|Invoice:|INV NO:)\s*(INV[- ]\d+)",
        "vendor": r"(?:Vendor:|FROM:)\s*(.*?)(?=\s+Due:|$)",
        "invoice_date": r"(?<!Due )\b(?:Date|DATE):\s*([^\n]+?)(?=\s+Due:|$)",
        "due_date": r"(?:Due Date:|Due:|DUE:)\s*(\S+)",
        "subtotal": r"(?i)SUBTOTAL:\s*(\$[\d,.O]+)",
        "tax": r"(?i)TAX\s*\([^)]*\):\s*(\$[\d,.O]+)",
        "declared_total": r"(?i)^(?:Grand )?TOTAL:\s*(\$[\d,.O]+)",
        "payment_terms": r"Terms:\s*(.*)",
    }
    for page in document.pages:
        for block in page.blocks:
            def observed(value):
                return ObservedField(literal=value, confidence=1, evidence=[block.locator])
            for name, pattern in patterns.items():
                match = re.search(pattern, block.text)
                if match:
                    setattr(proposal, name, observed(match.group(1)))
            if "$" in block.text and proposal.currency.literal is None:
                proposal.currency = observed("$")
            row = re.fullmatch(r"(.+?)\s+(-?\d+)\s+(\$[+-]?[\d,.O]+)\s+(\$[+-]?[\d,.O]+)(?:\s+(.*))?", block.text)
            if row:
                values = dict(zip(("name", "quantity", "unit_price", "declared_amount", "note"), row.groups()))
                proposal.line_items.append(ProposedLineItem(**{k: observed(v) for k, v in values.items() if v is not None}))
    return proposal


class FakeProvider:
    def __init__(self, script=None, visual_proposal=None):
        self.script = {key: deque(value) for key, value in (script or {}).items()}
        self.visual_proposal = visual_proposal
        self.calls = []

    def _respond(self, operation, context):
        self.calls.append(operation)
        if self.script.get(operation):
            value = self.script[operation].popleft()
            if isinstance(value, Exception):
                raise value
        elif operation == "critique":
            expected = fixture_proposal(context.document)
            missing = len(expected.line_items) > len(context.proposal.line_items)
            value = Critique(decision="revise" if missing else "accept", issues=[Issue(
                code="OMITTED_SOURCE_ROW", field="line_items", message="Source contains an omitted row") ] if missing else [])
        else:
            value = self.visual_proposal if context.visual and self.visual_proposal else fixture_proposal(context.document)
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        return ModelResponse(value)

    def interpret_text(self, context):
        return self._respond("interpret_text", context)

    def interpret_visual(self, context):
        return self._respond("pro" if context.adjudicate else "interpret_visual", context)

    def critique(self, context):
        return self._respond("critique", context)

    def revise(self, context):
        return self._respond("revise", context)
