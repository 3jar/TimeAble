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
