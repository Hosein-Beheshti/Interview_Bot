"""Extract plain text from candidate-uploaded CVs (PDF, DOCX, TXT)."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

from pypdf import PdfReader
from docx import Document

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}
SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}


class CVParseError(ValueError):
    """Raised when a CV cannot be parsed into usable text."""


@dataclass(frozen=True)
class ParsedCV:
    filename: str
    text: str
    char_count: int


def extension(filename: str) -> str:
    """Return the lowercased file extension (including the dot), or ''."""
    idx = filename.rfind(".")
    return filename[idx:].lower() if idx != -1 else ""


def parse(filename: str, content: bytes) -> ParsedCV:
    ext = extension(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise CVParseError(f"Unsupported file type: {ext or filename}")

    extractor = _EXTRACTORS[ext]
    raw = extractor(content)
    cleaned = _normalize(raw)

    if len(cleaned) < 50:
        raise CVParseError("CV appears to be empty or unreadable")

    return ParsedCV(filename=filename, text=cleaned, char_count=len(cleaned))


def _extract_pdf(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx(content: bytes) -> str:
    doc = Document(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_txt(content: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CVParseError("Could not decode text file")


_EXTRACTORS = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
    ".txt": _extract_txt,
}


_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE.sub(" ", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()
