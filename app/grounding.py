"""
Step 11: deterministic grounding validation.

Rather than trusting the LLM's own claim that it stuck to the evidence, we
independently check its output: every known-vocabulary entity name (herb,
pathology, physiological function, action, reference -- anything that exists
anywhere in the graph) that appears in the LLM's answer must also appear in
the evidence actually retrieved for this question. If the LLM mentions a real
dataset entity that was NOT part of its evidence, that is a hallucination
(it reached for outside/adjacent knowledge) and the answer is rejected.
"""
from __future__ import annotations

import re

from app.normalization import EntityIndex
from app.schemas import Evidence


def _mentioned_known_entities(text: str, index: EntityIndex) -> set[str]:
    lower = text.lower()
    found = set()
    for form in index.known_names():
        if len(form) < 3:
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(form) + r"(?![a-z0-9])", lower):
            canonical, _type = index.resolve(form)
            found.add(canonical)
    return found


def _evidence_entity_names(evidence: Evidence) -> set[str]:
    names = set()
    for r in evidence.records:
        names.add(r.subject)
        if r.retrieval_method == "structured":
            names.add(r.value)
    return names


def is_grounded(answer_text: str, evidence: Evidence, index: EntityIndex) -> tuple[bool, str]:
    mentioned = _mentioned_known_entities(answer_text, index)
    allowed = _evidence_entity_names(evidence)
    unsupported = {m for m in mentioned if m not in allowed}
    if unsupported:
        return False, f"answer mentions entities not present in retrieved evidence: {sorted(unsupported)}"
    return True, ""
