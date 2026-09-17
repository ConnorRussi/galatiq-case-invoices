import importlib.util
from pathlib import Path
import socket

import pytest

from invoice_system.ingestion.config import IngestionSettings
from invoice_system.ingestion.extraction import extract, read_source


@pytest.fixture(autouse=True)
def offline(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return
    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in offline tests")
    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.fixture(scope="session")
def invoices(tmp_path_factory):
    directory = tmp_path_factory.mktemp("invoices")
    module_path = Path(__file__).resolve().parents[1] / "scripts/generate_pdfs.py"
    spec = importlib.util.spec_from_file_location("generate_pdfs", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUTPUT_DIR = str(directory)
    module.create_clean_invoice()
    module.create_messy_invoice()
    module.create_bulk_invoice()
    return [directory / f"invoice_{number}.pdf" for number in (1011, 1012, 1013)]


@pytest.fixture
def settings():
    return IngestionSettings()


@pytest.fixture
def document(invoices, settings):
    source, data = read_source(invoices[0], settings.documents)
    return extract(source, data, settings.documents)


@pytest.fixture
def image_pdf(tmp_path):
    from PIL import Image, ImageDraw
    from fpdf import FPDF
    image = Image.new("RGB", (800, 300), "white")
    ImageDraw.Draw(image).text((30, 30), "Invoice: SCAN-001\nVendor: Scan Vendor\nWidgetA 2 $250.00 $500.00\nTotal: $500.00", fill="black", font_size=24)
    png = tmp_path / "scan.png"
    image.save(png)
    pdf = FPDF()
    pdf.add_page()
    pdf.image(str(png), x=10, y=10, w=180)
    path = tmp_path / "image-only.pdf"
    pdf.output(path)
    return path
