"""Supabase JWT 검증 의존성.

프론트(Next.js)가 Supabase Auth로 로그인 → 받은 access token(HS256, 프로젝트
JWT secret 서명)을 Authorization: Bearer 로 보낸다. FastAPI는 **검증만** 한다.
"""
from __future__ import annotations

import jwt
from fastapi import Header, HTTPException

from .config import settings


def current_user_id(authorization: str | None = Header(default=None)) -> str:
    """Bearer 토큰을 검증하고 Supabase user id(sub)를 돌려준다."""
    secret = settings.supabase_jwt_secret
    if not secret:
        raise HTTPException(status_code=503, detail="auth not configured")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid token")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="token has no subject")
    return sub
