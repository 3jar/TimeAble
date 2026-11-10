"""가용성 계산을 HTTP 로 노출하는 라우터."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..availability import attendance_field
from .db import GroupNotFound, load_group
from .schemas import FieldResponse

router = APIRouter()


def _load(group_id: str) -> dict:
    try:
        return load_group(group_id)
    except GroupNotFound:
        raise HTTPException(status_code=404, detail=f"group '{group_id}' not found")


@router.get("/groups/{group_id}/field", response_model=FieldResponse)
def get_field(group_id: str, min_duration: int = Query(1, ge=1)) -> FieldResponse:
    data = _load(group_id)
    return FieldResponse(
        days=data["days"],
        field=attendance_field(data, min_duration),
        min_duration=min_duration,
    )
