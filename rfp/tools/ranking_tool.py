"""Ranking tool: every number in the system is produced here, in pure Python.

No LLM is involved at any point in this module, and that separation is the
whole point. The model contributes one thing only -- a score per criterion,
grounded in quoted evidence. Weighting, benchmarking, the Peer Performance
Index, tie-breaking and the final ranks are arithmetic, and arithmetic must be
reproducible, auditable and identical on every run. An LLM asked to "rank these
suppliers" can neither be audited nor reproduced.

Formulas
--------
    weighted points     = score / max_score * weight
    absolute score      = sum(weighted points)                     -> 0..100
    benchmark(c)        = max validated score for c across the run
    gap(c)              = score - benchmark                        -> <= 0
    relative %(c)       = score / benchmark * 100                  -> 0 if benchmark is 0
    PPI                 = sum(relative % * weight) / sum(weight)

Tie-breaks, applied in order until one separates the pair:
    1. higher PPI (rounded to 4 dp first)
    2. earlier submission date
    3. higher historical experience rating
    4. supplier name A-Z
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Sequence

from rfp import config
from rfp.db import Criterion
from rfp.tools.validation_tool import ValidatedEvaluation

TIE_BREAK_RULES: dict[int, str] = {
    1: "Higher Peer Performance Index",
    2: "Earlier submission date",
    3: "Higher historical experience rating",
    4: "Supplier name, alphabetical",
}


@dataclass
class SupplierInput:
    """One supplier entering the ranking: metadata plus validated scores."""

    supplier_name: str
    submission_date: date | str | None
    experience_rating: float | None
    evaluation: ValidatedEvaluation
    document_info: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# primitive formulas -- each one is independently unit tested
# ---------------------------------------------------------------------------
def weighted_points(score: float, max_score: float, weight: float) -> float:
    """score / max_score * weight."""
    if max_score <= 0:
        return 0.0
    return score / max_score * weight


def relative_performance(score: float, benchmark: float) -> float:
    """score / benchmark * 100, defined as 0 when the benchmark is 0.

    A zero benchmark means no supplier scored anything on this criterion, so
    the division is undefined. Returning 0 for everyone keeps the criterion
    neutral between suppliers instead of crashing or silently dropping it.
    """
    if benchmark <= 0:
        return 0.0
    return score / benchmark * 100.0


def peer_performance_index(
    pairs: Sequence[tuple[float, float]]
) -> float:
    """sum(relative % * weight) / sum(weight) over (relative_pct, weight) pairs."""
    total_weight = sum(w for _, w in pairs)
    if total_weight <= 0:
        return 0.0
    return sum(rel * w for rel, w in pairs) / total_weight


def compute_benchmarks(
    suppliers: Sequence[SupplierInput], criteria: Sequence[Criterion]
) -> dict[int, float]:
    """Highest validated score per criterion across everyone in this run."""
    benchmarks: dict[int, float] = {}
    for criterion in criteria:
        scores = [s.evaluation.score_for(criterion.criterion_id) for s in suppliers]
        benchmarks[criterion.criterion_id] = max(scores) if scores else 0.0
    return benchmarks


def parse_submission_date(value: date | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# tie-breaking
# ---------------------------------------------------------------------------
def _sort_key(row: dict[str, Any]) -> tuple:
    """One stable key expressing all four tie-break rules in priority order.

    PPI is rounded before it enters the key: two mathematically equal indices
    can differ in the 15th decimal place through float accumulation, and an
    unrounded sort would let that noise decide a rank instead of the
    submission date.
    """
    return (
        -row["ppi"],                                   # 1. higher PPI first
        row["_date_key"],                              # 2. earlier date first
        -(row["experience_rating"] or 0.0),            # 3. higher experience first
        row["supplier_name"].strip().lower(),          # 4. name A-Z
    )


def _explain_pair(above: dict[str, Any], below: dict[str, Any]) -> dict[str, Any]:
    """Name the rule that put `above` ahead of `below`, and say it in English."""
    dp = config.PPI_SORT_DECIMALS

    if above["ppi"] != below["ppi"]:
        level = 1
        text = (
            f"Higher PPI: {above['supplier_name']} {above['ppi']:.{dp}f} "
            f"vs {below['supplier_name']} {below['ppi']:.{dp}f}."
        )
    elif above["_date_key"] != below["_date_key"]:
        level = 2
        text = (
            f"PPI tied at {above['ppi']:.{dp}f}; {above['supplier_name']} "
            f"submitted earlier ({above['submission_date']} vs "
            f"{below['submission_date']})."
        )
    elif (above["experience_rating"] or 0.0) != (below["experience_rating"] or 0.0):
        level = 3
        text = (
            f"PPI ({above['ppi']:.{dp}f}) and submission date "
            f"({above['submission_date']}) both tied; {above['supplier_name']} has "
            f"the higher experience rating ({above['experience_rating']:g} vs "
            f"{below['experience_rating']:g})."
        )
    else:
        level = 4
        text = (
            f"PPI, submission date and experience rating all tied; ordered "
            f"alphabetically ({above['supplier_name']} before "
            f"{below['supplier_name']})."
        )

    return {
        "above": above["supplier_name"],
        "below": below["supplier_name"],
        "rule_level": level,
        "rule": TIE_BREAK_RULES[level],
        "explanation": text,
    }


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------
def rank_suppliers(
    suppliers: Sequence[SupplierInput], criteria: Sequence[Criterion]
) -> dict[str, Any]:
    """Score, benchmark and rank every supplier in one run.

    Returns a dict with ``suppliers`` (ranked, rich per-criterion detail),
    ``benchmarks``, ``tie_breaks`` and ``warnings``.
    """
    if not suppliers:
        return {"suppliers": [], "benchmarks": {}, "tie_breaks": [], "warnings": []}

    warnings: list[str] = []
    benchmarks = compute_benchmarks(suppliers, criteria)

    for criterion in criteria:
        if benchmarks[criterion.criterion_id] <= 0:
            warnings.append(
                f"No supplier scored above 0 on '{criterion.name}', so its peer "
                "benchmark is 0. Relative performance is reported as 0% for every "
                "supplier on this criterion and it cannot separate them."
            )

    rows: list[dict[str, Any]] = []
    for supplier in suppliers:
        parsed_date = parse_submission_date(supplier.submission_date)
        if parsed_date is None and supplier.submission_date:
            warnings.append(
                f"{supplier.supplier_name}: submission date "
                f"'{supplier.submission_date}' could not be read; it sorts last "
                "on the date tie-break."
            )

        detail: list[dict[str, Any]] = []
        rel_weight_pairs: list[tuple[float, float]] = []
        absolute = 0.0

        for criterion in criteria:
            cid = criterion.criterion_id
            scored = next(
                (c for c in supplier.evaluation.criteria if c.criterion_id == cid),
                None,
            )
            score = scored.score if scored else 0.0
            benchmark = benchmarks[cid]
            points = weighted_points(score, criterion.max_score, criterion.weight)
            relative = relative_performance(score, benchmark)
            absolute += points
            rel_weight_pairs.append((relative, criterion.weight))

            detail.append({
                "criterion_id": cid,
                "criterion_name": criterion.name,
                "weight": criterion.weight,
                "max_score": criterion.max_score,
                "score": round(score, 4),
                "benchmark": round(benchmark, 4),
                "gap": round(score - benchmark, 4),
                "relative_pct": round(relative, 4),
                "weighted_points": round(points, 4),
                "status": scored.status if scored else "DEFAULTED_MISSING",
                "evidence_verified": bool(scored.evidence_verified) if scored else False,
                "justification": scored.justification if scored else "",
                "evidence": scored.evidence if scored else "",
            })

        rows.append({
            "supplier_name": supplier.supplier_name,
            "submission_date": (
                parsed_date.isoformat() if parsed_date
                else (str(supplier.submission_date) if supplier.submission_date else None)
            ),
            "experience_rating": (
                float(supplier.experience_rating)
                if supplier.experience_rating is not None else 0.0
            ),
            "absolute_score": round(absolute, 4),
            "ppi": round(
                peer_performance_index(rel_weight_pairs), config.PPI_SORT_DECIMALS
            ),
            "criteria": detail,
            "risks": list(supplier.evaluation.risks),
            "overall_summary": supplier.evaluation.overall_summary,
            "warnings": list(supplier.evaluation.warnings),
            "parse_failed": supplier.evaluation.parse_failed,
            "document": dict(supplier.document_info),
            "_date_key": parsed_date or date.max,   # unreadable dates sort last
        })

    rows.sort(key=_sort_key)

    tie_breaks = [
        _explain_pair(rows[i], rows[i + 1]) for i in range(len(rows) - 1)
    ]

    for position, row in enumerate(rows):
        row["final_rank"] = position + 1
        row["tie_break_reason"] = (
            tie_breaks[position]["explanation"] if position < len(tie_breaks)
            else "Lowest ranked supplier in this run."
        )
        row["tie_break_rule_level"] = (
            tie_breaks[position]["rule_level"] if position < len(tie_breaks) else None
        )
        row.pop("_date_key", None)

    return {
        "suppliers": rows,
        "benchmarks": {str(k): round(v, 4) for k, v in benchmarks.items()},
        "tie_breaks": tie_breaks,
        "warnings": warnings,
    }
