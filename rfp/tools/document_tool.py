"""Document tool: turn an uploaded file into trustworthy plain text.

PyMuPDF is the primary extractor, pypdf the fallback. A document is rejected
*before* any LLM call whenever it is not a PDF, is encrypted, or carries no
text layer -- sending a scanned page to the model would produce confident
scores grounded in nothing at all.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from rfp import config

PDF_HEADER = b"%PDF"
HEADER_SEARCH_WINDOW = 1024  # some generators emit junk before the header


class DocumentError(Exception):
    """A document that must not reach the LLM.

    ``code`` is stable and machine-readable; ``str(e)`` is shown to the user.
    """

    def __init__(self, code: str, message: str, source_name: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.source_name = source_name


@dataclass
class ExtractedDocument:
    source_name: str
    text: str
    page_count: int
    char_count: int
    extractor: str
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("text")  # the full text is never persisted; only its measurements
        return d


def normalise_whitespace(text: str) -> str:
    """Collapse all runs of whitespace to single spaces."""
    return re.sub(r"\s+", " ", text or "").strip()


def normalise_for_match(text: str) -> str:
    """Case- and whitespace-insensitive form used for evidence verification."""
    return normalise_whitespace(text).lower()


def _read_bytes(source: bytes | bytearray | str | Path) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    return Path(source).read_bytes()


def _extract_pymupdf(data: bytes) -> tuple[str, int]:
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if doc.needs_pass:
            raise DocumentError(
                "ENCRYPTED",
                "The PDF is password protected, so its text cannot be read.",
            )
        pages = doc.page_count
        text = "\n".join(page.get_text() for page in doc)
    return text, pages


def _extract_pypdf(data: bytes) -> tuple[str, int]:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise DocumentError(
            "ENCRYPTED", "The PDF is password protected, so its text cannot be read."
        )
    pages = len(reader.pages)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return text, pages


def extract_document(
    source: bytes | bytearray | str | Path,
    *,
    source_name: str | None = None,
    max_chars: int | None = None,
    min_chars: int | None = None,
    max_bytes: int | None = None,
) -> ExtractedDocument:
    """Extract text from a PDF, or raise DocumentError explaining why not.

    Rejection codes: TOO_LARGE, EMPTY_FILE, NOT_A_PDF, ENCRYPTED,
    NO_TEXT_LAYER, EXTRACTION_FAILED.
    """
    name = source_name or (
        Path(source).name if isinstance(source, (str, Path)) else "uploaded.pdf"
    )
    max_chars = config.MAX_DOC_CHARS if max_chars is None else max_chars
    min_chars = config.MIN_DOC_CHARS if min_chars is None else min_chars
    max_bytes = config.MAX_UPLOAD_BYTES if max_bytes is None else max_bytes

    try:
        data = _read_bytes(source)
    except FileNotFoundError as exc:
        raise DocumentError("NOT_FOUND", f"File not found: {name}", name) from exc

    if not data:
        raise DocumentError("EMPTY_FILE", f"'{name}' is empty (0 bytes).", name)

    if len(data) > max_bytes:
        raise DocumentError(
            "TOO_LARGE",
            f"'{name}' is {len(data) / 1_048_576:.1f} MB, above the "
            f"{max_bytes / 1_048_576:.0f} MB limit.",
            name,
        )

    if PDF_HEADER not in data[:HEADER_SEARCH_WINDOW]:
        raise DocumentError(
            "NOT_A_PDF",
            f"'{name}' is not a PDF -- the file has no %PDF header. "
            "A file renamed to .pdf is still not a PDF.",
            name,
        )

    warnings: list[str] = []
    extractor = "pymupdf"
    try:
        text, page_count = _extract_pymupdf(data)
    except DocumentError as exc:
        exc.source_name = name
        raise
    except Exception as primary_exc:  # noqa: BLE001 - fall back on any parser fault
        extractor = "pypdf"
        warnings.append(
            f"PyMuPDF could not read '{name}' ({type(primary_exc).__name__}); "
            "fell back to pypdf."
        )
        try:
            text, page_count = _extract_pypdf(data)
        except DocumentError as exc:
            exc.source_name = name
            raise
        except Exception as fallback_exc:  # noqa: BLE001
            raise DocumentError(
                "EXTRACTION_FAILED",
                f"Neither PyMuPDF nor pypdf could read '{name}': {fallback_exc}",
                name,
            ) from fallback_exc

    stripped = normalise_whitespace(text)
    if len(stripped) < min_chars:
        raise DocumentError(
            "NO_TEXT_LAYER",
            f"'{name}' contains only {len(stripped)} characters of extractable "
            f"text (minimum {min_chars}). It is most likely a scan or an "
            "image-only PDF and would have to be OCR'd first.",
            name,
        )

    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
        warnings.append(
            f"'{name}' was truncated to {max_chars:,} characters for evaluation; "
            "evidence beyond that point was not seen by the model."
        )

    return ExtractedDocument(
        source_name=name,
        text=text,
        page_count=page_count,
        char_count=len(text),
        extractor=extractor,
        truncated=truncated,
        warnings=warnings,
    )


def bundled_sample_pdfs() -> list[Path]:
    """The four proposals shipped with the project, for the demo run."""
    directory = config.SAMPLE_PDF_DIR
    if not directory.exists():
        return []
    return sorted(p for p in directory.glob("*.pdf") if p.is_file())
