from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.graph_store import Neo4jGraphStore
from app.normalization import EntityIndex
from app.pipeline import answer_question
from app.schemas import AskRequest, AskResponse

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"

app = FastAPI(title="Ayurveda GraphRAG QA (closed-domain)")

_state = {}


@app.on_event("startup")
def startup():
    store = Neo4jGraphStore()
    _state["store"] = store
    _state["index"] = EntityIndex(store)


@app.on_event("shutdown")
def shutdown():
    store = _state.get("store")
    if store:
        store.close()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    return answer_question(_state["store"], _state["index"], req.question)


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
