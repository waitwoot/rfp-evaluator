"""Validation tool: coerce whatever the LLM returned into a trustworthy shape.

An LLM's output is treated as hostile input. Every deviation is repaired
deterministically, and every repair leaves a human-readable warning, so the
UI can always show the marker exactly what the model got wrong and what the
system did about it.

The output of this module is the last point at which non-determinism exists.
Everything downstream (ranking_tool) is pure arithmetic over these numbers,
which is why "same validated inputs -> same ordering" holds even though the
model itself may vary between runs.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Literal, Sequence

from pydantic import BaseModel, Field, field_validator

from rfp.db import Criterion
from rfp.tools.document_tool import normalise_for_match

SENTINEL_NO_EVIDENCE = "No evidence found in document"
MIN_EVIDENCE_CHARS_TO_VERIFY = 12  # shorter quotes match by luck, not by grounding

ScoreStatus = Literal[
    "OK",                    # model returned a usable, in-range score
    "CLIPPED",               # out of range, clamped into [0, max_score]
    "DEFAULTED_INVALID",     # unparseable value ("eight", null) -> 0
    "DEFAULTED_MISSING",     # criterion absent from the response -> 0
    "DEFAULTED_PARSE_FAILURE",  # whole response unusable -> 0
]


class JSONParseError(ValueError):
    """The model's response contained no usable JSON object."""


class CriterionScore(BaseModel):
    criterion_id: int
    criterion_name: str
    score: float = Field(ge=0)
    max_score: float = Field(gt=0)
    justification: str = ""
    evidence: str = ""
    status: ScoreStatus = "OK"
    evidence_verified: bool = False

    @field_validator("justification", "evidence")
    @classmethod
    def _clean(cls, v: str) -> str:
        return (v or "").strip()


class ValidatedEvaluation(BaseModel):
    """One supplier's scores after normalisation. Always complete."""

    supplier_name: str
    criteria: list[CriterionScore]
    risks: list[str] = Field(default_factory=list)
    overall_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    parse_failed: bool = False

    def score_for(self, criterion_id: int) -> float:
        for c in self.criteria:
            if c.criterion_id == criterion_id:
                return c.score
        return 0.0


