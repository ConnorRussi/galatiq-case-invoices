import json
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_system.ingestion import critic
from invoice_system.ingestion import normalizer
from invoice_system.ingestion.graph import _find_critique_instability, revise_node
from invoice_system.ingestion.evaluation import (
    SCALAR_FIELDS, _common_fields_section, _evidence_section, _line_items_section,
)
from invoice_system.ingestion.gate import build_completed_result
from invoice_system.ingestion.models import (
    CritiqueResult, IngestionResult, IngestionStatus, NormalizationResult,
    NormalizedInvoice, SourceChunk, SourceDocument,
)
from invoice_system.agent_runtime import StructuredOutputError

ROOT = Path(__file__).resolve().parents[1]


def source(text='Tax (6%): 885.00'):
    return SourceDocument(filename='test.txt', file_type='txt', chunks=(
        SourceChunk(id='text_1', text=text, kind='text', extraction_method='text'),
    ))


@pytest.mark.parametrize(('path', 'proposed', 'message'), [
    ('items[0].quantity', -5, 'Quantity should be a numeric type, not a string.'),
    ('items[0].unit_price', '225.00', 'Use two decimal places.'),
    ('items[0].line_amount', None, 'Policy forbids deriving values. No issue in this regard.'),
    ('invoice_date', '2026-01-26', 'OCR correction is allowed.'),
])
def test_no_op_corrections_do_not_trigger_review(monkeypatch, path, proposed, message):
    candidate = NormalizationResult(invoice={
        'invoice_date': '2026-01-26',
        'items': [{'quantity': '-5', 'unit_price': '225.0'}],
    }, evidence=[])

    def invoke(**kwargs):
        payload = json.loads(kwargs['content'])
        assert 'candidate_schema' in payload
        assert payload['normalization']['invoice']['items'][0]['quantity'] == '-5'
        return kwargs['output_model'].model_validate({'issues': [{
            'issue_type': 'incorrect_value', 'field_path': path,
            'message': message, 'proposed_value': proposed,
        }]})

    monkeypatch.setattr(critic, 'invoke_structured', invoke)
    result = critic.critique(source(), candidate)
    assert result.issues == []
    assert build_completed_result(source_path='test.txt', source_document=source(),
        normalization=candidate, critique=result, revision_count=0).status == IngestionStatus.ACCEPT


def test_real_value_and_evidence_corrections_survive(monkeypatch):
    candidate = NormalizationResult(invoice={'items': [{'quantity': '-5'}]}, evidence=[
        {'field_path': 'items[0].quantity', 'source_chunk_ids': ['text_1'], 'source_text': 'wrong'},
    ])
    changes = [
        {'issue_type': 'incorrect_value', 'field_path': 'items[0].quantity',
         'message': 'The amount is already correct but the quantity should be -6.', 'proposed_value': -6},
        {'issue_type': 'evidence_problem', 'field_path': 'evidence[0].source_text',
         'message': 'Quote the actual claim.', 'proposed_value': '-6'},
    ]
    monkeypatch.setattr(critic, 'invoke_structured', lambda **kw: kw['output_model'].model_validate({'issues': changes}))
    review = critic.critique(source('Quantity: -6'), candidate)
    assert len(review.issues) == 1
    assert review.issues[0].proposed_value == -6
    assert candidate.invoice.items[0].quantity == Decimal('-5')


def test_critic_sanitizes_blank_and_schema_invalid_proposals(monkeypatch):
    candidate = NormalizationResult(invoice={
        'vendor': 'Wrong vendor',
        'items': [{'line_amount': '3500'}],
    }, evidence=[])
    changes = [
        {'issue_type': 'incorrect_value', 'field_path': 'vendor',
         'message': 'The source vendor is blank.', 'proposed_value': ''},
        {'issue_type': 'incorrect_value', 'field_path': 'items[0].line_amount',
         'message': 'Correct the OCR value.', 'proposed_value': '3500.O0'},
    ]
    monkeypatch.setattr(critic, 'invoke_structured', lambda **kw: kw['output_model'].model_validate({'issues': changes}))

    review = critic.critique(source('Vendor: ""\nAmount: $3,500.O0'), candidate)

    assert len(review.issues) == 1
    assert review.issues[0].field_path == 'vendor'
    assert review.issues[0].proposed_value is None


