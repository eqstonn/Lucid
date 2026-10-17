"""PDF byte-stream ingestion and text normalization (in-memory only, zero disk I/O).

Brightspace auto-fetches and manual dropzone uploads both arrive as raw ``bytes``
and go through the exact same code path.
"""

from __future__ import annotations

import re
import unicodedata

import pymupdf as fitz  # PyMuPDF (the `fitz` alias is deprecated as a top-level import)

_PDF_MAGIC = b"%PDF-"
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_LINEBREAK = re.compile(r"(\w)-\n(\w)")
_INLINE_WS = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n{3,}")
# Characters PDFs commonly use that tokenize/read poorly downstream.
_TRANSLATE = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        "•": "-",
        "­": "",  # soft hyphen
        "​": "",  # zero-width space
    }
)


class ExtractionError(Exception):
    """Raised when no usable text can be extracted (caller should show the upload fallback)."""


def normalize_text(raw: str) -> str:
    """Clean raw PDF text: unicode/punctuation folding, de-hyphenation, whitespace collapse."""
    text = unicodedata.normalize("NFKC", raw).translate(_TRANSLATE)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARS.sub("", text)
    text = _HYPHEN_LINEBREAK.sub(r"\1\2", text)
    lines = [_INLINE_WS.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract and normalize text from PDF bytes held entirely in memory.

    Raises:
        ExtractionError: bytes are not a readable PDF, the PDF is encrypted, or it has
            no text layer (e.g. a scanned image).
    """
    if _PDF_MAGIC not in pdf_bytes[:1024]:  # spec allows junk before the header
        raise ExtractionError("Input is not a PDF")

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # fitz raises several distinct error types for corrupt input
        raise ExtractionError(f"Could not open PDF: {exc}") from exc

    with doc:
        if doc.needs_pass:
            raise ExtractionError("PDF is password protected")
        pages = [page.get_text("text", sort=True) for page in doc]

    text = normalize_text("\n\n".join(pages))
    if not text:
        raise ExtractionError("PDF contains no extractable text (possibly a scanned image)")
    return text


if __name__ == "__main__":
    assert normalize_text("Mid-\nterm  Exam— 20%\r\n\r\n\r\n\r\nQuiz  1") == "Midterm Exam- 20%\n\nQuiz 1"
    assert normalize_text("“Quiz” \x00 5%") == '"Quiz" 5%'

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Final Exam - 40%")
    page.insert_text((72, 100), "Assignments - 30%")
    data = doc.tobytes()
    doc.close()
    out = extract_text_from_pdf(data)
    assert "Final Exam - 40%" in out and "Assignments - 30%" in out, out

    for bad in (b"", b"not a pdf at all"):
        try:
            extract_text_from_pdf(bad)
        except ExtractionError:
            pass
        else:
            raise AssertionError("expected ExtractionError")

    blank = fitz.open()
    blank.new_page()
    try:
        extract_text_from_pdf(blank.tobytes())
    except ExtractionError:
        pass
    else:
        raise AssertionError("expected ExtractionError for textless PDF")
    print("extractor.py: all assertions passed")
