import json
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_system.ingestion import critic
from invoice_system.ingestion.evaluation import (
    SCALAR_FIELDS, _common_fields_section, _evidence_section, _line_items_section,
)
from invoice_system.ingestion.gate import build_completed_result
from invoice_system.ingestion.models import (
    CritiqueResult, IngestionResult, IngestionStatus, NormalizationResult,
    NormalizedInvoice, SourceChunk, SourceDocument,
)

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
    assert len(review.issues) == 2
    assert review.issues[0].proposed_value == -6
    assert candidate.invoice.items[0].quantity == Decimal('-5')


@pytest.mark.parametrize(('currency', 'evidence', 'passed'), [
    ('USD', [], True),
    ('EUR', [], False),
    ('USD', [{'field_path': 'currency', 'source_chunk_ids': ['text_1'], 'source_text': 'USD'}], False),
])
def test_default_currency_evidence_exception_is_bounded(currency, evidence, passed):
    result = IngestionResult(status='accept', source_path='test.txt', source_document=source(),
        normalization=NormalizationResult(invoice={'currency': currency}, evidence=evidence))
    assert _evidence_section(result).passed is passed


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
    assert invoice.currency == ('EUR' if path.stem == 'invoice_1014' else 'USD')
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
