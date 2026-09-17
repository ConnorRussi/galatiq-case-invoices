"""Bounded PDF intake and deterministic line/word coordinates."""
import hashlib
import io
import json
import mimetypes
import csv
from pathlib import Path

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException
from defusedxml import ElementTree
from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError

from .models import EvidenceLocator, ExtractedDocument, Page, PageBlock, SourceDocument
from .config import DocumentSettings


class InvalidInput(ValueError):
    pass


def read_source(path: Path, limits: DocumentSettings) -> tuple[SourceDocument, bytes]:
    try:
        path = path.expanduser().resolve()
        if path.suffix.lower() not in {".pdf", ".txt", ".json", ".csv", ".xml"} or not path.is_file():
            raise InvalidInput("Expected an accessible PDF, TXT, JSON, CSV, or XML file")
        with path.open("rb") as stream:
            data = stream.read(limits.max_file_bytes + 1)
    except (OSError, RuntimeError, ValueError) as exc:
        raise InvalidInput("Source path is inaccessible") from exc
    if len(data) > limits.max_file_bytes:
        raise InvalidInput("PDF exceeds file size limit")
    if path.suffix.lower() == ".pdf" and not data.startswith(b"%PDF-"):
        raise InvalidInput("Invalid PDF signature")
    return SourceDocument(
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    ), data


def extract(source: SourceDocument, data: bytes, limits: DocumentSettings) -> ExtractedDocument:
    if source.path.suffix.lower() != ".pdf":
        return _extract_text_document(source, data, limits)
    pages = []
    texts = []
    count = 0
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if pdf.doc.encryption:
                raise InvalidInput("Encrypted PDFs are unsupported")
            if not pdf.pages or len(pdf.pages) > limits.max_pdf_pages:
                raise InvalidInput("PDF page count exceeds limits or is empty")
            for number, raw_page in enumerate(pdf.pages, 1):
                page = Page(number=number, width=raw_page.width, height=raw_page.height)
                words = raw_page.extract_words()
                rows: list[list[tuple[int, dict]]] = []
                for index, word in enumerate(words):
                    if not rows or abs(word["top"] - rows[-1][0][1]["top"]) > 3:
                        rows.append([])
                    rows[-1].append((index, word))
                for index, row in enumerate(rows):
                    text = " ".join(word["text"] for _, word in row)
                    count += len(text) + 1
                    if count > limits.max_extracted_characters:
                        raise InvalidInput("Extracted text exceeds character limit")
                    locator = EvidenceLocator(page=number, block_id=f"p{number}-b{index}",
                        word_ids=[i for i, _ in row], bbox=(min(w["x0"] for _, w in row),
                        min(w["top"] for _, w in row), max(w["x1"] for _, w in row), max(w["bottom"] for _, w in row)))
                    page.blocks.append(PageBlock(locator=locator, text=text))
                    texts.append(text)
                pages.append(page)
    except (PdfminerException, PDFSyntaxError, PDFPasswordIncorrect, PDFEncryptionError, ValueError) as exc:
        raise InvalidInput("Unreadable, encrypted, or out-of-limits PDF") from exc
    text = "\n".join(texts)
    return ExtractedDocument(source=source, pages=pages, text=text,
        usable_text=sum(c.isalnum() for c in text) >= limits.minimum_alphanumeric_characters)


def _extract_text_document(source: SourceDocument, data: bytes, limits: DocumentSettings) -> ExtractedDocument:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidInput("Text invoice is not valid UTF-8") from exc
    if len(text) > limits.max_extracted_characters:
        raise InvalidInput("Extracted text exceeds character limit")
    suffix = source.path.suffix.lower()
    try:
        if suffix == ".json":
            json.loads(text)
        elif suffix == ".csv":
            list(csv.reader(io.StringIO(text)))
        elif suffix == ".xml":
            ElementTree.fromstring(text)
    except (json.JSONDecodeError, csv.Error, ElementTree.ParseError) as exc:
        raise InvalidInput(f"Malformed {suffix.removeprefix('.').upper()} invoice") from exc

    lines = [line for line in text.splitlines() if line.strip()]
    height = max(float(len(lines) * 16 + 16), 32.0)
    page = Page(number=1, width=1000.0, height=height)
    for index, line in enumerate(lines):
        top = float(index * 16)
        locator = EvidenceLocator(
            page=1,
            block_id=f"p1-b{index}",
            word_ids=list(range(len(line.split()))),
            bbox=(0.0, top, min(999.0, max(1.0, float(len(line) * 7))), top + 14.0),
        )
        page.blocks.append(PageBlock(locator=locator, text=line))
    return ExtractedDocument(
        source=source,
        pages=[page],
        text="\n".join(lines),
        usable_text=sum(character.isalnum() for character in text)
        >= limits.minimum_alphanumeric_characters,
    )


def valid_evidence(literal: str, locators: list[EvidenceLocator], document: ExtractedDocument, *, visual: bool) -> bool:
    if not locators:
        return False
    cited = []
    for locator in locators:
        page = next((p for p in document.pages if p.number == locator.page), None)
        if page is None or locator.bbox[2] > page.width or locator.bbox[3] > page.height:
            return False
        if locator.block_id is None:
            if not visual or locator.word_ids:
                return False
            continue
        block = next((b for b in page.blocks if b.locator.block_id == locator.block_id), None)
        if block is None or locator != block.locator:
            return False
        cited.append(block.text)
    return (visual and not cited) or literal in " ".join(cited)
