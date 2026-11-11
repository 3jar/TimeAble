"""그룹 데이터 로더.

Plan 1: 로컬 data/dummy_students.json 하나를 'dummy' 그룹으로 제공.
Plan 2: 이 모듈만 Supabase(Postgres) 조회로 교체하면 라우트는 그대로 동작한다.
"""

from __future__ import annotations

from pathlib import Path

from ..schedule import load
from .config import settings, supabase_configured

# src/timeable/api/db.py -> parents[3] = 저장소 루트
_DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "dummy_students.json"


class GroupNotFound(Exception):
    """존재하지 않는 group_id."""


def load_group(group_id: str) -> dict:
    """group_id 로 시간표 데이터 dict 를 돌려준다.

    Plan 1에서는 'dummy' 하나만 유효하다.
    """
    if group_id != "dummy":
        raise GroupNotFound(group_id)
    return load(_DATA_PATH)


def save_member(group_id: str, member_id: str, busy: list[list[bool]], *, name: str | None = None) -> None:
    """한 멤버의 busy 격자를 Supabase `members`에 upsert 한다.

    PK (group_id, id) 충돌 시 덮어쓴다. GLS import 결과를 저장하는 경로.
    """
    if not supabase_configured():
        raise RuntimeError("supabase not configured")
    from supabase import create_client

    client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    row = {"group_id": group_id, "id": member_id, "busy": busy}
    if name is not None:
        row["name"] = name
    client.table("members").upsert(row, on_conflict="group_id,id").execute()
