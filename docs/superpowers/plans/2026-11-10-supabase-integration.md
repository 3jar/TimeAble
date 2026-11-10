# Supabase Integration (Plan 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Supabase(Postgres)에서 그룹·멤버 시간표를 읽어 기존 계산 엔드포인트를 그대로 구동하고, HS256 Supabase JWT 검증으로 보호되는 멤버 시간표 쓰기(upsert) 엔드포인트를 추가한다.

**Architecture:** `load_group`을 저장소(Repository) 패턴 뒤로 넣는다. `SUPABASE_URL`이 설정되면 `SupabaseRepository`, 아니면 기존 `LocalJsonRepository`(오프라인 테스트·데모용). 계산 코어와 읽기 라우트는 **한 줄도 바뀌지 않는다**. 인증은 `pyjwt`로 Supabase가 서명한 JWT(HS256, aud=authenticated)를 검증하는 FastAPI 의존성으로 붙인다. 읽기 엔드포인트는 공개, 쓰기(멤버 upsert)는 보호.

**Tech Stack:** FastAPI, Pydantic, uv. 추가: `supabase`(파이썬 클라이언트), `pyjwt`, `pydantic-settings`. 테스트는 기존대로 `unittest` + FastAPI TestClient. supabase/ 마이그레이션은 Supabase CLI.

---

## 전제조건 (외부, 사람이 수행)

