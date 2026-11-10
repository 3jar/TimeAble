"""시간표 데이터 모델과 로더.

데이터의 원본(source of truth)은 JSON이다. 모든 함수는 평범한 dict(`data`)를
직접 받아 동작하므로, three.js 프론트가 같은 JSON을 그대로 fetch할 수 있다.
`Timetable`은 편의용 래퍼일 뿐이다.

데이터 스키마::

    {
      "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
      "start_hour": 9,          # 하루 시작 (포함)
      "end_hour": 21,           # 하루 끝 (제외)
      "slot_minutes": 30,       # 한 칸 길이(분)
      "students": [
        {
          "id": "s01",
          "name": "김민준",
          "dept": "컴퓨터공학",
          "year": 2,
          "color": "#4FA3D1",   # 캐릭터 색
          "busy": [[bool, ...], ...]  # [요일][칸], True = 수업/바쁨
        },
        ...
      ]
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


def slot_count(data: dict) -> int:
    """하루의 시간 칸 개수. 예: 9~21시, 30분 → 24칸."""
    hours = data["end_hour"] - data["start_hour"]
    return hours * 60 // data["slot_minutes"]


def day_count(data: dict) -> int:
    """요일 개수. 예: 월~금 → 5."""
    return len(data["days"])


def slot_label(data: dict, slot: int) -> str:
    """칸 인덱스를 'HH:MM' 시작 시각으로 바꾼다. 예: 0 → '09:00'."""
    minutes = data["start_hour"] * 60 + slot * data["slot_minutes"]
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def load(path: str | Path) -> dict:
    """JSON 파일에서 시간표 데이터를 읽어 dict로 돌려준다."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Timetable:
    """`data` dict를 감싸는 얇은 편의 래퍼."""

    data: dict

    @classmethod
    def load(cls, path: str | Path) -> "Timetable":
        return cls(load(path))

    @property
    def students(self) -> list[dict]:
        return self.data["students"]

    def slot_count(self) -> int:
        return slot_count(self.data)

    def day_count(self) -> int:
        return day_count(self.data)

    def slot_label(self, slot: int) -> str:
        return slot_label(self.data, slot)
