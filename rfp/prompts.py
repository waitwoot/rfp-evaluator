"""Prompt construction.

The criteria block is built from the database at run time, so editing a
criterion in the UI changes what the model is asked on the very next run --
nothing about the criteria is hard-coded here.

Weights are deliberately NOT sent to the model. The model's job is to judge
one criterion at a time against the evidence in front of it; how much that
criterion matters to the buyer is a commercial decision that belongs to the
ranking tool, in Python. Telling the model that Technical Capability is worth
30% invites it to inflate scores on the criteria it believes are important.
"""

from __future__ import annotations

from typing import Sequence

from rfp.db import Criterion

SENTINEL_NO_EVIDENCE = "No evidence found in document"

SYSTEM_PROMPT = """\
You are a procurement evaluation assistant for a public sector buying team.

You read ONE supplier's RFP response and score it against the buyer's
criteria. You are rigorous, sceptical and evidence-driven. A confident claim
with nothing to back it up is not evidence.

Absolute rules:
1. Use ONLY what is written in the supplied document. Never use outside
   knowledge about the supplier, and never infer a capability that the
   document does not state.
2. Return EXACTLY one result for each criterion listed, no more and no fewer.
3. Every score must be a number within that criterion's stated range.
4. "evidence" must be a SHORT VERBATIM QUOTE copied character-for-character
   from the document. Do not paraphrase, summarise, correct or tidy it.
5. If the document contains no evidence for a criterion, score it 0 and set
   evidence to exactly "{sentinel}".
6. Reply with a single JSON object and nothing else. No prose before it, no
   explanation after it, no markdown code fences.
""".format(sentinel=SENTINEL_NO_EVIDENCE)


def format_criteria_block(criteria: Sequence[Criterion]) -> str:
    """Render the active criteria for the prompt. Weights are omitted."""
    lines = []
    for c in criteria:
        lines.append(
            f"- criterion_id: {c.criterion_id}\n"
            f"  name: {c.name}\n"
            f"  what to inspect: {c.description}\n"
            f"  score range: 0 to {c.max_score:g} (whole or half numbers)"
        )
    return "\n".join(lines)


def build_user_prompt(
    supplier_name: str,
    document_text: str,
    criteria: Sequence[Criterion],
) -> str:
    schema_example = (
        '{\n'
        '  "supplier_name": "string",\n'
        '  "criteria": [\n'
        '    {"criterion_id": <int>, "score": <number>, "max_score": <number>,\n'
        '     "justification": "one or two sentences explaining the score",\n'
        '     "evidence": "short verbatim quote from the document"}\n'
        '  ],\n'
        '  "risks": ["specific risk this proposal presents to the buyer"],\n'
        '  "overall_summary": "two or three sentences"\n'
        '}'
    )
    return f"""\
SUPPLIER UNDER EVALUATION: {supplier_name}

CRITERIA TO SCORE (return exactly {len(criteria)} results, one per criterion):
{format_criteria_block(criteria)}

OUTPUT SHAPE (JSON only):
{schema_example}

Notes on scoring:
- Judge each criterion independently, on this document alone.
- A specific, checkable commitment ("ISO 27001 certified, audited March 2026")
  scores higher than a vague assurance ("we follow industry best practice").
- Absence of detail is a reason to score low, not a reason to assume the best.
- "risks" are concrete risks this proposal creates for the buyer, drawn from
  what the document does and does not say.

=== BEGIN SUPPLIER DOCUMENT ===
{document_text}
=== END SUPPLIER DOCUMENT ===
"""


def build_repair_prompt(previous_response: str, criteria_count: int) -> str:
    """Sent once, after an unparseable response, before giving up on a supplier."""
    excerpt = (previous_response or "")[:600]
    return f"""\
Your previous reply could not be parsed as JSON.

Reply again with ONLY the JSON object described earlier: one object, exactly
{criteria_count} entries in "criteria", no markdown fences, no commentary
before or after it. Do not apologise or explain -- output the JSON only.

Your previous reply began:
{excerpt}
"""