# ---------------------------------------------------------------------------
# JSON recovery
# ---------------------------------------------------------------------------
def _strip_code_fences(raw: str) -> str:
    text = (raw or "").strip()
    fence = re.match(r"^```[a-zA-Z0-9_-]*\s*\n(.*?)\n?```\s*$", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return text


def _first_json_object(text: str) -> str | None:
    """Return the first balanced {...} span, ignoring braces inside strings."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_llm_json(raw: str) -> dict[str, Any]:
    """Recover a JSON object from a response that may carry fences or chatter."""
    cleaned = _strip_code_fences(raw)
    for candidate in (cleaned, _first_json_object(cleaned)):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise JSONParseError("No parseable JSON object found in the model response.")


# ---------------------------------------------------------------------------
# value coercion
# ---------------------------------------------------------------------------
_NUMBER_RE = re.compile(r"^[-+]?\d+(?:\.\d+)?")


def coerce_score(value: Any) -> float | None:
    """Best-effort numeric reading. None means "not a number at all".

    Accepts 8, 8.0, "8", "8.5", "7/10", "7 out of 10".
    Rejects "eight", "", None, True/False.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        match = _NUMBER_RE.match(text)   # leading number wins: "7/10" -> 7
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                out.append(
                    str(item.get("risk") or item.get("description") or item).strip()
                )
            elif item is not None:
                out.append(str(item).strip())
        return [o for o in out if o]
    return [str(value).strip()]


def verify_evidence(evidence: str, document_text: str) -> bool:
    """True when the quoted evidence really appears in the extracted text."""
    quote = (evidence or "").strip()
    if not quote or quote == SENTINEL_NO_EVIDENCE:
        return False
    if len(quote) < MIN_EVIDENCE_CHARS_TO_VERIFY:
        return False
    return normalise_for_match(quote) in normalise_for_match(document_text)


# ---------------------------------------------------------------------------
# main entry points
# ---------------------------------------------------------------------------
def _criterion_lookup(criteria: Sequence[Criterion]) -> tuple[dict, dict]:
    by_id = {c.criterion_id: c for c in criteria}
    by_name = {c.name.strip().lower(): c for c in criteria}
    return by_id, by_name


def validate_evaluation(
    payload: dict[str, Any],
    criteria: Sequence[Criterion],
    *,
    supplier_name: str,
    document_text: str = "",
) -> ValidatedEvaluation:
    """Normalise one parsed LLM payload against the criteria loaded from the DB.

    The returned evaluation always carries exactly one entry per active
    criterion, in criterion_id order, with a score inside [0, max_score].
    """
    by_id, by_name = _criterion_lookup(criteria)
    warnings: list[str] = []
    resolved: dict[int, CriterionScore] = {}

    raw_name = str(payload.get("supplier_name") or "").strip()
    if raw_name and raw_name.lower() != supplier_name.strip().lower():
        warnings.append(
            f"Model reported supplier name '{raw_name}'; using the "
            f"user-entered name '{supplier_name}'."
        )

    raw_items = payload.get("criteria")
    if not isinstance(raw_items, list):
        warnings.append(
            "Model response had no 'criteria' list; all criteria defaulted to 0."
        )
        raw_items = []

    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            warnings.append(f"Ignored criteria entry {index + 1}: not an object.")
            continue

        # --- identify the criterion (by id, else by name) -------------------
        criterion = None
        raw_id = item.get("criterion_id")
        parsed_id = coerce_score(raw_id)
        if parsed_id is not None and float(parsed_id).is_integer():
            criterion = by_id.get(int(parsed_id))
        if criterion is None:
            raw_cname = str(
                item.get("criterion_name") or item.get("name") or ""
            ).strip()
            if raw_cname:
                criterion = by_name.get(raw_cname.lower())
                if criterion is not None and raw_id is not None:
                    warnings.append(
                        f"Unknown criterion_id {raw_id!r}; matched by name "
                        f"'{criterion.name}' instead."
                    )
                elif criterion is not None:
                    warnings.append(
                        f"Entry {index + 1} had no criterion_id; matched by name "
                        f"'{criterion.name}'."
                    )
        if criterion is None:
            warnings.append(
                f"Dropped an unknown criterion from the model response "
                f"(id={raw_id!r}, name={item.get('criterion_name')!r})."
            )
            continue

        if criterion.criterion_id in resolved:
            warnings.append(
                f"Duplicate entry for '{criterion.name}'; kept the first and "
                "discarded the later one."
            )
            continue

        # --- max_score: the database always wins ---------------------------
        llm_max = coerce_score(item.get("max_score"))
        if llm_max is not None and abs(llm_max - criterion.max_score) > 1e-9:
            warnings.append(
                f"'{criterion.name}': model used max_score {llm_max:g} but the "
                f"database defines {criterion.max_score:g}; database value applied."
            )

        # --- score ----------------------------------------------------------
        status: ScoreStatus = "OK"
        raw_score = item.get("score")
        score = coerce_score(raw_score)
        if score is None:
            warnings.append(
                f"'{criterion.name}': score {raw_score!r} is not a number; "
                "defaulted to 0."
            )
            score, status = 0.0, "DEFAULTED_INVALID"
        elif score > criterion.max_score:
            warnings.append(
                f"'{criterion.name}': score {score:g} exceeds the maximum "
                f"{criterion.max_score:g}; clipped."
            )
            score, status = criterion.max_score, "CLIPPED"
        elif score < 0:
            warnings.append(
                f"'{criterion.name}': score {score:g} is below 0; clipped."
            )
            score, status = 0.0, "CLIPPED"

        # --- evidence -------------------------------------------------------
        evidence = str(item.get("evidence") or "").strip()
        justification = str(item.get("justification") or "").strip()
        verified = verify_evidence(evidence, document_text)
        if evidence and evidence != SENTINEL_NO_EVIDENCE and not verified:
            warnings.append(
                f"'{criterion.name}': quoted evidence was not found in the "
                "document text; score kept but marked unverified."
            )

        resolved[criterion.criterion_id] = CriterionScore(
            criterion_id=criterion.criterion_id,
            criterion_name=criterion.name,
            score=score,
            max_score=criterion.max_score,
            justification=justification,
            evidence=evidence or SENTINEL_NO_EVIDENCE,
            status=status,
            evidence_verified=verified,
        )

    # --- any criterion the model never mentioned ---------------------------
    for criterion in criteria:
        if criterion.criterion_id not in resolved:
            warnings.append(
                f"'{criterion.name}': missing from the model response; "
                "defaulted to 0."
            )
            resolved[criterion.criterion_id] = CriterionScore(
                criterion_id=criterion.criterion_id,
                criterion_name=criterion.name,
                score=0.0,
                max_score=criterion.max_score,
                justification="Not returned by the model.",
                evidence=SENTINEL_NO_EVIDENCE,
                status="DEFAULTED_MISSING",
                evidence_verified=False,
            )

    ordered = [resolved[c.criterion_id] for c in criteria]
    return ValidatedEvaluation(
        supplier_name=supplier_name,
        criteria=ordered,
        risks=_coerce_str_list(payload.get("risks")),
        overall_summary=str(payload.get("overall_summary") or "").strip(),
        warnings=warnings,
    )


def defaulted_evaluation(
    criteria: Sequence[Criterion],
    *,
    supplier_name: str,
    reason: str,
) -> ValidatedEvaluation:
    """Every criterion 0, supplier still visible on the leaderboard.

    Used when the model's output could not be parsed even after the repair
    retry. Dropping the supplier would silently change the peer group and
    therefore every other supplier's benchmark, so it stays in with zeros.
    """
    return ValidatedEvaluation(
        supplier_name=supplier_name,
        criteria=[
            CriterionScore(
                criterion_id=c.criterion_id,
                criterion_name=c.name,
                score=0.0,
                max_score=c.max_score,
                justification="No valid model output was produced for this supplier.",
                evidence=SENTINEL_NO_EVIDENCE,
                status="DEFAULTED_PARSE_FAILURE",
                evidence_verified=False,
            )
            for c in criteria
        ],
        risks=[],
        overall_summary="",
        warnings=[reason],
        parse_failed=True,
    )


def validate_raw_response(
    raw: str,
    criteria: Sequence[Criterion],
    *,
    supplier_name: str,
    document_text: str = "",
) -> ValidatedEvaluation:
    """Convenience wrapper: parse then validate, defaulting on parse failure."""
    try:
        payload = parse_llm_json(raw)
    except JSONParseError as exc:
        return defaulted_evaluation(
            criteria, supplier_name=supplier_name, reason=str(exc)
        )
    return validate_evaluation(
        payload, criteria, supplier_name=supplier_name, document_text=document_text
    )


def collect_warnings(evaluations: Iterable[ValidatedEvaluation]) -> list[str]:
    """Flatten per-supplier warnings, prefixed with the supplier name."""
    out: list[str] = []
    for ev in evaluations:
        out.extend(f"{ev.supplier_name}: {w}" for w in ev.warnings)
    return out
