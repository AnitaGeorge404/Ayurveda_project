# Architecture

```mermaid
flowchart TD
    Q[User Question] --> QA[Question Analyzer<br/>app/question_analysis.py]
    QA -->|entities + intent, rule-based| ENT[Entity Index<br/>app/normalization.py<br/>built from live Neo4j vocabulary]
    QA -->|no known entity, no domain keyword| REFUSE_OOD[OUT_OF_DOMAIN]

    QA --> RET[Retrieval<br/>app/retrieval.py]
    RET --> CYP[Structured Cypher retrieval<br/>app/graph_store.py]
    RET -->|only if no structured hit| SEM[Semantic TF-IDF fallback<br/>candidate retrieval only]
    CYP --> NEO[(Neo4j Graph<br/>source of truth)]
    SEM --> NEO

    RET --> EV[Evidence object]
    EV --> VAL{Evidence Validator<br/>app/evidence.py}
    VAL -->|no records| REFUSE_INS[INSUFFICIENT_EVIDENCE]
    VAL -->|structured hit, or semantic score >= threshold| LLM

    LLM[Optional LLM Generation<br/>app/llm_generation.py<br/>strict system prompt, evidence-only] --> GR{Grounding Validator<br/>app/grounding.py<br/>deterministic: every named entity<br/>in the answer must be in the evidence}
    GR -->|fails| REFUSE_GR[Refuse: not reliably grounded]
    GR -->|passes, or LLM disabled -> deterministic template| ANSWER[Final grounded answer + evidence + sources]

    REFUSE_OOD --> OUT[Response to user]
    REFUSE_INS --> OUT
    REFUSE_GR --> OUT
    ANSWER --> OUT
```

## Why each stage exists

1. **Question Analyzer / Entity Index** — deterministic keyword + known-vocabulary
   matching (`app/question_analysis.py`, `app/normalization.py`). The domain
   vocabulary is small and fully enumerable from the graph, so a rule-based
   classifier is both sufficient and fully auditable — there is no opaque
   intent classifier that could silently generalize past the dataset.
2. **Structured retrieval first** (`app/retrieval.py`, `app/graph_store.py`) —
   every list/lookup/aggregation question is answered by a parametrized
   Cypher query. Semantic (TF-IDF) retrieval only runs when no deterministic
   query intent matched, and its hits are candidates, not proof.
3. **Evidence Validator** (`app/evidence.py`) — the single gate the LLM must
   pass through. If it says insufficient, `app/pipeline.py` returns the
   refusal directly and **never calls the LLM**.
4. **Optional LLM Generation** (`app/llm_generation.py`) — only phrasing, only
   given the retrieved evidence, under a strict "evidence is the only source
   of truth" system prompt. If no API key is configured, a deterministic
   template produces the answer instead — the system is fully functional
   without an LLM.
5. **Grounding Validator** (`app/grounding.py`) — independently re-checks the
   LLM's output: every dataset entity name it mentions must appear in the
   evidence actually retrieved for this question. This is deterministic
   (string/vocabulary matching), not another LLM call grading itself.

See `README.md` for the three refusal modes and example Q&A, and
`DATA_CLEANING.md` for how the raw spreadsheet became this graph schema.
