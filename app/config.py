from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

NEO4J_URI = os.environ.get("NEO4J_URI", "")
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

# Similarity floor for the optional semantic-retrieval fallback. Candidate
# retrieval only -- records below this are treated as insufficient evidence.
# Configurable; not claimed to be a scientifically validated cutoff (see README).
EVIDENCE_THRESHOLD = float(os.environ.get("EVIDENCE_THRESHOLD", "0.80"))

# Optional LLM answer-generation step (architecture diagram marks it optional).
# If unset, the system falls back to a deterministic template answer built
# directly from the retrieved evidence -- still fully functional and grounded.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-5")

USE_SEMANTIC_RETRIEVAL = os.environ.get("USE_SEMANTIC_RETRIEVAL", "true").lower() == "true"
