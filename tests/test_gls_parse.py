"""Tests for the GLS timetable meeting-string parser.

Strings are real SUUP_YOIL_GYOSI samples from GLS dsGrdMain.
"""
from timeable.gls.parse import Meeting, meetings_for_row, parse_meetings


def test_two_day_lecture():
    result = parse_meetings("화12:00-13:15【36207】,목13:30-14:45【36207】")
    assert result == [
        Meeting(day=1, day_kr="화", start=12 * 60, end=13 * 60 + 15, room="36207", tags=()),
        Meeting(day=3, day_kr="목", start=13 * 60 + 30, end=14 * 60 + 45, room="36207", tags=()),
    ]


def test_same_day_double_block_with_flip_tag():
    result = parse_meetings("금10:00-10:50【33301】,금11:00-11:50【33301】【1h(ON)+2h(OFF)】")
    assert len(result) == 2
    assert result[0] == Meeting(4, "금", 600, 650, "33301", ())
    assert result[1] == Meeting(4, "금", 660, 710, "33301", ("1h(ON)+2h(OFF)",))


def test_tag_with_inner_brackets():
    # 미분적분학: the flip-learning tag itself contains [4시간].
    result = parse_meetings("월10:30-11:45【62306】,수09:00-10:15【62306】【1h(ON)+3h(OFF)[4시간]】")
    assert result[1].room == "62306"
    assert result[1].tags == ("1h(ON)+3h(OFF)[4시간]",)


def test_morning_time_to_minutes():
    (meeting,) = parse_meetings("월09:00-10:15【83279】")
    assert (meeting.day, meeting.day_kr, meeting.start, meeting.end, meeting.room) == (
        0, "월", 540, 615, "83279",
    )


def test_empty_and_blank():
    assert parse_meetings("") == []
    assert parse_meetings("   ") == []


def test_meetings_for_row():
    row = {"SUUP_YOIL_GYOSI": "화09:00-10:15【83279】,목10:30-11:45【83279】", "HAKSU_NO": "DASF003"}
    result = meetings_for_row(row)
    assert [m.day_kr for m in result] == ["화", "목"]
    assert meetings_for_row({}) == []
