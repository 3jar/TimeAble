"""FastAPI 엔드포인트 계약 테스트.

실행: uv run python -m unittest discover -s tests
TestClient 는 httpx 기반이라 dev 의존성에 httpx 필요.
"""

import unittest

from fastapi.testclient import TestClient

from timeable.api.main import app
from timeable.api.db import GroupNotFound, load_group

client = TestClient(app)


class HealthTest(unittest.TestCase):
    def test_health_ok(self):
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})


class LoadGroupTest(unittest.TestCase):
    def test_dummy_group_loads_students(self):
        data = load_group("dummy")
        self.assertIn("students", data)
        self.assertEqual(data["days"], ["Mon", "Tue", "Wed", "Thu", "Fri"])
        self.assertGreater(len(data["students"]), 0)

    def test_unknown_group_raises(self):
        with self.assertRaises(GroupNotFound):
            load_group("nope")


class FieldEndpointTest(unittest.TestCase):
    def test_field_default_duration(self):
        resp = client.get("/groups/dummy/field")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["min_duration"], 1)
        self.assertEqual(len(body["days"]), 5)
        self.assertEqual(len(body["field"]), 5)       # 요일 5
        self.assertEqual(len(body["field"][0]), 24)   # 칸 24

    def test_field_unknown_group_404(self):
        resp = client.get("/groups/nope/field")
        self.assertEqual(resp.status_code, 404)


class AvailabilityEndpointTest(unittest.TestCase):
    def test_availability_returns_blocks(self):
        resp = client.get("/groups/dummy/availability", params={"min_free": 15, "min_duration": 2})
        self.assertEqual(resp.status_code, 200)
        blocks = resp.json()
        self.assertIsInstance(blocks, list)
        for b in blocks:
            self.assertGreaterEqual(b["length"], 2)
            self.assertGreaterEqual(b["min_free"], 15)
            self.assertIn("attendance", b)

    def test_availability_requires_min_free(self):
        resp = client.get("/groups/dummy/availability")
        self.assertEqual(resp.status_code, 422)  # min_free 필수

    def test_candidates_sorted_and_limited(self):
        resp = client.get("/groups/dummy/candidates", params={"min_free": 12, "k": 3})
        self.assertEqual(resp.status_code, 200)
        cands = resp.json()
        self.assertGreater(len(cands), 0)  # 더미 데이터에서 실제 후보가 나와야 정렬 검증이 의미가 있다
        self.assertLessEqual(len(cands), 3)
        attendances = [c["attendance"] for c in cands]
        self.assertEqual(attendances, sorted(attendances, reverse=True))

    def test_candidates_unknown_group_404(self):
        resp = client.get("/groups/nope/candidates", params={"min_free": 10})
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
