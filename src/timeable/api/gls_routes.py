"""GLS 시간표 import 라우트 (2단계 OTP).

흐름:
    POST /me/gls/import      → 202 OTP_REQUIRED{attempt_id} | 200 IMPORTED
    POST /me/gls/import/otp  → 200 IMPORTED

로그인은 login_flow 레지스트리의 워커 스레드에서 돌고, 성공 시 run 클로저가
busy 격자를 Supabase `members`에 저장한다. 비밀번호는 run 밖으로 안 나간다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from ..gls import importer
from ..gls.http import GLSError
from ..gls.login_flow import DONE, ERROR, OTP_REQUESTED, AttemptNotFound, LoginRegistry
from . import db
from .auth import current_user_id
from .schemas import ImportRequest, OtpRequest

router = APIRouter(prefix="/me/gls", tags=["gls"])
_registry = LoginRegistry()


def _resolve(status: tuple, attempt_id: str | None = None) -> JSONResponse:
    kind, payload = status
    if kind == OTP_REQUESTED:
        return JSONResponse({"status": "OTP_REQUIRED", "attempt_id": attempt_id}, status_code=202)
    if kind == DONE:
        return JSONResponse({"status": "IMPORTED", **payload}, status_code=200)
    # ERROR: GLSError 메시지는 사용자 안전(자격증명 미포함). 그 외는 숨긴다.
    if isinstance(payload, GLSError):
        raise HTTPException(status_code=400, detail=str(payload))
    raise HTTPException(status_code=500, detail="import failed")


@router.post("/import")
def start_import(body: ImportRequest, user_id: str = Depends(current_user_id)) -> JSONResponse:
    def run(ask):
        result = importer.import_timetable_busy(
            body.gls_id, body.gls_pw, ask, year=body.year, semester=body.semester,
        )
        db.save_member(body.group_id, user_id, result["busy"])
        return {"group_id": body.group_id, "courses": result["courses"]}

    attempt_id, status = _registry.start(run, meta={"user_id": user_id, "group_id": body.group_id})
    return _resolve(status, attempt_id)


@router.post("/import/otp")
def submit_import_otp(body: OtpRequest, user_id: str = Depends(current_user_id)) -> JSONResponse:
    try:
        status = _registry.submit_otp(body.attempt_id, body.code)
    except AttemptNotFound:
        raise HTTPException(status_code=410, detail="attempt expired or not found")
    return _resolve(status)
