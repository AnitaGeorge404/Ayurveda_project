"""
Wires together question analysis -> retrieval -> evidence validation ->
[refuse | optional LLM generation -> grounding validation] -> final answer.
This is the one place that encodes the full architecture diagram end to end,
kept separate from FastAPI so it is directly unit-testable.
"""
from __future__ import annotations

from app import grounding, llm_generation, question_analysis, retrieval
from app.evidence import validate
from app.graph_store import GraphStore
from app.normalization import EntityIndex
from app.schemas import AnswerStatus, AskResponse

REFUSAL_TEXT = {
    AnswerStatus.OUT_OF_DOMAIN: "This system only answers questions based on the provided dataset.",
    AnswerStatus.INSUFFICIENT_EVIDENCE: (
        "I cannot answer this reliably because the required information is not "
        "available in the provided dataset."
    ),
}

UNGROUNDED_TEXT = (
    "I cannot provide a reliable answer because the available dataset does not "
    "contain sufficient supporting information."
)


def _sources(evidence) -> list[str]:
    seen = []
    for r in evidence.records:
        if r.source_file and r.source_row:
            tag = f"{r.source_file} row {r.source_row}"
            if tag not in seen:
                seen.append(tag)
    return seen


def answer_question(store: GraphStore, index: EntityIndex, question: str) -> AskResponse:
    analysis = question_analysis.analyze(question, index)
    evidence = retrieval.retrieve(store, index, analysis)
    status = validate(analysis, evidence)

    if status != AnswerStatus.ANSWERABLE:
        return AskResponse(status=status, answer=REFUSAL_TEXT[status], evidence=[], sources=[])

    llm_text = llm_generation.llm_answer(evidence)
    if llm_text is not None:
        grounded, _reason = grounding.is_grounded(llm_text, evidence, index)
        if not grounded:
            return AskResponse(
                status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                answer=UNGROUNDED_TEXT,
                evidence=evidence.records,
                sources=_sources(evidence),
            )
        answer_text = llm_text
    else:
        answer_text = llm_generation.deterministic_answer(evidence)

    return AskResponse(
        status=AnswerStatus.ANSWERABLE,
        answer=answer_text,
        evidence=evidence.records,
        sources=_sources(evidence),
    )