- Plan 1(PR #1)이 `main`에 머지된 뒤 `main`에서 `feat/supabase-integration` 브랜치를 딴다.
- 실제 Supabase 프로젝트가 필요하다(Task 2·5의 적용/수동 검증 단계). 유닛 테스트는 Supabase 없이 오프라인으로 통과한다.
- Supabase 대시보드 → Settings에서 다음을 확보해 **`.env.local`**(gitignore됨)에 넣는다:
  ```
  SUPABASE_URL=https://<project>.supabase.co
  SUPABASE_SERVICE_ROLE_KEY=<service_role key>
  SUPABASE_JWT_SECRET=<JWT secret (Legacy HS256)>
  ```
  > 주의: 신규 프로젝트는 비대칭 키가 기본일 수 있다. HS256을 쓰려면 대시보드에서 Legacy JWT Secret(HS256)을 사용/활성화해야 한다. 없으면 이 플랜의 인증 부분은 비대칭(JWKS)로 바꿔야 하므로, Task 4 시작 전 secret 존재를 확인한다.

## File Structure

- `pyproject.toml` (수정) — `supabase`, `pyjwt`, `pydantic-settings` 런타임 의존성.
- `src/timeable/api/config.py` (생성) — 환경설정(`settings`) + `supabase_configured()`.
- `src/timeable/api/repository.py` (생성) — `GroupNotFound`, `GroupRepository` 프로토콜, `LocalJsonRepository`, `SupabaseRepository`, `get_repository()`.
- `src/timeable/api/db.py` (수정) — repository로 위임하는 얇은 facade (public `load_group`, `GroupNotFound` 유지 → routes.py 불변).
- `src/timeable/api/auth.py` (생성) — `verify_jwt` 의존성(HS256).
- `src/timeable/api/schemas.py` (수정) — `MemberIn` 입력 모델 추가.
- `src/timeable/api/routes.py` (수정) — `POST /groups/{group_id}/members` 보호 엔드포인트.
- `supabase/migrations/0001_init.sql` (생성) — groups, members 테이블.
- `scripts/seed_supabase.py` (생성) — 로컬 더미 20명을 Supabase 'dummy' 그룹으로 적재.
- `tests/test_config.py`, `tests/test_repository.py`, `tests/test_auth.py` (생성) — 오프라인 유닛 테스트.
- `docs/backend-run.md` (수정) — Supabase 설정·시드·인증 절 추가.

기존 `tests/test_api.py`의 19개 테스트는 Supabase env가 없으면 `LocalJsonRepository`로 떨어져 **그대로 green**이어야 한다. 모든 태스크에서 이 불변식을 깨지 않는지 확인한다.

---

## Task 1: 의존성 + 환경설정 모듈

**Files:**
- Modify: `pyproject.toml`
- Create: `src/timeable/api/config.py`, `tests/test_config.py`

- [ ] **Step 1: 의존성 추가**

Run:
```bash
uv add supabase pyjwt pydantic-settings
```
Expected: `pyproject.toml` dependencies에 `supabase`, `pyjwt`, `pydantic-settings` 추가, `uv.lock` 갱신.

- [ ] **Step 2: 실패하는 테스트 — create `tests/test_config.py`:**

```python
"""환경설정 테스트. Supabase env 미설정 시 미구성으로 인식해야 한다."""

import unittest

from timeable.api.config import Settings, supabase_configured


class ConfigTest(unittest.TestCase):
    def test_unset_is_not_configured(self):
        s = Settings(supabase_url=None, supabase_service_role_key=None)
        self.assertFalse(supabase_configured(s))

    def test_both_set_is_configured(self):
        s = Settings(supabase_url="https://x.supabase.co", supabase_service_role_key="k")
        self.assertTrue(supabase_configured(s))

    def test_url_only_is_not_configured(self):
        s = Settings(supabase_url="https://x.supabase.co", supabase_service_role_key=None)
        self.assertFalse(supabase_configured(s))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 실패 확인**

Run: `uv run python -m unittest tests.test_config -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'timeable.api.config'`

- [ ] **Step 4: 구현 — create `src/timeable/api/config.py`:**

```python
"""환경설정. .env.local(gitignore) 또는 실제 환경변수에서 읽는다.

Supabase 관련 값이 없으면 로컬 더미 모드로 떨어진다(오프라인 개발·테스트).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.local", extra="ignore")

    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_jwt_secret: str | None = None


settings = Settings()


def supabase_configured(s: Settings = settings) -> bool:
    """Supabase 읽기/쓰기에 필요한 최소 설정이 있는지."""
    return bool(s.supabase_url and s.supabase_service_role_key)
```

- [ ] **Step 5: 통과 확인**

Run: `uv run python -m unittest tests.test_config -v`  → PASS (3 tests)
Full suite: `uv run python -m unittest discover -s tests` → all pass (기존 19 + config 3).

- [ ] **Step 6: 커밋**

```bash
git add pyproject.toml uv.lock src/timeable/api/config.py tests/test_config.py
git commit -m "feat: add settings module and supabase/jwt dependencies"
```

---

## Task 2: Supabase 스키마 마이그레이션 + 시드 스크립트

스키마는 기존 `data` dict 모양을 복원할 수 있게 만든다. 적용/시드는 실제 프로젝트가 필요하므로, SQL·스크립트를 작성하고 적용 절차를 문서화한다(유닛 테스트 대상 아님).

**Files:**
- Create: `supabase/migrations/0001_init.sql`, `scripts/seed_supabase.py`

- [ ] **Step 1: 마이그레이션 SQL — create `supabase/migrations/0001_init.sql`:**

```sql
-- TimeAble 그룹/멤버 스키마. data dict 모양을 복원할 수 있게 구성한다.

create table if not exists groups (
    id           text primary key,            -- 'dummy' 같은 slug
    name         text not null,
    days         text[] not null default array['Mon','Tue','Wed','Thu','Fri'],
    start_hour   int  not null default 9,
    end_hour     int  not null default 21,
    slot_minutes int  not null default 30,
    created_at   timestamptz not null default now()
);

create table if not exists members (
    id        text not null,                  -- 학생 id 's01'
    group_id  text not null references groups(id) on delete cascade,
    name      text,
    dept      text,
    year      int,
    color     text,
    busy      jsonb not null,                 -- [요일][칸] bool 격자
    primary key (group_id, id)
);

create index if not exists members_group_idx on members(group_id);
```

- [ ] **Step 2: 시드 스크립트 — create `scripts/seed_supabase.py`:**

```python
"""로컬 더미(data/dummy_students.json)를 Supabase 'dummy' 그룹으로 적재한다.

실행(실제 Supabase 필요): uv run python scripts/seed_supabase.py
.env.local 의 SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY 를 사용한다.
"""

from __future__ import annotations

from pathlib import Path

from supabase import create_client

from timeable.api.config import settings, supabase_configured
from timeable.schedule import load

GROUP_ID = "dummy"


def main() -> None:
    if not supabase_configured():
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 가 .env.local 에 필요합니다.")

    data_path = Path(__file__).resolve().parents[1] / "data" / "dummy_students.json"
    data = load(data_path)
    client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    client.table("groups").upsert(
        {
            "id": GROUP_ID,
            "name": "더미 20명",
            "days": data["days"],
            "start_hour": data["start_hour"],
            "end_hour": data["end_hour"],
            "slot_minutes": data["slot_minutes"],
        }
    ).execute()

    rows = [
        {
            "id": s["id"],
            "group_id": GROUP_ID,
            "name": s.get("name"),
            "dept": s.get("dept"),
            "year": s.get("year"),
            "color": s.get("color"),
            "busy": s["busy"],
        }
        for s in data["students"]
    ]
    client.table("members").upsert(rows).execute()
    print(f"seeded group '{GROUP_ID}' with {len(rows)} members")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 적용 절차 확인 (실제 프로젝트 보유 시)**

이 스텝은 Supabase 프로젝트가 있을 때만 수행한다. 없으면 SQL/스크립트 작성만 하고 커밋 후 다음 태스크로 간다.
```bash
# Supabase CLI 로 로컬/원격에 마이그레이션 적용 (택1):
#  원격:  supabase db push        (supabase link 후)
#  로컬:  supabase start && supabase db reset
# 그 다음 시드:
uv run python scripts/seed_supabase.py
```
Expected(적용 시): `seeded group 'dummy' with 20 members` 출력.

- [ ] **Step 4: 커밋**

```bash
git add supabase/migrations/0001_init.sql scripts/seed_supabase.py
git commit -m "feat: add supabase schema migration and dummy seed script"
```

---

## Task 3: 저장소 패턴 + load_group를 Supabase로 (오프라인 폴백 유지)

**Files:**
- Create: `src/timeable/api/repository.py`, `tests/test_repository.py`
- Modify: `src/timeable/api/db.py`

- [ ] **Step 1: 실패하는 테스트 — create `tests/test_repository.py`:**

```python
"""저장소 테스트. 로컬 폴백 + Supabase 조립 로직을 가짜 클라이언트로 검증."""

import unittest

from timeable.api.repository import (
    GroupNotFound,
    LocalJsonRepository,
    SupabaseRepository,
)


class _FakeExecute:
    def __init__(self, data):
        self._data = data

    def execute(self):
        class R:
            pass

        r = R()
        r.data = self._data
        return r


class _FakeTable:
    """table().select().eq().order().execute() 체인을 흉내낸다."""

    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        return _FakeExecute(self._rows).execute()


class _FakeClient:
    def __init__(self, groups, members):
        self._groups = groups
        self._members = members

    def table(self, name):
        return _FakeTable(self._groups if name == "groups" else self._members)


class LocalRepoTest(unittest.TestCase):
    def test_dummy_loads(self):
        data = LocalJsonRepository().load_group("dummy")
        self.assertEqual(data["days"], ["Mon", "Tue", "Wed", "Thu", "Fri"])
        self.assertGreater(len(data["students"]), 0)

    def test_unknown_raises(self):
        with self.assertRaises(GroupNotFound):
            LocalJsonRepository().load_group("nope")


class SupabaseRepoTest(unittest.TestCase):
    def test_assembles_data_dict(self):
        groups = [{
            "id": "g1", "name": "G", "days": ["Mon"],
            "start_hour": 9, "end_hour": 11, "slot_minutes": 30,
        }]
        members = [{
            "id": "s1", "group_id": "g1", "name": "A", "dept": "CS",
            "year": 2, "color": "#fff", "busy": [[True, False, False, False]],
        }]
        repo = SupabaseRepository(_FakeClient(groups, members))
        data = repo.load_group("g1")
        self.assertEqual(data["start_hour"], 9)
        self.assertEqual(len(data["students"]), 1)
        self.assertEqual(data["students"][0]["id"], "s1")
        self.assertEqual(data["students"][0]["busy"], [[True, False, False, False]])

    def test_missing_group_raises(self):
        repo = SupabaseRepository(_FakeClient([], []))
        with self.assertRaises(GroupNotFound):
            repo.load_group("nope")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run python -m unittest tests.test_repository -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'timeable.api.repository'`

- [ ] **Step 3: 구현 — create `src/timeable/api/repository.py`:**

```python
"""그룹 저장소. 설정에 따라 로컬 더미 또는 Supabase 를 쓴다.

계산 라우트는 db.load_group 만 보므로, 데이터 출처 교체가 라우트에 영향 없다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Protocol

from ..schedule import load
from .config import settings, supabase_configured


class GroupNotFound(Exception):
    """존재하지 않는 group_id."""


class GroupRepository(Protocol):
    def load_group(self, group_id: str) -> dict: ...


_DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "dummy_students.json"


class LocalJsonRepository:
    """오프라인 개발·테스트용. data/dummy_students.json 의 'dummy' 그룹만."""

    def load_group(self, group_id: str) -> dict:
        if group_id != "dummy":
            raise GroupNotFound(group_id)
        return load(_DATA_PATH)


class SupabaseRepository:
    """Supabase(Postgres)에서 그룹+멤버를 읽어 data dict 로 조립."""

    def __init__(self, client) -> None:
        self._client = client

    def load_group(self, group_id: str) -> dict:
        g = self._client.table("groups").select("*").eq("id", group_id).execute()
        if not g.data:
            raise GroupNotFound(group_id)
        group = g.data[0]
        m = (
            self._client.table("members")
            .select("*")
            .eq("group_id", group_id)
            .order("id")
            .execute()
        )
        return {
            "days": group["days"],
            "start_hour": group["start_hour"],
            "end_hour": group["end_hour"],
            "slot_minutes": group["slot_minutes"],
            "students": [
                {
                    "id": r["id"],
                    "name": r.get("name"),
                    "dept": r.get("dept"),
                    "year": r.get("year"),
                    "color": r.get("color"),
                    "busy": r["busy"],
                }
                for r in m.data
            ],
        }


@lru_cache(maxsize=1)
def get_repository() -> GroupRepository:
    """설정에 맞는 저장소. Supabase 구성 시 SupabaseRepository, 아니면 로컬."""
    if supabase_configured():
        from supabase import create_client

        client = create_client(
            settings.supabase_url, settings.supabase_service_role_key
        )
        return SupabaseRepository(client)
    return LocalJsonRepository()
```

- [ ] **Step 4: db.py를 facade로 교체 — set `src/timeable/api/db.py` to:**

```python
"""그룹 데이터 로더 facade. 실제 구현은 repository 가 설정에 따라 고른다.

routes.py 는 여전히 `from .db import GroupNotFound, load_group` 만 쓴다.
"""

from __future__ import annotations

from .repository import GroupNotFound, get_repository

__all__ = ["GroupNotFound", "load_group"]


def load_group(group_id: str) -> dict:
    return get_repository().load_group(group_id)
```

- [ ] **Step 5: 통과 확인**

Run: `uv run python -m unittest tests.test_repository -v`  → PASS (4 tests)
Full suite: `uv run python -m unittest discover -s tests` → 기존 test_api 19개 포함 모두 green (Supabase env 없으면 로컬 폴백).

- [ ] **Step 6: 커밋**

```bash
git add src/timeable/api/repository.py src/timeable/api/db.py tests/test_repository.py
git commit -m "feat: repository pattern with supabase/local backends (load_group seam)"
```

---

## Task 4: JWT 인증 의존성 + 보호된 멤버 upsert 엔드포인트

읽기는 공개 유지, 쓰기(멤버 시간표 upsert)는 Supabase JWT(HS256) 보호.

**Files:**
- Create: `src/timeable/api/auth.py`, `tests/test_auth.py`
- Modify: `src/timeable/api/schemas.py`, `src/timeable/api/repository.py` (upsert_member), `src/timeable/api/routes.py`

- [ ] **Step 1: 실패하는 테스트 — create `tests/test_auth.py`:**

```python
"""인증 테스트. settings.supabase_jwt_secret 를 몽키패치해 HS256 토큰을 만든다."""

import unittest

import jwt
from fastapi.testclient import TestClient

from timeable.api import config, routes
from timeable.api.main import app

client = TestClient(app)
SECRET = "test-secret"


def make_token(sub: str = "user-1") -> str:
    return jwt.encode({"sub": sub, "aud": "authenticated"}, SECRET, algorithm="HS256")


class AuthTest(unittest.TestCase):
    def setUp(self):
        self._orig = config.settings.supabase_jwt_secret
        config.settings.supabase_jwt_secret = SECRET
        self._calls = []

        class _Repo:
            def upsert_member(_self, group_id, member):
                self._calls.append((group_id, member))

        # routes.py 가 get_repository 를 이름으로 import 하므로 routes 네임스페이스를 패치한다.
        self._orig_get = routes.get_repository
        routes.get_repository = lambda: _Repo()

    def tearDown(self):
        config.settings.supabase_jwt_secret = self._orig
        routes.get_repository = self._orig_get

    def _member_body(self):
        return {
            "id": "s99", "name": "테스트", "dept": "CS", "year": 1,
            "color": "#123456", "busy": [[False] * 24 for _ in range(5)],
        }

    def test_missing_token_401(self):
        resp = client.post("/groups/dummy/members", json=self._member_body())
        self.assertEqual(resp.status_code, 401)

    def test_invalid_token_401(self):
        resp = client.post(
            "/groups/dummy/members",
            json=self._member_body(),
            headers={"Authorization": "Bearer not.a.jwt"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_valid_token_upserts(self):
        resp = client.post(
            "/groups/dummy/members",
            json=self._member_body(),
            headers={"Authorization": f"Bearer {make_token()}"},
        )
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(len(self._calls), 1)
        self.assertEqual(self._calls[0][0], "dummy")
        self.assertEqual(self._calls[0][1]["id"], "s99")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run python -m unittest tests.test_auth -v`
Expected: FAIL — `/groups/dummy/members` 가 404 (라우트 없음) 또는 import 에러.

- [ ] **Step 3: 인증 의존성 — create `src/timeable/api/auth.py`:**

```python
"""Supabase JWT(HS256) 검증 의존성.

Supabase 가 발급한 access token 의 서명을 SUPABASE_JWT_SECRET 으로 확인하고
subject(user id)를 돌려준다. 읽기 라우트는 공개, 쓰기 라우트만 이걸 의존한다.
"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

_bearer = HTTPBearer(auto_error=False)


def verify_jwt(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if settings.supabase_jwt_secret is None:
        raise HTTPException(status_code=503, detail="auth not configured")
    if creds is None:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        payload = jwt.decode(
            creds.credentials,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid token")
    return payload["sub"]
```

- [ ] **Step 4: 입력 스키마 — in `src/timeable/api/schemas.py`, add at the end:**

```python
class MemberIn(BaseModel):
    """멤버 시간표 upsert 입력. busy 는 [요일][칸] bool 격자."""

    id: str
    name: str | None = None
    dept: str | None = None
    year: int | None = None
    color: str | None = None
    busy: list[list[bool]]
```

- [ ] **Step 5: 저장소에 upsert_member 추가 — in `src/timeable/api/repository.py`:**

`LocalJsonRepository` 클래스에 추가:
```python
    def upsert_member(self, group_id: str, member: dict) -> None:
        raise NotImplementedError("로컬 더미 저장소는 읽기 전용입니다. Supabase 를 설정하세요.")
```
`SupabaseRepository` 클래스에 추가:
```python
    def upsert_member(self, group_id: str, member: dict) -> None:
        row = {**member, "group_id": group_id}
        self._client.table("members").upsert(row).execute()
```
그리고 `GroupRepository` Protocol 에 메서드 시그니처 추가:
```python
    def upsert_member(self, group_id: str, member: dict) -> None: ...
```

- [ ] **Step 6: 보호된 라우트 — in `src/timeable/api/routes.py`:**

파일 상단의 import 블록 **전체를 아래로 교체**한다 (기존엔 `APIRouter, HTTPException, Query` + availability + db + schemas 만 있었다):
```python
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..availability import attendance_field, handler, top_candidates
from .auth import verify_jwt
from .db import GroupNotFound, load_group
from .repository import get_repository
from .schemas import Block, FieldResponse, MemberIn
```

그리고 파일 끝에 라우트 추가:
```python
@router.post("/groups/{group_id}/members", status_code=204)
def upsert_member(
    group_id: str,
    member: MemberIn,
    user_id: str = Depends(verify_jwt),
) -> Response:
    get_repository().upsert_member(group_id, member.model_dump())
    return Response(status_code=204)
```

- [ ] **Step 7: 통과 확인**

Run: `uv run python -m unittest tests.test_auth -v`  → PASS (3 tests)
Full suite: `uv run python -m unittest discover -s tests` → 모두 green (test_api 19 + config 3 + repository 4 + auth 3 = 29).

- [ ] **Step 8: 커밋**

```bash
git add src/timeable/api/auth.py src/timeable/api/schemas.py src/timeable/api/repository.py src/timeable/api/routes.py tests/test_auth.py
git commit -m "feat: HS256 JWT verification and protected member upsert endpoint"
```

---

## Task 5: 문서 업데이트 + (프로젝트 보유 시) 실 환경 수동 검증

**Files:**
- Modify: `docs/backend-run.md`

- [ ] **Step 1: 문서 보강 — in `docs/backend-run.md`, add a section:**

```markdown
## Supabase (Plan 2)

### 설정 (.env.local, gitignore)
    SUPABASE_URL=https://<project>.supabase.co
    SUPABASE_SERVICE_ROLE_KEY=<service_role>
    SUPABASE_JWT_SECRET=<legacy HS256 secret>
- 세 값이 없으면 백엔드는 로컬 더미('dummy' 그룹)로 자동 폴백한다(오프라인).

### 스키마·시드
    supabase db push        # 또는 로컬: supabase start && supabase db reset
    uv run python scripts/seed_supabase.py

### 인증
- 읽기(field/availability/candidates)는 공개.
- 쓰기: POST /groups/{id}/members 는 Supabase access token(HS256) 필요.
      Authorization: Bearer <token>
- 프론트는 Supabase JS 로그인으로 토큰을 얻어 이 헤더로 호출한다.
```

- [ ] **Step 2: 전체 테스트 통과 확인 (오프라인)**

Run: `uv run python -m unittest discover -s tests -v`
Expected: 29개 전부 PASS (Supabase env 없이, 로컬 폴백).

- [ ] **Step 3: 실 환경 수동 검증 (Supabase 프로젝트 보유 시에만)**

`.env.local`을 채우고 마이그레이션+시드를 적용한 뒤:
```bash
uv run uvicorn timeable.api.main:app --port 8000 > /tmp/ta.log 2>&1 &
UVPID=$!; sleep 3
curl -s "http://127.0.0.1:8000/groups/dummy/candidates?min_free=15&k=3"; echo   # Supabase 데이터로 응답
curl -s -o /dev/null -w "%{http_code}\n" -X POST "http://127.0.0.1:8000/groups/dummy/members" -H "Content-Type: application/json" -d '{"id":"s99","busy":[[false]]}'   # 401 (토큰 없음)
kill $UVPID 2>/dev/null
```
Expected: candidates 가 Supabase 시드 데이터로 응답, 멤버 POST 는 토큰 없으면 401.
> Supabase 프로젝트가 아직 없으면 이 스텝은 건너뛰고, 오프라인 29개 테스트 green 으로 Plan 2 를 완료 처리한다. 실 검증은 프로젝트 준비 후 재수행.

- [ ] **Step 4: 커밋**

```bash
git add docs/backend-run.md
git commit -m "docs: document Supabase config, seed, and auth"
```

---

## 완료 기준 (Plan 2)

- 오프라인 전체 테스트(29개) green — Supabase env 없이 로컬 폴백으로 동작.
- `SUPABASE_URL` 설정 시 읽기 엔드포인트가 Supabase 데이터를 반환(계산 라우트·코어 무변경).
- `POST /groups/{id}/members` 가 유효한 HS256 토큰에서 204, 없거나 틀리면 401.
- 스키마 마이그레이션 + 시드 스크립트로 더미 20명을 Supabase 'dummy' 그룹에 적재 가능.

## 범위 밖 (다음)
- RLS 정책 세부, 그룹 생성/멤버 조회 엔드포인트 → 필요 시 후속.
- 비대칭(JWKS) 인증, 투표/확정 realtime, Canvas import → Plan 4(부가).
- Next.js 복셀 프론트 → Plan 3.
