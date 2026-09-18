"""Read document structure without interpreting invoice fields."""

import csv
import json
from pathlib import Path
from xml.etree import ElementTree

import pdfplumber

from .models import SourceChunk, SourceDocument


class SourceReadingError(Exception):
    """The file cannot be represented as readable source content."""


def read_source(path: str | Path) -> SourceDocument:
    path = Path(path)
    file_type = path.suffix.lower().lstrip(".")
    if file_type not in {"pdf", "txt", "md", "csv", "json", "xml"}:
        raise SourceReadingError(f"Unsupported file extension: {path.suffix}")
    try:
        if file_type == "pdf":
            chunks = _read_pdf(path)
        elif file_type == "csv":
            with path.open(encoding="utf-8-sig", newline="") as handle:
                chunks = [
                    SourceChunk(
                        id=f"row_{number}",
                        text=json.dumps(row, ensure_ascii=False),
                        row=number,
                        kind="row",
                        extraction_method="csv",
                    )
                    for number, row in enumerate(csv.reader(handle, strict=True), 1)
                ]
        else:
            # Strict UTF-8 reports damaged input instead of silently replacing claims.
            text = path.read_text(encoding="utf-8-sig")
            if file_type == "json":
                json.loads(text, parse_constant=_invalid_json_constant)
            elif file_type == "xml":
                # No external resources or entity expansion are needed for invoices.
                if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
                    raise SourceReadingError("XML DTDs and entity declarations are unsupported")
                ElementTree.fromstring(text)
            chunks = [SourceChunk(
                id="text_1", text=text, kind="text",
                extraction_method=file_type if file_type in {"json", "xml"} else "text",
            )]
        if not chunks or not any(chunk.text.strip() for chunk in chunks):
            raise SourceReadingError("No readable source content")
        return SourceDocument(filename=path.name, file_type=file_type, chunks=tuple(chunks))
    except SourceReadingError:
        raise
    except Exception as exc:
        raise SourceReadingError(f"Could not read {path} ({file_type}): {exc}") from exc


def _invalid_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _read_pdf(path: Path) -> list[SourceChunk]:
    chunks = []
    with pdfplumber.open(path) as document:
        for number, page in enumerate(document.pages, 1):
            text = page.extract_text(layout=True) or ""
            if not any(character.isalnum() for character in text):
                raise SourceReadingError(
                    f"{path.name}, page {number}: no meaningful native text; "
                    "OCR is required for image-only content and is unavailable."
                )
            chunks.append(SourceChunk(
                id=f"page_{number}", text=text, page=number,
                kind="page", extraction_method="pdfplumber",
            ))
    if not chunks:
        raise SourceReadingError(f"{path.name}: PDF contains no pages")
    return chunks
