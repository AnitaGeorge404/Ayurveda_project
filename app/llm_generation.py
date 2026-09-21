"""
Step 10: answer generation. Two modes:

1. Deterministic template (always available, zero external dependency) --
   this is what Step 12 of the spec's example output looks like, and is the
   default and fallback.
2. Optional LLM rewrite via the Gemini API, ONLY invoked when the evidence
   validator has already said ANSWERABLE, and its output is re-checked by
   app.grounding before it is ever shown to the user.

The LLM is never given the question without evidence, and is never allowed
to be the thing that decides whether evidence is sufficient.
"""
from __future__ import annotations

from app.schemas import Evidence
from app import config

SYSTEM_PROMPT = """You are a closed-domain question-answering system.
You must answer ONLY using the supplied evidence.
The evidence is the only source of truth.
Do not use pretrained knowledge.
Do not use general world knowledge.
Do not infer unsupported scientific facts.
Do not invent relationships.
Do not introduce information that is not explicitly supported by the evidence.
If the evidence does not sufficiently answer the question, output exactly:
INSUFFICIENT_EVIDENCE"""


def _group_by_subject_predicate(evidence: Evidence):
    groups: dict[tuple[str, str], list[str]] = {}
    for r in evidence.records:
        if r.retrieval_method != "structured":
            continue
        groups.setdefault((r.subject, r.predicate), []).append(r.value)
    return groups


PREDICATE_PHRASING = {
    "HAS_ACTION": "has the action(s)",
    "TREATS_PATHOLOGY": "is associated with treating",
    "AFFECTS_FUNCTION": "affects the physiological/functional aspect(s) of",
    "HAS_REFERENCE": "is referenced in",
    "IS_A": "in the dataset includes",
}


def deterministic_answer(evidence: Evidence) -> str:
    groups = _group_by_subject_predicate(evidence)
    if not groups:
        semantic = [r for r in evidence.records if r.retrieval_method == "semantic"]
        if semantic:
            lines = [f"- {r.subject}: {r.value} (similarity {r.score:.2f})" for r in semantic[:5]]
            return "The most closely related records found in the dataset:\n" + "\n".join(lines)
        return "INSUFFICIENT_EVIDENCE"

    sentences = []
    for (subject, predicate), values in groups.items():
        phrase = PREDICATE_PHRASING.get(predicate, predicate.replace("_", " ").lower())
        sentences.append(f"{subject} {phrase} {', '.join(sorted(set(values)))}.")
    return " ".join(sentences)


def _evidence_as_text(evidence: Evidence) -> str:
    lines = []
    for r in evidence.records:
        if r.retrieval_method == "structured":
            lines.append(f"{r.subject} [{r.predicate}] {r.value} (source: {r.source_file} row {r.source_row})")
        else:
            lines.append(f"{r.subject}: {r.value} (semantic similarity {r.score:.2f})")
    return "\n".join(lines)


def llm_answer(evidence: Evidence, target_language: str = "English") -> str | None:
    """Returns None if the LLM step is skipped (no API key, import error, or
    the LLM itself reports insufficient evidence) -- caller should fall back
    to deterministic_answer()."""
    if not config.GEMINI_API_KEY:
        return None
    try:
        from google import genai
    except ImportError:
        return None

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    user_content = (
        f"Question:\n{evidence.question}\n\n"
        f"Evidence:\n{_evidence_as_text(evidence)}"
    )
    
    sys_prompt = SYSTEM_PROMPT
    if target_language and target_language.upper() != "ENGLISH":
        sys_prompt += f"\nIMPORTANT: You must write your final answer in the {target_language} language."

    try:
        response = client.models.generate_content(
            model=config.LLM_MODEL,
            contents=user_content,
            config=genai.types.GenerateContentConfig(
                system_instruction=sys_prompt,
                max_output_tokens=400,
            )
        )
        text = response.text.strip() if response.text else ""
    except Exception:
        return None

    if not text or text == "INSUFFICIENT_EVIDENCE":
        return None
    return text

def translate_to_english(question: str) -> tuple[str, str]:
    """Translates the question to English and detects the language.
    Returns (english_translation, language_name). If translation fails, returns (question, 'English')."""
    if not config.GEMINI_API_KEY:
        return question, "English"
    try:
        from google import genai
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        prompt = (
            "You are a language detector and translator. "
            "If the following text is in English, reply exactly with: ENGLISH|{text}. "
            "If it is in another language, translate it to English and reply with: {Language Name}|{Translated Text}. "
            f"Text: {question}"
        )
        response = client.models.generate_content(
            model=config.LLM_MODEL,
            contents=prompt,
            config=genai.types.GenerateContentConfig(max_output_tokens=150)
        )
        text = response.text.strip() if response.text else ""
        if "|" in text:
            lang, translated = text.split("|", 1)
            return translated.strip(), lang.strip()
    except Exception:
        pass
    return question, "English"
