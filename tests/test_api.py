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


if __name__ == "__main__":
    unittest.main()
