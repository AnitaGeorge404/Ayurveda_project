"""
Steps 6-9: structured (Cypher-backed) retrieval first, optional semantic
fallback second, then assembly into an Evidence object. No LLM is involved
anywhere in this file.
"""
from app.graph_store import GraphStore
from app.normalization import EntityIndex
from app.question_analysis import QuestionAnalysis
from app.schemas import Evidence, EvidenceRecord
from app import config

# entity types treated as "subject-like" (things that HAVE actions/pathologies/etc.)
SUBJECT_TYPES = {"Herb", "Category"}
# entity types treated as "object-like" (things a subject points AT) -> reverse-lookup intent
OBJECT_TYPES = {"Pathology", "PhysiologicalFunction", "Action", "Reference"}

INTENT_PREDICATE = {
    "FIND_ACTIONS": "HAS_ACTION",
    "FIND_PATHOLOGIES_TREATED": "TREATS_PATHOLOGY",
    "FIND_FUNCTIONS_AFFECTED": "AFFECTS_FUNCTION",
    "FIND_REFERENCES": "HAS_REFERENCE",
}


def _structured_retrieve(store: GraphStore, analysis: QuestionAnalysis) -> list[EvidenceRecord]:
    records: list[EvidenceRecord] = []

    if "LIST" in analysis.intents or "COUNT" in analysis.intents:
        if analysis.list_target_type:
            names = store.list_by_type(analysis.list_target_type)
            for n in names:
                records.append(EvidenceRecord(
                    subject=analysis.list_target_type, subject_type="ListQuery",
                    predicate="IS_A", value=n, value_type=analysis.list_target_type,
                    retrieval_method="structured",
                ))
            return records  # list/count intents are self-contained

    for name, node_type in analysis.entities:
        matched_any_intent = False
        for intent in analysis.intents:
            if intent == "UNSUPPORTED_RELATION":
                # Entity is known but the relation asked about isn't in our
                # schema at all -- deliberately yield zero records instead of
                # falling back to a generic description.
                matched_any_intent = True
                continue
            predicate = INTENT_PREDICATE.get(intent)
            if not predicate:
                continue
            matched_any_intent = True
            if node_type in SUBJECT_TYPES:
                rows = store.outgoing(name, predicate)
                for row in rows:
                    records.append(EvidenceRecord(
                        subject=name, subject_type=node_type, predicate=predicate,
                        value=row["value"], value_type=row["value_type"],
                        source_file=row.get("source_file"), source_row=row.get("source_row"),
                        retrieval_method="structured",
                    ))
            elif node_type in OBJECT_TYPES:
                rows = store.incoming(name, predicate)
                for row in rows:
                    records.append(EvidenceRecord(
                        subject=row["value"], subject_type=row["value_type"], predicate=predicate,
                        value=name, value_type=node_type,
                        source_file=row.get("source_file"), source_row=row.get("source_row"),
                        retrieval_method="structured",
                    ))

        if not matched_any_intent or "DESCRIBE_ENTITY" in analysis.intents:
            for row in store.describe(name):
                if row["direction"] == "outgoing":
                    records.append(EvidenceRecord(
                        subject=name, subject_type=node_type, predicate=row["predicate"],
                        value=row["value"], value_type=row["value_type"],
                        source_file=row.get("source_file"), source_row=row.get("source_row"),
                        retrieval_method="structured",
                    ))
                else:
                    records.append(EvidenceRecord(
                        subject=row["value"], subject_type=row["value_type"], predicate=row["predicate"],
                        value=name, value_type=node_type,
                        source_file=row.get("source_file"), source_row=row.get("source_row"),
                        retrieval_method="structured",
                    ))

    # de-duplicate
    seen = set()
    deduped = []
    for r in records:
        key = (r.subject, r.predicate, r.value, r.source_file, r.source_row)
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped


def _semantic_retrieve(store: GraphStore, question: str) -> list[EvidenceRecord]:
    """Lightweight TF-IDF candidate retrieval for questions that don't map to a
    deterministic Cypher intent (e.g. "information related to memory"). This is
    candidate retrieval only, never proof: every hit still carries a similarity
    score and is filtered against EVIDENCE_THRESHOLD by the evidence validator."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        return []

    corpus = store.text_corpus()
    if not corpus:
        return []

    texts = [c["text"] or "" for c in corpus]
    vectorizer = TfidfVectorizer(stop_words="english")
    try:
        matrix = vectorizer.fit_transform(texts + [question])
    except ValueError:
        return []
    sims = cosine_similarity(matrix[-1], matrix[:-1])[0]

    records = []
    for c, score in zip(corpus, sims):
        if score <= 0:
            continue
        records.append(EvidenceRecord(
            subject=c["name"], subject_type=c["type"], predicate="RELATED_TO",
            value=c["text"], value_type="SourceText",
            retrieval_method="semantic", score=float(score),
        ))
    records.sort(key=lambda r: r.score or 0, reverse=True)
    return records[:10]


def retrieve(store: GraphStore, index: EntityIndex, analysis: QuestionAnalysis) -> Evidence:
    records = _structured_retrieve(store, analysis)

    if not records and config.USE_SEMANTIC_RETRIEVAL and analysis.entities:
        records = _semantic_retrieve(store, analysis.question)

    return Evidence(
        question=analysis.question,
        entities=[f"{name} ({t})" for name, t in analysis.entities],
        intents=analysis.intents,
        records=records,
    )