def test_critic_rejects_evidence_correction_targeting_invoice_field(monkeypatch):
    candidate = NormalizationResult(invoice={'invoice_date': '2026-01-26'}, evidence=[
        {'field_path': 'invoice_date', 'source_chunk_ids': ['text_1'], 'source_text': 'DATE: 26-Jan-2O26'},
    ])
    monkeypatch.setattr(
        critic,
        'invoke_structured',
        lambda **kw: kw['output_model'].model_validate({'issues': [{
            'issue_type': 'evidence_problem', 'field_path': 'invoice_date',
            'message': 'Evidence needs correction.', 'proposed_value': '26-Jan-2O26',
        }]}),
    )

    assert critic.critique(source('DATE: 26-Jan-2O26'), candidate).issues == []


def test_normalizer_contract_handles_blank_ambiguous_amount_notes_and_embedded_po(monkeypatch):
    source_document = source('Amt: $15,000.00\nRef PO-20260115. Deliver to dock B.')
    candidate = NormalizationResult(invoice={
        'vendor': '',
        'subtotal': '15000',
        'additional_fields': {'payment_terms': '', 'notes': 'Ref PO-20260115. Deliver to dock B.'},
        'items': [{'additional_fields': {'note': 'Keep this note'}}],
    }, evidence=[
        {'field_path': 'subtotal', 'source_chunk_ids': ['text_1'], 'source_text': 'Amt: $15,000.00'},
        {'field_path': 'additional_fields.notes', 'source_chunk_ids': ['text_1'], 'source_text': 'Ref PO-20260115. Deliver to dock B.'},
        {'field_path': 'items[0].additional_fields.note', 'source_chunk_ids': ['text_1'], 'source_text': 'Keep this note'},
    ])
    monkeypatch.setattr(normalizer, 'invoke_structured', lambda **kw: candidate)

    result = normalizer.normalize(source_document)

    assert result.invoice.vendor is None
    assert result.invoice.subtotal is None
    assert result.invoice.additional_fields['amount_raw'] == '$15,000.00'
    assert result.invoice.additional_fields['payment_terms'] is None
    assert result.invoice.additional_fields['purchase_order'] == 'PO-20260115'
    assert result.invoice.additional_fields['notes'] == 'Ref PO-20260115. Deliver to dock B.'
    assert result.invoice.items[0].additional_fields == {'notes': 'Keep this note'}
    assert {item.field_path for item in result.evidence} >= {
        'additional_fields.amount_raw', 'additional_fields.purchase_order',
        'items[0].additional_fields.notes',
    }


def test_normalizer_contract_promotes_explicit_total_and_amount_due(monkeypatch):
    source_document = source('Total Amount: $5,000.00\nAmount Due: $4,500.00')
    candidate = NormalizationResult(invoice={
        'additional_fields': {'amount_raw': '$5,000.00'},
    }, evidence=[
        {
            'field_path': 'additional_fields.amount_raw',
            'source_chunk_ids': ['text_1'],
            'source_text': 'Total Amount: $5,000.00',
        },
    ])
    monkeypatch.setattr(normalizer, 'invoke_structured', lambda **kw: candidate)

    result = normalizer.normalize(source_document)

    assert result.invoice.invoice_total == Decimal('5000.00')
    assert result.invoice.amount_due == Decimal('4500.00')
    assert 'amount_raw' not in result.invoice.additional_fields
    assert {item.field_path for item in result.evidence} >= {'invoice_total', 'amount_due'}


def test_invalid_revision_preserves_last_valid_candidate(monkeypatch):
    previous = NormalizationResult(invoice={'invoice_total': '250'}, evidence=[])
    review = CritiqueResult(issues=[{
        'issue_type': 'incorrect_value', 'field_path': 'invoice_total',
        'message': 'Use the source total.', 'proposed_value': '300',
    }])
    source_document = source('Total: 250')
    monkeypatch.setattr(
        'invoice_system.ingestion.graph.revise_normalization',
        lambda *args: (_ for _ in ()).throw(StructuredOutputError('invalid Decimal output')),
    )
    update = revise_node({
        'source_path': 'test.txt', 'source_document': source_document,
        'normalization': previous, 'critique': review, 'revision_count': 0,
        'critique_history': [], 'critic_instability': None,
        'revision_errors': [], 'result': None,
    })

    assert update['normalization'] == previous
    assert update['revision_count'] == 1
    assert update['revision_errors'] == ['invalid Decimal output']


def test_critic_does_not_enforce_normalization_only_conventions(monkeypatch):
    candidate = NormalizationResult(invoice={
        'due_date': None,
        'additional_fields': {'due_date_raw': 'yesterday', 'payment_terms': ''},
    }, evidence=[
        {'field_path': 'due_date_raw', 'source_chunk_ids': ['text_1'], 'source_text': 'Due: yesterday'},
    ])
    monkeypatch.setattr(critic, 'invoke_structured', lambda **kw: kw['output_model']())
    assert critic.critique(source('Due: yesterday\nPayment terms: '), candidate).issues == []


