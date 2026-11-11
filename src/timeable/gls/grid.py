"""GLS 시간표 → availability 코어의 busy 격자 변환.

`timeable.gls.parse.Meeting`(요일·분단위 시각)을 TimeAble availability가 쓰는
``busy[day][slot]`` 격자로 바꾼다. 결과 dict는 `timeable.availability`의
`free_counts`/`handler`/`top_candidates`가 그대로 소비한다.

격자 밖(주말, 영업시간 밖)은 무시/클램프한다. 기본 격자는
``data/dummy_students.json`` 스키마(월~금, 9~21시, 30분)와 동일.
"""
from __future__ import annotations

from collections.abc import Iterable

from .parse import Meeting, meetings_for_row

DEFAULT_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
DEFAULT_START_HOUR = 9
DEFAULT_END_HOUR = 21
DEFAULT_SLOT_MINUTES = 30


def meetings_to_busy(
    meetings: Iterable[Meeting],
    *,
    day_count: int = len(DEFAULT_DAYS),
    start_hour: int = DEFAULT_START_HOUR,
    end_hour: int = DEFAULT_END_HOUR,
    slot_minutes: int = DEFAULT_SLOT_MINUTES,
) -> list[list[bool]]:
    """Meeting 리스트를 ``busy[day][slot]`` 격자로.

    한 칸 ``i`` 는 ``[base+i*slot, base+(i+1)*slot)`` 를 덮고, 그 구간과 조금이라도
    겹치는 수업이 있으면 True(바쁨)로 둔다. 격자 밖 요일/시간은 건너뛴다.
    """
    base = start_hour * 60
    span = end_hour * 60
    slots = (span - base) // slot_minutes
    grid = [[False] * slots for _ in range(day_count)]
    for m in meetings:
        if not (0 <= m.day < day_count):
            continue  # 주말 등 격자 밖 요일
        lo = max(m.start, base)
        hi = min(m.end, span)
        if hi <= lo:
            continue  # 영업시간과 안 겹침
        first = (lo - base) // slot_minutes
        last = (hi - base - 1) // slot_minutes  # 겹치는 마지막 칸(포함)
        for s in range(first, last + 1):
            if 0 <= s < slots:
                grid[m.day][s] = True
    return grid


def busy_from_rows(rows: Iterable[dict], **grid_kw) -> list[list[bool]]:
    """dsGrdMain 행들(한 학생의 수강목록) → 합쳐진 busy 격자."""
    meetings = [m for row in rows for m in meetings_for_row(row)]
    return meetings_to_busy(meetings, **grid_kw)


def build_group(
    students: Iterable[dict],
    *,
    days: list[str] | None = None,
    start_hour: int = DEFAULT_START_HOUR,
    end_hour: int = DEFAULT_END_HOUR,
    slot_minutes: int = DEFAULT_SLOT_MINUTES,
) -> dict:
    """GLS 수강목록들로 availability `data` dict 를 조립한다.

    Args:
        students: 각 원소는 ``{"id", "rows", [name/dept/year/color]}``.
            ``rows`` 는 그 학생의 dsGrdMain 행 리스트(각 행에 SUUP_YOIL_GYOSI).
        days/start_hour/end_hour/slot_minutes: 격자 스키마(기본 월~금 9~21시 30분).

    Returns:
        `free_counts`/`handler`/`top_candidates`가 바로 받는 데이터 dict.
    """
    days = list(days if days is not None else DEFAULT_DAYS)
    grid_kw = dict(day_count=len(days), start_hour=start_hour,
                   end_hour=end_hour, slot_minutes=slot_minutes)
    out = []
    for st in students:
        out.append({
            "id": st["id"],
            "name": st.get("name", ""),
            "dept": st.get("dept"),
            "year": st.get("year"),
            "color": st.get("color"),
            "busy": busy_from_rows(st.get("rows", []), **grid_kw),
        })
    return {
        "days": days,
        "start_hour": start_hour,
        "end_hour": end_hour,
        "slot_minutes": slot_minutes,
        "students": out,
    }
