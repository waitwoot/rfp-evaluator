"""Evaluation agent -- the ONLY component in this project that calls an LLM.

Three providers share one interface:
  openai     -- OpenAI SDK, with base_url so Groq / OpenRouter also work
  anthropic  -- Anthropic SDK
  mock       -- deterministic offline keyword scorer, no network, no key

The mock provider exists so the whole pipeline can be tested, demonstrated and
graded without an API key, and so the test suite never depends on a paid
service or on a model's mood. It emits the same JSON schema as a real model.

A fault-injection switch deliberately corrupts the first supplier's response,
so the validation layer can be demonstrated on demand rather than hoping a
real model misbehaves on camera.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from rfp import config, prompts
from rfp.db import Criterion

FAULT_MODES = ("malformed_values", "invalid_json_once", "invalid_json_always")

GARBAGE_RESPONSE = (
    "I'm sorry, but I am not able to complete this evaluation as requested. "
    "Please consult your procurement team for guidance."
)


class EvaluationError(RuntimeError):
    """The provider could not be reached or rejected the request outright."""


def _failed_generation(exc: Exception) -> str | None:
    """Recover the model's text from a server-side JSON-validation rejection.

    Returns None for every other kind of error, so genuine faults (bad key,
    retired model, exhausted rate limit) still abort the run loudly.
    """
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return None
    # The OpenAI SDK unwraps the {"error": {...}} envelope, so the payload
    # arrives flat; other gateways leave it nested. Accept both.
    for candidate in (body, body.get("error")):
        if isinstance(candidate, dict):
            salvaged = candidate.get("failed_generation")
            if isinstance(salvaged, str) and salvaged.strip():
                return salvaged
    return None


@dataclass
class AgentCall:
    """One completed model call, kept for the Run details tab."""

    supplier_name: str
    attempt: int
    provider: str
    model: str
    raw: str
    faulted: bool = False
    prompt_chars: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# deterministic offline scorer
# ---------------------------------------------------------------------------
# Indicative terms per seeded criterion. For criteria the user has added in the
# UI, terms are derived from the criterion description instead (see below).
MOCK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "technical capability": (
        "architecture", "kubernetes", "postgresql", "api", "scalab", "rest",
        "openapi", "failover", "stateless", "integration", "sip2", "saml",
        "concurrent", "load test", "recovery point", "container",
    ),
    "implementation plan": (
        "phase", "milestone", "timeline", "migration", "rehearsal", "uat",
        "cutover", "raci", "governance", "contingency", "pilot", "hypercare",
        "exit criterion", "rollout", "sign-off", "parallel running",
    ),
    "commercial value": (
        "fixed-price", "total cost", "cost of ownership", "price", "charges",
        "assumption", "payment", "licence", "subscription", "day rate",
        "value for money", "excludes", "valid for", "capital",
    ),
    "security & compliance": (
        "iso 27001", "soc 2", "encrypt", "aes-256", "tls", "penetration test",
        "audit", "role-based access", "rbac", "certification", "retention",
        "pseudonymis", "incident response", "in-country", "data protection",
    ),
    "support & experience": (
        "sla", "response target", "resolution target", "service delivery manager",
        "support", "reference", "delivered", "training", "account manager",
        "escalation", "service credit", "24x7", "helpdesk", "client since",
    ),
}

_STOPWORDS = {
    "and", "the", "for", "with", "that", "this", "from", "how", "are", "its",
    "overall", "their", "which", "into", "across", "within", "relevant", "past",
    "demonstrated", "proposed", "solution", "named", "stated", "including",
}


def _keywords_for(criterion: Criterion) -> tuple[str, ...]:
    """Seeded criteria use a curated list; user-added ones use their description."""
    known = MOCK_KEYWORDS.get(criterion.name.strip().lower())
    if known:
        return known
    words = re.findall(r"[a-z][a-z-]{4,}", criterion.description.lower())
    unique: list[str] = []
    for word in words:
        if word not in _STOPWORDS and word not in unique:
            unique.append(word)
    return tuple(unique[:14]) or (criterion.name.strip().lower(),)


MIN_USEFUL_QUOTE = 60   # a quote shorter than this is not worth citing


def _best_evidence(text: str, lowered: str, keywords: Sequence[str]) -> str:
    """Pick the first hit that yields a substantial quote, else the longest.

    Matching a bare table-header cell ("Phase") produces a technically correct
    but useless five-character quote, which the validator then refuses to
    verify. Preferring a full sentence keeps the offline provider's evidence
    as checkable as a real model's.
    """
    best = ""
    for keyword in keywords:
        quote = _evidence_for(text, lowered, keyword)
        if len(quote) >= MIN_USEFUL_QUOTE:
            return quote
        if len(quote) > len(best):
            best = quote
    return best


def _evidence_for(text: str, lowered: str, keyword: str) -> str:
    """Verbatim slice of `text` around the first hit, trimmed to one sentence."""
    position = lowered.find(keyword)
    if position == -1:
        return ""
    start = max(
        lowered.rfind(". ", 0, position) + 2,
        lowered.rfind("\n", 0, position) + 1,
        0,
    )
    end_candidates = [
        e for e in (lowered.find(". ", position), lowered.find("\n", position))
        if e != -1
    ]
    end = min(end_candidates) + 1 if end_candidates else min(len(text), position + 200)
    quote = text[start:end].strip()
    if len(quote) > 240:                      # keep the quote short but verbatim
        cut = quote.rfind(" ", 0, 240)
        quote = quote[: cut if cut > 80 else 240].strip()
    return quote


def mock_evaluate(
    supplier_name: str, document_text: str, criteria: Sequence[Criterion]
) -> str:
    """Score by counting indicative terms. Same input -> byte-identical output."""
    lowered = document_text.lower()
    results = []
    weakest: list[tuple[float, str]] = []

    for criterion in criteria:
        keywords = _keywords_for(criterion)
        hits = [k for k in keywords if k in lowered]
        # Full marks require roughly 80% of the indicative terms to appear, so
        # a merely competent proposal does not top out the scale.
        target = max(3, math.ceil(len(keywords) * 0.8))
        coverage = min(1.0, len(hits) / target)
        score = round(criterion.max_score * coverage * 2) / 2   # nearest half point

        if hits:
            evidence = _best_evidence(document_text, lowered, hits) or \
                prompts.SENTINEL_NO_EVIDENCE
            justification = (
                f"Matched {len(hits)} of {len(keywords)} indicative terms for "
                f"{criterion.name}: {', '.join(hits[:6])}."
            )
        else:
            score = 0.0
            evidence = prompts.SENTINEL_NO_EVIDENCE
            justification = (
                f"No indicative terms for {criterion.name} were found in the document."
            )

        weakest.append((score / criterion.max_score, criterion.name))
        results.append({
            "criterion_id": criterion.criterion_id,
            "score": score,
            "max_score": criterion.max_score,
            "justification": justification,
            "evidence": evidence,
        })

    weakest.sort()
    risks = [
        f"Limited detail on {name} relative to the other criteria assessed."
        for ratio, name in weakest[:2] if ratio < 0.8
    ] or ["No criterion scored materially below the others."]

    mean = sum(r["score"] / c.max_score for r, c in zip(results, criteria)) / len(criteria)
    return json.dumps({
        "supplier_name": supplier_name,
        "criteria": results,
        "risks": risks,
        "overall_summary": (
            f"Offline keyword assessment of {supplier_name}: average coverage "
            f"{mean * 100:.0f}% across {len(criteria)} criteria. Scores reflect the "
            "presence of indicative terms only, not editorial judgement."
        ),
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# fault injection
# ---------------------------------------------------------------------------
def corrupt_response(raw: str, criteria: Sequence[Criterion]) -> str:
    """Apply six well-known defects; the validator should report five warnings.

    1. out-of-range score 14        -> CLIPPED
    2. non-numeric score "eight"    -> DEFAULTED_INVALID
    3. a criterion removed          -> DEFAULTED_MISSING
    4. an unknown criterion_id 99   -> dropped
    5. a duplicated criterion       -> later copy discarded
    6. wrapped in markdown fences   -> stripped silently, no warning
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return "```json\n" + raw + "\n```"

    items = payload.get("criteria") or []
    if len(items) >= 3:
        items[0]["score"] = 14                      # 1
        items[1]["score"] = "eight"                 # 2
        removed = items.pop(2)                      # 3
        payload.setdefault("_removed_for_demo", removed.get("criterion_id"))
    if items:
        items.append({                              # 4
            "criterion_id": 99, "score": 9, "max_score": 10,
            "justification": "Criterion that does not exist in the database.",
            "evidence": "Fault injection demo.",
        })
        duplicate = dict(items[0])                  # 5
        duplicate["score"] = 1
        duplicate["justification"] = "Duplicate entry produced by fault injection."
        items.append(duplicate)

    payload["criteria"] = items
    payload.pop("_removed_for_demo", None)
    return "```json\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n```"  # 6


