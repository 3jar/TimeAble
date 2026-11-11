"""Tests for GLS timetable -> availability busy-grid bridge.

Uses real SUUP_YOIL_GYOSI samples from GLS dsGrdMain.
"""
from timeable.availability import free_counts, handler
from timeable.gls.grid import build_group, busy_from_rows, meetings_to_busy
from timeable.gls.parse import parse_meetings


def test_single_course_marks_overlapping_slots():
    # 공학컴퓨터프로그래밍: 화 09:00-10:15, 목 10:30-11:45
    busy = meetings_to_busy(parse_meetings("화09:00-10:15【83279】,목10:30-11:45【83279】"))
    tue = [i for i, b in enumerate(busy[1]) if b]
    thu = [i for i, b in enumerate(busy[3]) if b]
    assert tue == [0, 1, 2]       # 09:00-09:30, 09:30-10:00, 10:00-10:30
    assert thu == [3, 4, 5]       # 10:30-11:00, 11:00-11:30, 11:30-12:00
    assert not any(busy[0]) and not any(busy[2]) and not any(busy[4])


def test_grid_dimensions_default():
    busy = meetings_to_busy([])
    assert len(busy) == 5                 # 월~금
    assert all(len(row) == 24 for row in busy)  # 9~21시 / 30분 = 24칸
    assert not any(any(row) for row in busy)


def test_union_of_multiple_courses():
    rows = [
        {"SUUP_YOIL_GYOSI": "월09:00-10:15【1】,수10:30-11:45【1】"},  # 월0-2, 수3-5
        {"SUUP_YOIL_GYOSI": "월10:30-11:45【2】"},                    # 월3-5
    ]
    busy = busy_from_rows(rows)
    assert [i for i, b in enumerate(busy[0]) if b] == [0, 1, 2, 3, 4, 5]  # 월 합집합
    assert [i for i, b in enumerate(busy[2]) if b] == [3, 4, 5]           # 수


def test_weekend_and_out_of_range_skipped():
    # 토요일(day 5)은 5일 격자 밖 → 무시, 08:00 수업은 9시 이전 부분만 잘림
    busy = meetings_to_busy(parse_meetings("토09:00-10:00【9】,월08:00-09:30【9】"))
    assert not any(any(row) for row in busy[1:])  # 화~금 비어있고 토는 격자에 없음
    assert [i for i, b in enumerate(busy[0]) if b] == [0]  # 월 09:00-09:30만


def test_build_group_feeds_availability_core():
    students = [
        {"id": "a", "name": "A", "rows": [{"SUUP_YOIL_GYOSI": "월09:00-10:15【1】"}]},
        {"id": "b", "name": "B", "rows": [{"SUUP_YOIL_GYOSI": "월09:00-09:30【2】"}]},
    ]
    data = build_group(students)
    assert data["days"] == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    assert len(data["students"]) == 2
    # 월 09:00(slot0): 둘 다 수업 -> 자유 0명. 10:30(slot3): 둘 다 자유 -> 2명.
    counts = free_counts(data)
    assert counts[0][0] == 0
    assert counts[0][3] == 2
    # 월 오후는 둘 다 비어 블록으로 잡힘
    blocks = handler(data, min_free=2, min_duration=2)
    assert any(b["day"] == "Mon" and b["attendance"] == 2 for b in blocks)
