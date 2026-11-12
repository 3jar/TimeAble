"""API 응답 Pydantic 모델. 프론트 TS 가 이 shape 를 그대로 소비한다."""

from __future__ import annotations

from pydantic import BaseModel


class Block(BaseModel):
    """handler/top_candidates 가 돌려주는 가용성 블록."""

    day_index: int
    day: str
    start_slot: int
    end_slot: int
    length: int
    start_label: str
    end_label: str
    min_free: int
    attendees: list[str]
    attendance: int


class FieldResponse(BaseModel):
    """히트맵/지형용 스칼라 필드."""

    days: list[str]
    field: list[list[int]]  # [day][slot] = 창 내내 비는 공통 인원 수
    min_duration: int


class ImportRequest(BaseModel):
    """GLS 시간표 import 시작 요청."""

    group_id: str
    gls_id: str
    gls_pw: str
    year: int | None = None
    semester: str | None = None


class OtpRequest(BaseModel):
    """import 진행중 OTP 제출."""

    attempt_id: str
    code: str


class OtpRequired(BaseModel):
    status: str = "OTP_REQUIRED"
    attempt_id: str


class ImportResult(BaseModel):
    status: str = "IMPORTED"
    group_id: str
    courses: int
