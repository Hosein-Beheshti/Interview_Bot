"""Extract plain text from candidate-uploaded CVs (PDF, DOCX, TXT)."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

from docx import Document
from pypdf import PdfReader

from interview_bot.config import settings

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

    # The single minimum-text rule, from config. It lives here rather than in the
    # route because this is the only place the extracted text exists, and the
    # client mirrors the same number via `GET /api/config` — one threshold, one
    # source. The two cases are separated because their fixes differ: no text at
    # all is a wrong-kind-of-file problem, too little text is a wrong-file problem.
    if not cleaned:
        raise CVParseError(
            "No text could be extracted. Image-only or scanned PDFs have no text "
            "layer — paste the text instead."
        )
    if len(cleaned) < settings.cv_min_chars:
        raise CVParseError(
            f"This CV has only {len(cleaned)} characters of text; at least "
            f"{settings.cv_min_chars} are needed to interview on it."
        )

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


# A CV's own name line is almost always near the top and looks like "Jane Doe" or
# "JANE A. DOE" — one to four capitalised words, no digits or contact-detail
# punctuation. Heading keywords ("Resume", "Curriculum Vitae", ...) are common on
# the same line or just above it and would otherwise match the same shape.
_NAME_LINE = re.compile(r"^[A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z][A-Za-z.'-]*){0,3}$")
_NON_NAME_KEYWORDS = (
    "resume",
    "curriculum vitae",
    "cv",
    "phone",
    "email",
    "address",
    "profile",
    "summary",
    "objective",
)


def extract_name(text: str) -> str | None:
    """Best-effort first name of the CV's owner, from the document's opening lines.

    Heuristic, not authoritative: returns None rather than guessing when the
    top of the document doesn't look like a name line.
    """
    for line in text.splitlines()[:8]:
        candidate = line.strip()
        if not candidate or "@" in candidate or any(ch.isdigit() for ch in candidate):
            continue
        if candidate.lower() in _NON_NAME_KEYWORDS:
            continue
        if not _NAME_LINE.match(candidate):
            continue
        return candidate.split()[0].capitalize()
    return None
