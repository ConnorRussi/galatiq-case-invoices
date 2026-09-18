"""Safe multi-format intake and native-text PDF extraction for the POC."""
import csv
import hashlib
import io
import json
import mimetypes
from pathlib import Path

import pdfplumber
from defusedxml import ElementTree
from pdfplumber.utils.exceptions import PdfminerException
from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError

from .config import DocumentSettings
from .models import EvidenceLocator, ExtractedDocument, Page, PageBlock, SourceDocument

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".json", ".csv", ".xml"}


class InvalidInput(ValueError):
    pass


def read_source(path: Path, limits: DocumentSettings) -> tuple[SourceDocument, bytes]:
    try:
        path = path.expanduser().resolve()
        if path.suffix.lower() not in SUPPORTED_SUFFIXES or not path.is_file():
            raise InvalidInput("Expected an accessible PDF, TXT, JSON, CSV, or XML invoice")
        with path.open("rb") as stream:
            data = stream.read(limits.max_file_bytes + 1)
    except InvalidInput:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise InvalidInput("Source path is inaccessible") from exc
    if len(data) > limits.max_file_bytes:
        raise InvalidInput("Source exceeds the configured file-size limit")
    if path.suffix.lower() == ".pdf" and not data.startswith(b"%PDF-"):
        raise InvalidInput("Invalid PDF signature")
    return SourceDocument(path=path, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream"), data


def extract(source: SourceDocument, data: bytes, limits: DocumentSettings) -> ExtractedDocument:
    if source.path.suffix.lower() == ".pdf":
        return _extract_pdf_text(source, data, limits)
    return _extract_text_document(source, data, limits)


def _extract_pdf_text(source: SourceDocument, data: bytes, limits: DocumentSettings) -> ExtractedDocument:
    pages, text_parts, count = [], [], 0
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if pdf.doc.encryption:
                raise InvalidInput("Encrypted PDFs are unsupported")
            if not pdf.pages or len(pdf.pages) > limits.max_pdf_pages:
                raise InvalidInput("PDF page count exceeds configured limits or is empty")
            for number, raw_page in enumerate(pdf.pages, 1):
                page = Page(number=number, width=raw_page.width, height=raw_page.height)
                rows: list[list[tuple[int, dict]]] = []
                for index, word in enumerate(raw_page.extract_words()):
                    if not rows or abs(word["top"] - rows[-1][0][1]["top"]) > 3:
                        rows.append([])
                    rows[-1].append((index, word))
                for index, row in enumerate(rows):
                    text = " ".join(word["text"] for _, word in row)
                    count += len(text) + 1
                    if count > limits.max_extracted_characters:
                        raise InvalidInput("Extracted PDF text exceeds the configured character limit")
                    locator = EvidenceLocator(page=number, block_id=f"p{number}-b{index}", word_ids=[word_id for word_id, _ in row], bbox=[min(word["x0"] for _, word in row), min(word["top"] for _, word in row), max(word["x1"] for _, word in row), max(word["bottom"] for _, word in row)])
                    page.blocks.append(PageBlock(locator=locator, text=text))
                    text_parts.append(text)
                pages.append(page)
    except InvalidInput:
        raise
    except (PdfminerException, PDFSyntaxError, PDFPasswordIncorrect, PDFEncryptionError, ValueError) as exc:
        raise InvalidInput("Unreadable PDF") from exc
    text = "\n".join(text_parts)
    if sum(character.isalnum() for character in text) < limits.minimum_alphanumeric_characters:
        raise InvalidInput("PDF has no usable native text; visual/OCR input is deferred in the POC")
    return ExtractedDocument(source=source, pages=pages, text=text)


def _extract_text_document(source: SourceDocument, data: bytes, limits: DocumentSettings) -> ExtractedDocument:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidInput("Text invoice is not valid UTF-8") from exc
    if len(text) > limits.max_extracted_characters:
        raise InvalidInput("Source text exceeds the configured character limit")
    try:
        suffix = source.path.suffix.lower()
        if suffix == ".json":
            json.loads(text)
        elif suffix == ".csv":
            list(csv.reader(io.StringIO(text)))
        elif suffix == ".xml":
            ElementTree.fromstring(text)
    except (json.JSONDecodeError, csv.Error, ElementTree.ParseError) as exc:
        raise InvalidInput(f"Malformed {suffix.removeprefix('.').upper()} invoice") from exc
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise InvalidInput("Source text is empty")
    page = Page(number=1, width=1000.0, height=max(float(len(lines) * 16 + 16), 32.0))
    for index, line in enumerate(lines):
        top = float(index * 16)
        page.blocks.append(PageBlock(locator=EvidenceLocator(page=1, block_id=f"p1-b{index}", word_ids=list(range(len(line.split()))), bbox=[0.0, top, min(999.0, max(1.0, float(len(line) * 7))), top + 14.0]), text=line))
    return ExtractedDocument(source=source, pages=[page], text="\n".join(lines))
