"""
Vercel entrypoint. Vercel's Python runtime detects an ASGI-compatible `app`
object exported from a file under api/ and serves it as a serverless
function. All actual routes (/api/ask, /api/health) are defined in
app/main.py so the exact same code path runs locally (`uvicorn app.main:app`)
and on Vercel -- this file only re-exports it.
"""
import sys
from pathlib import Path

# Belt-and-braces: make sure the repo root (parent of this api/ directory) is
# importable as `app`, regardless of Vercel's working directory / packaging.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402,F401
