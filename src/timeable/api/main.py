"""FastAPI 진입점.

실행: uv run uvicorn timeable.api.main:app --reload
문서: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="TimeAble API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
