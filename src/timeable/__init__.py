"""TimeAble - 공통 빈 시간 지형도.

데이터 스키마와 개수기반 호출 핸들러를 제공한다.
"""

from .schedule import Timetable, load, slot_label
from .availability import free_counts, handler, top_candidates

__all__ = [
    "Timetable",
    "load",
    "slot_label",
    "free_counts",
    "handler",
    "top_candidates",
]
