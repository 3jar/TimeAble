"""Parse GLS timetable meeting strings (dsGrdMain.SUUP_YOIL_GYOSI).

Example inputs::

    "화09:00-10:15【83279】,목10:30-11:45【83279】"
    "금10:00-10:50【33301】,금11:00-11:50【33301】【1h(ON)+2h(OFF)】"

Each comma-separated block is ``<요일><HH:MM>-<HH:MM>`` followed by one or more
``【...】`` groups. An all-digit group is the room; the rest are tags (e.g.
flip-learning descriptors like ``1h(ON)+2h(OFF)``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

DAYS = "월화수목금토일"  # index 0 = 월(Mon) ... 6 = 일(Sun)

_BLOCK = re.compile(r"([월화수목금토일])(\d{1,2}:\d{2})-(\d{1,2}:\d{2})((?:【[^】]*】)*)")
_BRACKET = re.compile(r"【([^】]*)】")


@dataclass(frozen=True)
class Meeting:
    day: int                 # 0 = 월 ... 6 = 일
    day_kr: str              # "월"
    start: int               # minutes from midnight
    end: int                 # minutes from midnight
    room: str | None
    tags: tuple[str, ...]    # non-room 【...】 groups (e.g. flip-learning)


def _minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def parse_meetings(raw: str) -> list[Meeting]:
    """Return every meeting block in a SUUP_YOIL_GYOSI string.

    Empty or unrecognized input yields an empty list rather than raising.
    """
    meetings: list[Meeting] = []
    for day_kr, start, end, brackets in _BLOCK.findall(raw or ""):
        groups = _BRACKET.findall(brackets)
        room = next((g for g in groups if g.isdigit()), None)
        tags = tuple(g for g in groups if not g.isdigit())
        meetings.append(Meeting(
            day=DAYS.index(day_kr),
            day_kr=day_kr,
            start=_minutes(start),
            end=_minutes(end),
            room=room,
            tags=tags,
        ))
    return meetings


def meetings_for_row(row: dict) -> list[Meeting]:
    """Meetings for one dsGrdMain row returned by ``GLSClient.timetable``."""
    return parse_meetings(row.get("SUUP_YOIL_GYOSI", ""))