# ---------------------------------------------------------------------------
# the agent
# ---------------------------------------------------------------------------
class EvaluationAgent:
    """Wraps one LLM provider behind a single ``evaluate`` call."""

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        fault: str | None = None,
    ) -> None:
        self.provider = (provider or config.get_provider()).strip().lower()
        self.model = (model or config.get_model(self.provider)).strip()
        self.base_url = base_url if base_url is not None else config.get_base_url()
        self.api_key = api_key if api_key is not None else config.get_api_key(self.provider)
        self.fault = fault if fault in FAULT_MODES else None
        self._client = None

        if self.provider not in ("openai", "anthropic", "mock"):
            raise EvaluationError(
                f"Unknown provider '{self.provider}'. Use openai, anthropic or mock."
            )
        if self.provider == "mock" and not self.model:
            self.model = config.DEFAULT_MOCK_MODEL
        if self.provider != "mock":
            if not self.api_key:
                raise EvaluationError(
                    f"No API key found for provider '{self.provider}'. Set LLM_API_KEY "
                    "in your environment or in Streamlit secrets."
                )
            if not self.model:
                raise EvaluationError(
                    "No model configured. Set LLM_MODEL (list the provider's /models "
                    "endpoint first -- providers retire models without notice)."
                )

    @property
    def description(self) -> str:
        where = f" via {self.base_url}" if self.base_url else ""
        return f"{self.provider}:{self.model}{where}"

    @property
    def is_mock(self) -> bool:
        return self.provider == "mock"

    # -- provider calls ----------------------------------------------------
    def _openai_client(self):
        if self._client is None:
            from openai import OpenAI

            kwargs: dict[str, Any] = {
                "api_key": self.api_key,
                "max_retries": config.LLM_CLIENT_MAX_RETRIES,
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def _call_openai(self, system: str, user: str) -> str:
        client = self._openai_client()
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            response = client.chat.completions.create(
                model=self.model,
                temperature=config.LLM_TEMPERATURE,
                response_format={"type": "json_object"},
                messages=messages,
            )
        except Exception as exc:  # noqa: BLE001
            # Some gateways (Groq) validate JSON mode server-side and reject the
            # whole completion with a 400, returning the text in
            # `failed_generation`. Our own parser is more forgiving than that
            # validator -- it strips fences and surrounding prose -- so the best
            # move is to ask again WITHOUT JSON mode and parse the reply
            # ourselves. Only if that also fails do we fall back to the
            # salvaged text and let the normal repair-retry path deal with it.
            salvaged = _failed_generation(exc)
            if salvaged is None and "response_format" not in str(exc):
                raise EvaluationError(str(exc)) from exc
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    temperature=config.LLM_TEMPERATURE,
                    messages=messages,
                )
            except Exception as retry_exc:  # noqa: BLE001
                salvaged = salvaged or _failed_generation(retry_exc)
                if salvaged is not None:
                    return salvaged
                raise EvaluationError(str(retry_exc)) from retry_exc
        return response.choices[0].message.content or ""

    def _call_anthropic(self, system: str, user: str) -> str:
        from anthropic import Anthropic

        if self._client is None:
            self._client = Anthropic(
                api_key=self.api_key, max_retries=config.LLM_CLIENT_MAX_RETRIES
            )
        try:
            message = self._client.messages.create(
                model=self.model,
                max_tokens=4096,
                temperature=config.LLM_TEMPERATURE,
                system=system,
                messages=[
                    {"role": "user", "content": user},
                    # Prefilling the opening brace is how this SDK is steered
                    # into JSON; it has no response_format parameter.
                    {"role": "assistant", "content": "{"},
                ],
            )
        except Exception as exc:  # noqa: BLE001
            raise EvaluationError(str(exc)) from exc
        return "{" + "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        )

    # -- public API --------------------------------------------------------
    def evaluate(
        self,
        supplier_name: str,
        document_text: str,
        criteria: Sequence[Criterion],
        *,
        attempt: int = 1,
        previous_response: str | None = None,
        apply_fault: bool = False,
    ) -> AgentCall:
        """Score one supplier. ``attempt`` 2 sends the JSON repair prompt."""
        faulted = bool(apply_fault and self.fault)

        if faulted and self.fault == "invalid_json_always":
            return AgentCall(supplier_name, attempt, self.provider, self.model,
                             GARBAGE_RESPONSE, faulted=True)
        if faulted and self.fault == "invalid_json_once" and attempt == 1:
            return AgentCall(supplier_name, attempt, self.provider, self.model,
                             GARBAGE_RESPONSE, faulted=True)

        user = prompts.build_user_prompt(supplier_name, document_text, criteria)
        if attempt > 1 and previous_response is not None:
            user = user + "\n\n" + prompts.build_repair_prompt(
                previous_response, len(criteria)
            )

        if self.provider == "mock":
            raw = mock_evaluate(supplier_name, document_text, criteria)
        elif self.provider == "anthropic":
            raw = self._call_anthropic(prompts.SYSTEM_PROMPT, user)
        else:
            raw = self._call_openai(prompts.SYSTEM_PROMPT, user)

        if faulted and self.fault == "malformed_values":
            raw = corrupt_response(raw, criteria)

        return AgentCall(
            supplier_name=supplier_name,
            attempt=attempt,
            provider=self.provider,
            model=self.model,
            raw=raw,
            faulted=faulted,
            prompt_chars=len(user),
        )
