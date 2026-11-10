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


if __name__ == "__main__":
    unittest.main()
