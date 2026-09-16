"""
Vercel entrypoint. Vercel's Python runtime detects an ASGI-compatible `app`
object exported from a file under api/ and serves it as a serverless
function. All actual routes (/api/ask, /api/health) are defined in
app/main.py so the exact same code path runs locally (`uvicorn app.main:app`)
and on Vercel -- this file only re-exports it.
"""
from app.main import app  # noqa: F401
