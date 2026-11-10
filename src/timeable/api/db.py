"""그룹 데이터 로더.

Plan 1: 로컬 data/dummy_students.json 하나를 'dummy' 그룹으로 제공.
Plan 2: 이 모듈만 Supabase(Postgres) 조회로 교체하면 라우트는 그대로 동작한다.
"""

from __future__ import annotations

from pathlib import Path

from ..schedule import load

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
