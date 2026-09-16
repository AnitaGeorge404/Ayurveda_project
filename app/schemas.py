from enum import Enum
from typing import Optional

from pydantic import BaseModel


class AnswerStatus(str, Enum):
    ANSWERABLE = "ANSWERABLE"
    OUT_OF_DOMAIN = "OUT_OF_DOMAIN"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class AskRequest(BaseModel):
    question: str


class EvidenceRecord(BaseModel):
    subject: str
    subject_type: str
    predicate: str
    value: str
    value_type: str
    source_file: Optional[str] = None
    source_row: Optional[str] = None
    retrieval_method: str = "structured"  # "structured" | "semantic"
    score: Optional[float] = None


class Evidence(BaseModel):
    question: str
    entities: list[str] = []
    intents: list[str] = []
    records: list[EvidenceRecord] = []

    def is_sufficient(self, threshold: float) -> bool:
        for r in self.records:
            if r.retrieval_method == "structured":
                return True
            if r.retrieval_method == "semantic" and r.score is not None and r.score >= threshold:
                return True
        return False


class AskResponse(BaseModel):
    status: AnswerStatus
    answer: str
    evidence: list[EvidenceRecord] = []
    sources: list[str] = []
