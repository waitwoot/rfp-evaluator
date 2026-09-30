"""Shared fixtures. Criteria are built in-memory so tests never touch the app DB."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rfp.db import SEED_CRITERIA, Criterion  # noqa: E402
from rfp.tools.validation_tool import (  # noqa: E402
    CriterionScore,
    ValidatedEvaluation,
)


@pytest.fixture
def ab_criteria() -> list[Criterion]:
    """The hand-checked worked example: Tech 60% / Price 40%, both out of 10."""
    return [
        Criterion(1, "Technical", "Technical capability", 60.0, 10.0, True),
        Criterion(2, "Price", "Commercial value", 40.0, 10.0, True),
    ]


@pytest.fixture
def default_criteria() -> list[Criterion]:
    """The five seeded criteria, without needing a database."""
    return [
        Criterion(cid, name, desc, weight, max_score, True)
        for cid, name, desc, weight, max_score in SEED_CRITERIA
    ]


@pytest.fixture
def make_eval():
    """Factory: make_eval("Apex", {1: 8, 2: 5}, criteria) -> ValidatedEvaluation."""

    def _make(
        supplier_name: str,
        scores: dict[int, float],
        criteria: list[Criterion],
        *,
        status: str = "OK",
        evidence_verified: bool = True,
    ) -> ValidatedEvaluation:
        return ValidatedEvaluation(
            supplier_name=supplier_name,
            criteria=[
                CriterionScore(
                    criterion_id=c.criterion_id,
                    criterion_name=c.name,
                    score=float(scores.get(c.criterion_id, 0.0)),
                    max_score=c.max_score,
                    justification=f"Justification for {c.name}.",
                    evidence=f"Evidence for {c.name}.",
                    status=status,
                    evidence_verified=evidence_verified,
                )
                for c in criteria
            ],
            risks=[],
            overall_summary=f"Summary for {supplier_name}.",
            warnings=[],
        )

    return _make
