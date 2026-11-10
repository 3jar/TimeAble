"""attendance_field(히트맵 스칼라) 테스트.

실행: uv run python -m unittest discover -s tests
"""

import unittest

from timeable.availability import attendance_field, free_counts


def make_data() -> dict:
    """하루(Mon) 4칸, 학생 3명.

    칸:        0      1      2      3
    s1 busy:   T      F      F      F
    s2 busy:   T      T      F      F
    s3 busy:   F      F      F      T
    free수:    1      2      3      2
    free집합:  {s3}  {s1,s3} {s1,s2,s3} {s1,s2}
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


class AttendanceFieldTest(unittest.TestCase):
    def test_duration_1_equals_free_counts(self):
        data = make_data()
        self.assertEqual(attendance_field(data, 1), free_counts(data))

    def test_duration_2_is_window_intersection(self):
        # 칸0 창[0,2): {s3}&{s1,s3}={s3}=1
        # 칸1 창[1,3): {s1,s3}&{s1,s2,s3}={s1,s3}=2
        # 칸2 창[2,4): {s1,s2,s3}&{s1,s2}={s1,s2}=2
        # 칸3 창[3,5): ns=4 넘음 -> 0
        self.assertEqual(attendance_field(make_data(), 2), [[1, 2, 2, 0]])

    def test_duration_overflow_is_zero(self):
        # min_duration=4, ns=4: 칸0만 창[0,4) 유효(교집합 {}=0), 나머지 overflow -> 0.
        self.assertEqual(attendance_field(make_data(), 4), [[0, 0, 0, 0]])


if __name__ == "__main__":
    unittest.main()