def test_critic_revision_reversal_is_detected():
    previous = CritiqueResult(issues=[{
        'issue_type': 'unsupported_inference',
        'field_path': 'invoice_total',
        'message': 'Clear unsupported value.',
        'proposed_value': None,
    }])
    current = CritiqueResult(issues=[{
        'issue_type': 'missing_information',
        'field_path': 'invoice_total',
        'message': 'Restore value.',
        'proposed_value': '15000',
    }])
    candidate = NormalizationResult(invoice={'invoice_total': None}, evidence=[])
    assert 'Critic reversal on invoice_total' in _find_critique_instability(
        [previous], candidate, current
    )


@pytest.mark.parametrize(('currency', 'evidence', 'passed'), [
    (None, [], True),
    ('USD', [], False),
    ('USD', [{'field_path': 'currency', 'source_chunk_ids': ['text_1'], 'source_text': 'USD'}], True),
])
def test_currency_requires_source_evidence_when_populated(currency, evidence, passed):
    result = IngestionResult(status='accept', source_path='test.txt', source_document=source('Currency: USD'),
        normalization=NormalizationResult(invoice={'currency': currency}, evidence=evidence))
    assert _evidence_section(result).passed is passed


def test_normalizer_collects_usd_from_dollar_symbol(monkeypatch):
    candidate = NormalizationResult(invoice={}, evidence=[])
    monkeypatch.setattr(normalizer, 'invoke_structured', lambda **kw: candidate)

    result = normalizer.normalize(source('Total: $225.00'))

    assert result.invoice.currency == 'USD'
    assert any(item.field_path == 'currency' and item.source_text == '$' for item in result.evidence)


def test_normalizer_keeps_currency_unknown_without_code_or_symbol(monkeypatch):
    candidate = NormalizationResult(invoice={'currency': 'USD'}, evidence=[])
    monkeypatch.setattr(normalizer, 'invoke_structured', lambda **kw: candidate)

    result = normalizer.normalize(source('Total: 225.00'))

    assert result.invoice.currency is None


def test_normalizer_collects_explicit_currency_code(monkeypatch):
    candidate = NormalizationResult(invoice={}, evidence=[])
    monkeypatch.setattr(normalizer, 'invoke_structured', lambda **kw: candidate)

    result = normalizer.normalize(source('Currency: EUR\nTotal: €225.00'))

    assert result.invoice.currency == 'EUR'
    assert any(item.field_path == 'currency' and 'EUR' in (item.source_text or '') for item in result.evidence)


@pytest.mark.parametrize(('quote', 'ids', 'passed'), [
    ('6%', ['text_1'], True), ('"6%"', ['text_1'], True),
    ('"7%"', ['text_1'], False), ('0.06', ['text_1'], False),
    ('6%', ['missing'], False), ('6%', [], False),
])
def test_evidence_accepts_display_quotes_but_not_invented_claims(quote, ids, passed):
    result = IngestionResult(status='accept', source_path='test.txt', source_document=source(),
        normalization=NormalizationResult(invoice={'tax_rate': '0.06'}, evidence=[
            {'field_path': 'tax_rate', 'source_chunk_ids': ids, 'source_text': quote},
        ]))
    assert _evidence_section(result).passed is passed


@pytest.mark.parametrize('path', sorted((ROOT / 'evals/ingestion/expected').glob('*.json')), ids=lambda p: p.stem)
def test_goldens_cover_every_typed_field_and_reject_invented_values(path):
    golden = json.loads(path.read_text())
    assert set(SCALAR_FIELDS) <= golden.keys()
    invoice = NormalizedInvoice.model_validate(golden)
    assert invoice.currency in {None, 'USD', 'EUR'}
    for item in golden['items']:
        assert {'item_name', 'quantity', 'unit_price', 'line_amount'} <= item.keys()
    # Any previously unspecified scalar is now an explicit null assertion.
    null_field = next(name for name in ('subtotal', 'tax_rate', 'tax_amount', 'shipping', 'discount', 'amount_due') if golden[name] is None)
    setattr(invoice, null_field, Decimal('123'))
    result = IngestionResult(status='accept', source_path=golden['fixture'],
        normalization=NormalizationResult(invoice=invoice, evidence=[]))
    assert not _common_fields_section(result, golden).passed
    for item in invoice.items:
        if item.line_amount is None:
            item.line_amount = Decimal('123')
            assert not _line_items_section(result, golden).passed
            break
