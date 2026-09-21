"""
Step 5 of the pipeline: deterministic, rule-based question understanding.

Deliberately NOT a general NLU/NER model -- the domain vocabulary is small
and fully enumerable from the graph, so keyword + known-entity matching is
both sufficient and fully auditable (no black-box intent classifier that
could quietly generalize outside the dataset).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.normalization import EntityIndex

GREETINGS = {
    "hi", "hello", "hey", "yo", "sup", "howdy", "hiya",
    "how are you", "what's up", "who are you", "good morning",
    "good evening", "good afternoon", "thanks", "thank you", "bye",
}

DOMAIN_HINT_WORDS = {
    "herb", "herbs", "ayurved", "ayurveda", "medhya", "rasayana",
    "pharmacotherapeutic", "pharmacotherapeutics", "pathology", "pathological",
    "physiological", "dosha", "dhatu",
}


# Relations a user might plausibly ask about that our schema simply does not
# capture. Recognizing these explicitly (instead of silently falling back to
# a generic "describe this entity" answer) is what makes
# "What is the mechanism of compound X?" correctly refuse with
# INSUFFICIENT_EVIDENCE rather than answering a question that wasn't asked.
UNSUPPORTED_RELATION_KEYWORDS = [
    "mechanism", "compound", "compounds", "molecular", "molecule", "target",
    "pathway", "dose", "dosage", "side effect", "side effects", "toxicity",
    "contraindication", "gene", "protein", "receptor", "clinical trial",
    "bioavailability", "pharmacokinetics",
    # Preparation/usage questions: the dataset has no HAS_PREPARATION-style
    # relationship at all, so these must not fall back to a generic
    # "describe this entity" dump of unrelated relations (see meeting notes).
    "prepare", "preparation", "how to make", "how to use", "recipe",
    "formulation", "how is it made", "administer", "administration",
    "make", "manufacture", "extract"
]

INTENT_KEYWORDS = {
    "FIND_ACTIONS": ["action", "actions"],
    "FIND_PATHOLOGIES_TREATED": ["treat", "treats", "cure", "cures", "condition", "conditions",
                                  "disorder", "disorders", "disease", "diseases", "pathology",
                                  "pathological", "helps with", "used for"],
    "FIND_FUNCTIONS_AFFECTED": ["function", "functions", "physiological", "affects", "effect on",
                                 "influence"],
    "FIND_REFERENCES": ["reference", "references", "source", "sources", "cited", "citation",
                         "textual source", "classical text"],
    "LIST": ["list", "what are all", "which are all", "show me all", "enumerate"],
    "COUNT": ["how many"],
}

LIST_TARGET_TYPE = {
    "herb": "Herb", "herbs": "Herb",
    "category": "Category", "categories": "Category",
    "pathology": "Pathology", "pathologies": "Pathology", "conditions": "Pathology",
    "function": "PhysiologicalFunction", "functions": "PhysiologicalFunction",
    "physiological": "PhysiologicalFunction",
    "action": "Action", "actions": "Action",
    "reference": "Reference", "references": "Reference",
}


@dataclass
class QuestionAnalysis:
    question: str
    in_domain: bool
    intents: list[str] = field(default_factory=list)
    entities: list[tuple[str, str]] = field(default_factory=list)  # (canonical_name, type)
    list_target_type: str | None = None
    reason: str = ""


def _is_greeting_or_chitchat(text: str) -> bool:
    t = text.strip().lower().rstrip("!?. ")
    if t in GREETINGS:
        return True
    # very short, no dataset hint, no known punctuation of a real question
    return False


def analyze(question: str, index: EntityIndex) -> QuestionAnalysis:
    text = question.strip()
    lower = text.lower()

    if _is_greeting_or_chitchat(text):
        return QuestionAnalysis(question, in_domain=False, reason="conversational")

    entities = index.find_in_text(text)
    has_domain_hint = any(w in lower for w in DOMAIN_HINT_WORDS)

    intents = []
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            intents.append(intent)

    list_target_type = None
    if "LIST" in intents or "COUNT" in intents:
        for word, node_type in LIST_TARGET_TYPE.items():
            if re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", lower):
                list_target_type = node_type
                break

    in_domain = bool(entities) or has_domain_hint or list_target_type is not None

    if not in_domain:
        return QuestionAnalysis(text, in_domain=False, reason="no known dataset entity or domain keyword found")

    if any(kw in lower for kw in UNSUPPORTED_RELATION_KEYWORDS) and entities:
        # A recognized entity but a relation our graph doesn't model at all:
        # this must NOT fall back to a generic description of the entity.
        intents = ["UNSUPPORTED_RELATION"]
    elif not intents and entities:
        intents = ["DESCRIBE_ENTITY"]

    return QuestionAnalysis(
        question=text,
        in_domain=True,
        intents=intents or ["DESCRIBE_ENTITY"],
        entities=entities,
        list_target_type=list_target_type,
    )
