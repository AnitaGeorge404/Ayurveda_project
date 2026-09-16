from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

def _env(key: str, default: str = "") -> str:
    """os.environ.get(key, default) only falls back when the key is *absent*
    -- a variable that exists but is set to an empty string (as some hosting
    dashboards store an unfilled optional field) still comes back as "".
    This treats blank-and-missing the same way."""
    return os.environ.get(key) or default


NEO4J_URI = _env("NEO4J_URI")
NEO4J_USERNAME = _env("NEO4J_USERNAME")
NEO4J_PASSWORD = _env("NEO4J_PASSWORD")
NEO4J_DATABASE = _env("NEO4J_DATABASE", "neo4j")

# Similarity floor for the optional semantic-retrieval fallback. Candidate
# retrieval only -- records below this are treated as insufficient evidence.
# Configurable; not claimed to be a scientifically validated cutoff (see README).
EVIDENCE_THRESHOLD = float(_env("EVIDENCE_THRESHOLD", "0.80"))

# Optional LLM answer-generation step (architecture diagram marks it optional).
# If unset, the system falls back to a deterministic template answer built
# directly from the retrieved evidence -- still fully functional and grounded.
GEMINI_API_KEY = _env("GEMINI_API_KEY")
LLM_MODEL = _env("LLM_MODEL", "gemini-2.5-flash")

USE_SEMANTIC_RETRIEVAL = _env("USE_SEMANTIC_RETRIEVAL", "true").lower() == "true"
