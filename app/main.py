from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from app.graph_store import Neo4jGraphStore
from app.normalization import EntityIndex
from app.pipeline import answer_question
from app.schemas import AskRequest, AskResponse

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"

app = FastAPI(title="Ayurveda GraphRAG QA (closed-domain)")

_state = {}


def get_store_and_index():
    """Lazy singleton instead of a startup event: this must work identically
    whether the app is run with `uvicorn` (where lifespan events fire) or as a
    Vercel serverless function (where they may not) -- and it doubles as
    connection reuse across warm serverless invocations on the same instance."""
    if "store" not in _state or "index" not in _state:
        store = Neo4jGraphStore()
        _state["store"] = store
        _state["index"] = EntityIndex(store)
    return _state["store"], _state["index"]


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/ask", response_model=AskResponse)
def ask(req: AskRequest):
    try:
        store, index = get_store_and_index()
        return answer_question(store, index, req.question)
    except HTTPException:
        raise
    except Exception as e:
        # Anything here is a deployment/connectivity problem (missing env var,
        # wrong credentials, unreachable host), never something caused by the
        # user's question -- surface the real reason instead of a bare 500 so
        # it's debuggable from the deployed site alone.
        raise HTTPException(status_code=503, detail=f"Graph database connection failed: {e}")


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
