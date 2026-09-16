"""Step 9: evidence validation gate. If this says insufficient, the LLM is
never called -- this module is what prevents the LLM from ever answering
from outside knowledge."""
from __future__ import annotations

from app.question_analysis import QuestionAnalysis
from app.schemas import AnswerStatus, Evidence
from app import config


def validate(analysis: QuestionAnalysis, evidence: Evidence) -> AnswerStatus:
    if not analysis.in_domain:
        return AnswerStatus.OUT_OF_DOMAIN
    if evidence.is_sufficient(config.EVIDENCE_THRESHOLD):
        return AnswerStatus.ANSWERABLE
    return AnswerStatus.INSUFFICIENT_EVIDENCE
