"""FastAPI 진입점.

실행: uv run uvicorn timeable.api.main:app --reload
문서: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router

app = FastAPI(title="TimeAble API")

# 프론트(Next.js)에서 브라우저가 직접 호출하므로 CORS 허용.
# Plan 3/배포에서 allow_origins 를 실제 도메인으로 좁힌다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
