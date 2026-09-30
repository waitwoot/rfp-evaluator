"""Document tool: extraction, and the three rejections that must happen
before any LLM call is made."""

from __future__ import annotations

import pytest

from rfp import config
from rfp.tools.document_tool import (
    DocumentError,
    bundled_sample_pdfs,
    extract_document,
    normalise_for_match,
    normalise_whitespace,
)

SAMPLES = config.SAMPLE_PDF_DIR
ERROR_CASES = SAMPLES / "error_cases"

requires_samples = pytest.mark.skipif(
    not (SAMPLES / "nexaworks_proposal.pdf").exists(),
    reason="run scripts/generate_sample_pdfs.py first",
)


def test_normalise_whitespace_collapses_runs():
    assert normalise_whitespace("  a \n\n b\tc  ") == "a b c"
    assert normalise_for_match("  ISO   27001\n") == "iso 27001"
    assert normalise_whitespace(None) == ""


@requires_samples
def test_extracts_every_bundled_proposal():
    found = bundled_sample_pdfs()
    assert len(found) == 4
    for path in found:
        doc = extract_document(path)
        assert doc.page_count >= 2
        assert len(doc.text) > config.MIN_DOC_CHARS
        assert doc.extractor == "pymupdf"
        assert doc.truncated is False
        assert doc.warnings == []


@requires_samples
def test_extracted_text_contains_the_scored_content():
    doc = extract_document(SAMPLES / "apex_systems_proposal.pdf")
    flat = normalise_for_match(doc.text)
    assert "iso 27001" in flat
    assert "aes-256" in flat
    assert "$629,000" in flat            # the computed TCO really reached the page


@requires_samples
def test_accepts_bytes_as_well_as_paths():
    path = SAMPLES / "nexaworks_proposal.pdf"
    from_path = extract_document(path)
    from_bytes = extract_document(path.read_bytes(), source_name="nexaworks_proposal.pdf")
    assert from_bytes.text == from_path.text
    assert from_bytes.source_name == "nexaworks_proposal.pdf"


@requires_samples
def test_text_file_renamed_to_pdf_is_rejected():
    with pytest.raises(DocumentError) as exc:
        extract_document(ERROR_CASES / "not_a_pdf.pdf")
    assert exc.value.code == "NOT_A_PDF"
    assert "%PDF" in str(exc.value)


@requires_samples
def test_scanned_pdf_with_no_text_layer_is_rejected():
    with pytest.raises(DocumentError) as exc:
        extract_document(ERROR_CASES / "scanned_no_text.pdf")
    assert exc.value.code == "NO_TEXT_LAYER"
    assert "scan" in str(exc.value).lower()


def test_empty_file_is_rejected():
    with pytest.raises(DocumentError) as exc:
        extract_document(b"", source_name="empty.pdf")
    assert exc.value.code == "EMPTY_FILE"


def test_oversized_file_is_rejected_before_parsing():
    with pytest.raises(DocumentError) as exc:
        extract_document(b"%PDF-1.7" + b"\x00" * 5000,
                         source_name="huge.pdf", max_bytes=1024)
    assert exc.value.code == "TOO_LARGE"


def test_missing_file_is_reported_clearly():
    with pytest.raises(DocumentError) as exc:
        extract_document(SAMPLES / "does_not_exist.pdf")
    assert exc.value.code == "NOT_FOUND"


@requires_samples
def test_long_document_is_truncated_and_flagged():
    doc = extract_document(SAMPLES / "apex_systems_proposal.pdf", max_chars=500)
    assert doc.truncated is True
    assert len(doc.text) == 500
    assert any("truncated" in w for w in doc.warnings)


@requires_samples
def test_to_dict_never_leaks_the_full_text():
    """Document measurements are persisted; the document body is not."""
    payload = extract_document(SAMPLES / "nexaworks_proposal.pdf").to_dict()
    assert "text" not in payload
    assert payload["page_count"] >= 2
    assert payload["char_count"] > 0
