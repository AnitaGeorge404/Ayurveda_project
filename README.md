# Ayurveda / Medhya Rasayana — Closed-Domain GraphRAG QA

A strict closed-domain question-answering system over a Neo4j graph built
from an Ayurveda research spreadsheet. It **only** answers from what is
actually stored in the graph, and refuses everything else — see
[Hard requirements](#hard-requirements) below, all implemented.

See `ARCHITECTURE.md` for the full pipeline diagram and `DATA_CLEANING.md`
for how the raw spreadsheet was normalized into the graph schema.

## Hard requirements, and where they're implemented

| Requirement | Implementation |
|---|---|
| Never answer from LLM pretrained knowledge | `app/evidence.py` gates the LLM call entirely; `app/pipeline.py` only invokes `llm_generation.llm_answer()` after `AnswerStatus.ANSWERABLE` |
| Neo4j is the sole source of truth | All entity recognition (`app/normalization.py`) and retrieval (`app/retrieval.py`) query the live graph; nothing is hard-coded |
| No fine-tuning / training | Uses an existing hosted LLM (Anthropic API) purely for phrasing, optionally |
| Entity normalization with provenance | `data/canonical_entities.json` + `scripts/ingest_excel.py`, documented in `DATA_CLEANING.md` |
| Evidence threshold, configurable | `EVIDENCE_THRESHOLD` env var, used only for the semantic-retrieval fallback |
| Grounding validation | `app/grounding.py`, deterministic |
| 3 refusal modes | `AnswerStatus.{OUT_OF_DOMAIN, INSUFFICIENT_EVIDENCE, ANSWERABLE}` in `app/schemas.py` |
| No hard-coded credentials | `app/config.py` reads env vars only; `.env` is gitignored |

## Project layout

```
data/raw/                 original spreadsheet + pasted relationship export (untouched)
data/canonical_entities.json   manually curated alias/normalization map (auditable)
data/processed/           cleaned, provenance-carrying CSVs (output of scripts/ingest_excel.py)
scripts/ingest_excel.py   Step 1: Excel/text -> cleaned CSVs
scripts/load_neo4j.py     Step 2/4: CSVs -> Neo4j (idempotent MERGE, with constraints)
app/                      the QA system (see ARCHITECTURE.md)
frontend/                 chat UI (index.html + style.css + script.js), calls POST /api/ask
api/index.py              Vercel serverless entrypoint -- re-exports app/main.py's FastAPI app
vercel.json               routes /api/* to api/index.py; everything else serves frontend/ as static
tests/                    pytest suite + tests/run_eval.py (metrics)
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # fill in your real Neo4j credentials
```
`requirements.txt` is the slim runtime set (what Vercel actually installs for
the serverless function); `requirements-dev.txt` adds what only the ingestion
pipeline, tests, and eval script need (pandas, openpyxl, scikit-learn, pytest).

### 1. Clean & normalize the raw data

```bash
python scripts/ingest_excel.py
```
Writes `data/processed/nodes.csv` and `data/processed/edges.csv`. Re-run any
time `data/raw/*` or `data/canonical_entities.json` changes.

### 2. Load into Neo4j

```bash
python scripts/load_neo4j.py
```
Creates uniqueness constraints and `MERGE`s every node/relationship with
provenance (`source_file`, `source_row`, `source_text`). Safe to re-run.

### 3. Run the API + chat UI locally

```bash
uvicorn app.main:app --reload
```
Open http://localhost:8000 for the chat UI, or `POST /api/ask {"question": "..."}`.

### 4. Deploy to Vercel

The repo is already laid out for Vercel: `api/index.py` exposes the FastAPI
app as a serverless function, `vercel.json` routes `/api/*` to it, and
everything else (`frontend/`) is served as static files at the same domain
— one deploy, one URL, frontend and backend together.

```bash
npm i -g vercel     # if you don't have the CLI
vercel login
vercel               # from the repo root; accept the defaults (no framework preset needed)
```
Then set the environment variables Vercel will need at runtime — either in
the dashboard (Project → Settings → Environment Variables) or via CLI:
```bash
vercel env add NEO4J_URI
vercel env add NEO4J_USERNAME
vercel env add NEO4J_PASSWORD
vercel env add NEO4J_DATABASE
# optional:
vercel env add ANTHROPIC_API_KEY
```
Redeploy after adding env vars (`vercel --prod`). The same live database is
used — nothing about the graph or the answers changes, only where the API
is hosted. `.vercelignore` excludes the raw/processed data files, scripts,
and tests from the deployed bundle (Neo4j is queried live; nothing needs to
ship with the function).

> Cold-start note: `app/main.py` initializes the Neo4j driver lazily on the
> first request per warm serverless instance (`get_store_and_index()`), not
> via a startup event — this works the same whether the app is run under
> `uvicorn` or invoked as a Vercel function, where ASGI lifespan events
> aren't guaranteed to fire.

### 5. Run tests / evaluation

```bash
pytest tests/test_pipeline.py -v
python tests/run_eval.py        # writes tests/eval_report.json
```
The test suite and eval script run against `FakeGraphStore` (an in-memory
replica of `data/processed/*.csv`), so they don't require a live Neo4j
connection — useful for CI or offline development. The FastAPI app itself
always talks to real Neo4j (`app/graph_store.Neo4jGraphStore`).

> **Note on this build environment**: the sandbox this project was
> originally built in has network egress blocked for `*.databases.neo4j.io`
> (and `docs.google.com`), so `scripts/load_neo4j.py` and a live end-to-end
> API test against your Aura instance could not be executed from there. The
> code is written directly against the `neo4j` Python driver and was
> validated with the `FakeGraphStore` test double (36/36 tests passing,
> `tests/eval_report.json`) — run the two commands above from a machine/
> environment with outbound access to your database to complete the load.

## Example Cypher queries

```cypher
// All actions of a herb
MATCH (h:Herb {name: "Brahmi"})-[:HAS_ACTION]->(a:Action) RETURN a.name;

// Pathologies a herb treats, with provenance
MATCH (h:Herb {name: "Brahmi"})-[r:TREATS_PATHOLOGY]->(p:Pathology)
RETURN p.name, r.source_file, r.source_row;

// Which herbs affect a given physiological function (reverse lookup)
MATCH (h)-[:AFFECTS_FUNCTION]->(f:PhysiologicalFunction {name: "Smriti"})
RETURN h.name;

// Full profile of a herb, either direction
MATCH (h:Herb {name: "Vacha"})-[r]->(o) RETURN type(r), o.name;

// List every herb in the dataset
MATCH (h:Herb) RETURN h.name ORDER BY h.name;

// Count herbs per category-level relationship (e.g. Medhya Rasayana)
MATCH (c:Category {name: "Medhya Rasayana"})-[:AFFECTS_FUNCTION]->(f)
RETURN f.name;

// A term that exists as vocabulary but has no relationships at all
// (correctly triggers INSUFFICIENT_EVIDENCE at the API level)
MATCH (n {name: "Simhadi"}) OPTIONAL MATCH (n)-[r]-() RETURN n, r;
```

## Example Q&A

| Question | Status | Answer (abridged) |
|---|---|---|
| "What pathologies does Brahmi treat?" | `ANSWERABLE` | "Brahmi is associated with treating Anavasthita Citta, Apasmara, Budhibhramsha, ..." |
| "What actions does Vacha have?" | `ANSWERABLE` | "Vacha has the action(s) Vakvishudhi." |
| "Which herbs affect Smriti?" | `ANSWERABLE` | "Medhya Rasayana affects ... Smriti. Brahmi affects ... Smriti. Mandukaparni affects ... Smriti. ..." |
| "What does Giloy treat?" (alias of Guduchi) | `ANSWERABLE` | Same answer as querying "Guduchi" — alias resolved via `data/canonical_entities.json` |
| "What is the capital of France?" | `OUT_OF_DOMAIN` | "This system only answers questions based on the provided dataset." |
| "Hi" | `OUT_OF_DOMAIN` | "This system only answers questions based on the provided dataset." |
| "What is the mechanism of Brahmi?" | `INSUFFICIENT_EVIDENCE` | "I cannot answer this reliably because the required information is not available in the provided dataset." |
| "What is the mechanism of Simhadi?" (herb exists, zero relationships) | `INSUFFICIENT_EVIDENCE` | same |
| "What does Prabhava treat?" (real Ayurvedic pharmacology concept, vocabulary-only) | `INSUFFICIENT_EVIDENCE` | same |

Full machine-checked set: `tests/test_data/questions.json` (31 cases across
valid / out-of-domain / insufficient-evidence / hallucination-probe
categories), results in `tests/eval_report.json`.

## Evaluation metrics (from `tests/run_eval.py`, current dataset)

- Overall accuracy: 100% (36/36 pytest cases; 31/31 eval-script cases)
- Abstention accuracy (correctly refused when it should refuse): 100%
- Hallucination rate (wrongly answered when it should have refused): 0%
- Avg latency (structured retrieval, no LLM, in-process): ~1 ms

These numbers reflect the current small, hand-curated test set, not a
claim of general accuracy — extend `tests/test_data/questions.json` as the
dataset grows.

## Known limitations

- **Keyword-based intent detection can over-trigger.** E.g. "Is Brahmi FDA
  approved for Alzheimer's disease?" contains "disease", which triggers the
  `FIND_PATHOLOGIES_TREATED` intent and returns Brahmi's real (but
  unrelated-to-FDA-approval) treated-pathology list, rather than recognizing
  the question is really about regulatory approval. It does **not**
  fabricate an FDA claim — grounding still holds — it just answers a
  related-but-different question. See `tests/test_data/questions.json` for
  the documented case.
- **Semantic retrieval is TF-IDF, not a trained embedding model.** This was
  a deliberate choice to avoid pulling in a multi-hundred-MB
  sentence-transformers/torch dependency for a 9-herb prototype (see
  "DO NOT OVERENGINEER" in the project brief). To swap in real embeddings,
  replace `app/retrieval.py::_semantic_retrieve` with a
  `sentence-transformers` encoder + a vector index (Neo4j supports native
  vector indexes) — the rest of the pipeline (evidence validation, threshold,
  grounding) does not need to change.
- **Dataset is small.** 10 herbs/categories, ~180 edges. The two Google
  Sheets referenced in the original task could not be fetched (network
  egress to `docs.google.com` is blocked in the build sandbox) or fully
  uploaded; `data/raw/relationships_medhya.txt` is a partial paste covering
  the "Medhya" category. Re-run `scripts/ingest_excel.py` after dropping a
  fuller export into `data/raw/` to extend coverage — no code changes
  needed unless new herb name variants appear (add them to
  `data/canonical_entities.json`).

## Security

Credentials are read exclusively from environment variables
(`app/config.py`, `scripts/load_neo4j.py`) via `.env` (gitignored). See
`.env.example` for the required variables. Nothing in this repository
contains a real credential.
