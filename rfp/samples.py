"""Metadata for the bundled demo proposals, shared by the CLI and the UI."""

from __future__ import annotations

from pathlib import Path

from rfp.tools.document_tool import bundled_sample_pdfs

# filename stem (without "_proposal") -> (supplier name, submission date, rating)
SAMPLE_METADATA: dict[str, tuple[str, str, float]] = {
    "apex_systems": ("Apex Systems", "2026-09-08", 4.2),
    "brightpath_tech": ("BrightPath Tech", "2026-09-11", 2.5),
    "nexaworks": ("NexaWorks", "2026-09-09", 4.0),
    "orbit_digital": ("Orbit Digital", "2026-09-10", 4.6),
}

DEFAULT_SUBMISSION_DATE = "2026-09-09"
DEFAULT_EXPERIENCE_RATING = 3.0


def metadata_for(filename: str) -> tuple[str, str, float]:
    """Best guess at a supplier's metadata from its filename."""
    stem = Path(filename).stem.replace("_proposal", "")
    if stem in SAMPLE_METADATA:
        return SAMPLE_METADATA[stem]
    return (
        stem.replace("_", " ").replace("-", " ").title(),
        DEFAULT_SUBMISSION_DATE,
        DEFAULT_EXPERIENCE_RATING,
    )


def sample_suppliers() -> list[dict]:
    """The four bundled proposals as orchestrator input."""
    suppliers = []
    for path in bundled_sample_pdfs():
        name, date, rating = metadata_for(path.name)
        suppliers.append({
            "supplier_name": name,
            "submission_date": date,
            "experience_rating": rating,
            "source": path,
            "source_name": path.name,
        })
    return suppliers
