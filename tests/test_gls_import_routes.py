"""Tests for GLS import routes — JWT auth + OTP 2-step flow (GLS/Supabase mocked)."""
import jwt
import pytest
from fastapi.testclient import TestClient

from timeable.api import db, main
from timeable.api.config import settings
from timeable.gls import importer
from timeable.gls.http import GLSError

SECRET = "test-jwt-secret"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "supabase_jwt_secret", SECRET)
    return TestClient(main.app)


def _auth(sub="user-1"):
    token = jwt.encode({"sub": sub, "aud": "authenticated"}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_import_requires_auth(client):
    r = client.post("/me/gls/import", json={"group_id": "g", "gls_id": "a", "gls_pw": "b"})
    assert r.status_code == 401


def test_import_rejects_bad_token(client):
    bad = jwt.encode({"sub": "x", "aud": "authenticated"}, "wrong-secret", algorithm="HS256")
    r = client.post(
        "/me/gls/import",
        json={"group_id": "g", "gls_id": "a", "gls_pw": "b"},
        headers={"Authorization": f"Bearer {bad}"},
    )
    assert r.status_code == 401


def test_import_no_otp_saves_and_returns(client, monkeypatch):
    saved = {}
    monkeypatch.setattr(
        importer, "import_timetable_busy",
        lambda *a, **k: {"busy": [[True]], "courses": 5, "year": 2026, "semester": "2"},
    )
    monkeypatch.setattr(
        db, "save_member",
        lambda group_id, member_id, busy, **k: saved.update(group_id=group_id, member_id=member_id, busy=busy),
    )

    r = client.post("/me/gls/import", json={"group_id": "g1", "gls_id": "a", "gls_pw": "b"}, headers=_auth("u9"))
    assert r.status_code == 200
    assert r.json() == {"status": "IMPORTED", "group_id": "g1", "courses": 5}
    assert saved == {"group_id": "g1", "member_id": "u9", "busy": [[True]]}


def test_import_otp_roundtrip(client, monkeypatch):
    saved = {}

    def fake_import(gls_id, gls_pw, ask, *, year=None, semester=None, grid_opts=None):
        code = ask("otp?")                 # OTP 요구 → suspend
        assert code == "1234"
        return {"busy": [[False]], "courses": 3, "year": 2026, "semester": "2"}

    monkeypatch.setattr(importer, "import_timetable_busy", fake_import)
    monkeypatch.setattr(db, "save_member", lambda *a, **k: saved.update(ok=True))

    r1 = client.post("/me/gls/import", json={"group_id": "g", "gls_id": "a", "gls_pw": "b"}, headers=_auth())
    assert r1.status_code == 202
    attempt_id = r1.json()["attempt_id"]

    r2 = client.post("/me/gls/import/otp", json={"attempt_id": attempt_id, "code": "1234"}, headers=_auth())
    assert r2.status_code == 200
    assert r2.json()["status"] == "IMPORTED"
    assert saved == {"ok": True}


def test_import_error_maps_to_400(client, monkeypatch):
    def boom(*a, **k):
        raise GLSError("킹고 로그인 미완료")

    monkeypatch.setattr(importer, "import_timetable_busy", boom)
    r = client.post("/me/gls/import", json={"group_id": "g", "gls_id": "a", "gls_pw": "b"}, headers=_auth())
    assert r.status_code == 400
    assert "킹고" in r.json()["detail"]


def test_otp_unknown_attempt(client):
    r = client.post("/me/gls/import/otp", json={"attempt_id": "nope", "code": "1234"}, headers=_auth())
    assert r.status_code == 410
