"""개수기반 핸들러 테스트.

실행: ``uv run python -m unittest discover -s tests``
작은 합성 데이터로 핵심 불변식을 못박는다.
"""

import unittest

from timeable.availability import free_counts, handler, top_candidates


def make_data() -> dict:
    """하루(Mon) 4칸, 학생 3명짜리 미니 데이터.

    칸:        0      1      2      3
    s1 busy:   T      F      F      F
    s2 busy:   T      T      F      F
    s3 busy:   F      F      F      T
    free수:    1      2      3      2
    """
    return {
        "days": ["Mon"],
        "start_hour": 9,
        "end_hour": 11,
        "slot_minutes": 30,
        "students": [
            {"id": "s1", "busy": [[True, False, False, False]]},
            {"id": "s2", "busy": [[True, True, False, False]]},
            {"id": "s3", "busy": [[False, False, False, True]]},
        ],
    }


class FreeCountsTest(unittest.TestCase):
    def test_counts_per_slot(self):
        self.assertEqual(free_counts(make_data()), [[1, 2, 3, 2]])


class HandlerTest(unittest.TestCase):
    def test_min_free_filters_slots(self):
        # 3명 모두 비는 칸은 칸 2 하나뿐.
        blocks = handler(make_data(), min_free=3)
        self.assertEqual(len(blocks), 1)
        b = blocks[0]
        self.assertEqual((b["start_slot"], b["end_slot"]), (2, 3))
        self.assertEqual(b["min_free"], 3)

    def test_blocks_are_contiguous_runs(self):
        # min_free=2 → 칸 1,2,3 이 하나의 연속 블록.
        blocks = handler(make_data(), min_free=2)
        self.assertEqual(len(blocks), 1)
        self.assertEqual((blocks[0]["start_slot"], blocks[0]["end_slot"]), (1, 4))

    def test_min_duration_drops_short_blocks(self):
        # 칸 2만 3명 → 길이 1. 최소 2칸을 요구하면 탈락.
        self.assertEqual(handler(make_data(), min_free=3, min_duration=2), [])

    def test_attendees_are_block_intersection(self):
        # 칸 1~3 블록: 내내 비는 공통 참석자는 s1뿐(s2는 칸1 바쁨, s3는 칸3 바쁨).
        block = handler(make_data(), min_free=2)[0]
        self.assertEqual(block["attendees"], ["s1"])
        self.assertEqual(block["attendance"], 1)

    def test_labels(self):
        block = handler(make_data(), min_free=3)[0]
        self.assertEqual(block["start_label"], "10:00")  # 칸 2 = 09:00 + 60분
        self.assertEqual(block["end_label"], "10:30")


class TopCandidatesTest(unittest.TestCase):
    def test_sorted_by_attendance_then_length(self):
        cands = top_candidates(make_data(), min_free=1, k=5)
        attendances = [c["attendance"] for c in cands]
        self.assertEqual(attendances, sorted(attendances, reverse=True))


if __name__ == "__main__":
    unittest.main()
