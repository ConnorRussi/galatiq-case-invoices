import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def cli():
    path = Path(__file__).resolve().parents[5] / "main.py"
    spec = importlib.util.spec_from_file_location("invoice_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_explicit_inputs(cli, monkeypatch):
    monkeypatch.setattr(cli, "generate_pdf_fixtures", lambda: pytest.fail("unexpected regeneration"))
    selected = cli.run(["data/invoices/invoice_1011.pdf", "missing.pdf"], pipeline_runner=lambda p: p)
    assert len(selected) == 2
    assert selected[0] == cli.PROJECT_ROOT / "data/invoices/invoice_1011.pdf"
    with pytest.raises(cli.OrchestrationError):
        cli.run([], pipeline_runner=lambda p: p)


def test_cli_generate(cli, invoices, monkeypatch):
    monkeypatch.setattr(cli, "generate_pdf_fixtures", lambda: tuple(invoices))
    assert cli.run([], regenerate_pdfs=True, pipeline_runner=lambda p: p) == tuple(invoices)
    assert cli.build_parser().parse_args(["--generate-pdfs"]).generate_pdfs


def test_cli_batch_json(cli, invoices, tmp_path, monkeypatch, capsys):
    import json
    from invoice_system.ingestion.workflow import run_pipeline
    from invoice_system.ingestion.fake import FakeProvider
    from invoice_system.ingestion.config import IngestionSettings
    monkeypatch.setattr(cli, "generate_pdf_fixtures", lambda: tuple(invoices))
    monkeypatch.setattr(cli, "load_pipeline_runner", lambda: lambda paths: run_pipeline(
        paths, settings=IngestionSettings(), provider=FakeProvider(), runs_dir=tmp_path / "runs"))
    assert cli.main(["--generate-pdfs"]) == 0
    assert len(json.loads(capsys.readouterr().out)["results"]) == 3
    assert cli.main(["--invoice_path", str(invoices[0]), "--invoice_path", "missing.pdf"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert [item["result"]["status"] for item in output["results"]] == ["ready_for_validation", "invalid_input"]
