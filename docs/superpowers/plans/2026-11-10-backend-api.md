# Backend API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 가용성 계산 코어 위에 `attendance_field`(히트맵 스칼라)를 추가하고, FastAPI로 `/field`·`/availability`·`/candidates` 엔드포인트를 로컬 JSON 위에서 구동한다. Supabase 없이도 완결·테스트되는 Python 백엔드.

**Architecture:** 기존 순수 함수(`schedule.py`, `availability.py`)는 그대로 두고, FastAPI 앱을 `src/timeable/api/` 하위 모듈로 추가한다. 데이터 로딩은 `db.load_group(group_id)` 한 함수 뒤로 숨겨, Plan 2에서 이 함수만 Supabase로 교체하면 된다. 엔드포인트는 계산 함수를 얇게 감싸고 Pydantic으로 응답 스키마를 고정한다.

**Tech Stack:** Python 3.10+, uv, FastAPI, Uvicorn, Pydantic, httpx(TestClient). 테스트는 기존 컨벤션대로 `unittest`.

---

## File Structure

- `src/timeable/availability.py` (수정) — `attendance_field()` 추가. 히트맵 모델 #2(windowed-intersection attendance).
- `src/timeable/api/__init__.py` (생성) — 빈 패키지 마커.
- `src/timeable/api/db.py` (생성) — `load_group(group_id)` + `GroupNotFound`. Plan 1은 로컬 JSON, Plan 2에서 Supabase로 교체.
- `src/timeable/api/schemas.py` (생성) — Pydantic 모델 `Block`, `FieldResponse`.
- `src/timeable/api/routes.py` (생성) — 3개 엔드포인트 + 404 처리.
- `src/timeable/api/main.py` (생성) — `app = FastAPI()`, CORS, `/health`, 라우터 포함.
- `tests/test_attendance_field.py` (생성) — `attendance_field` 단위 테스트.
- `tests/test_api.py` (생성) — TestClient 계약 테스트.
- `pyproject.toml` (수정) — fastapi/uvicorn 런타임 의존성, httpx dev 의존성.
- `README` 또는 docs (수정) — 백엔드 실행법 메모.

주의: `tests/` 의 기존 테스트는 패키지 import(`from timeable...`)를 쓰므로 `uv run`이 `src/timeable`을 설치된 상태로 인식한다. 새 테스트도 동일하게 `from timeable.api...`로 import한다.

---

## Task 1: `attendance_field` 계산 함수

칸 (d,s)마다 "길이 `min_duration` 창 [s, s+min_duration) 동안 **내내** 비는 공통 인원 수"를 센다. `min_duration=1`이면 정확히 `free_counts`와 같아야 한다. 창이 요일 끝을 넘으면(회의가 하루 안에 안 들어가면) 0.

**Files:**
- Modify: `src/timeable/availability.py` (파일 끝 `top_candidates` 아래, `_demo` 위)
- Test: `tests/test_attendance_field.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_attendance_field.py` 생성:

```python
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
        # 칸0 창[0,1):{s3}&... 실제 창[0,2) 교집합:
        #  칸0 free {s3}, 칸1 free {s1,s3} -> 교집합 {s3} = 1
        #  칸1 free {s1,s3}, 칸2 free {s1,s2,s3} -> {s1,s3} = 2
        #  칸2 free {s1,s2,s3}, 칸3 free {s1,s2} -> {s1,s2} = 2
        #  칸3: 창[3,5) 가 ns=4 넘음 -> 0
        self.assertEqual(attendance_field(make_data(), 2), [[1, 2, 2, 0]])

    def test_duration_overflow_is_zero(self):
        # min_duration=4, ns=4: 칸0만 창[0,4) 유효, 나머지는 overflow -> 0.
        #  칸0 교집합: {s3}&{s1,s3}&{s1,s2,s3}&{s1,s2} = {} = 0
        self.assertEqual(attendance_field(make_data(), 4), [[0, 0, 0, 0]])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run python -m unittest tests.test_attendance_field -v`
Expected: FAIL — `ImportError: cannot import name 'attendance_field'`

- [ ] **Step 3: 최소 구현**

`src/timeable/availability.py` 의 `top_candidates` 함수 정의가 끝난 직후(줄 124~125 `return blocks[:k]` 아래 빈 줄)에 추가:

```python
def attendance_field(data: dict, min_duration: int = 1) -> list[list[int]]:
    """칸마다 '길이 min_duration 창 내내 비는 공통 인원 수'.

    히트맵/지형 높이를 위한 스칼라 필드. 각 칸 (d,s)에서 창 [s, s+min_duration)
    동안 모두 자유인 학생의 교집합 크기를 센다. 회의는 연속 블록이 필요하므로
    고립된 한 칸의 자유는 긴 블록과 다르게 평가된다.

    - min_duration=1 이면 free_counts 와 동일.
    - 창이 요일 끝을 넘으면(회의가 하루 안에 안 들어가면) 0.
    """
    free_ids = _free_ids(data)
    nd, ns = day_count(data), slot_count(data)
    field = [[0] * ns for _ in range(nd)]
    for d in range(nd):
        for s in range(ns):
            end = s + min_duration
            if end > ns:
                continue  # 창이 요일 밖 -> 0 유지
            attendees = set(free_ids[d][s])
            for t in range(s + 1, end):
                attendees &= set(free_ids[d][t])
            field[d][s] = len(attendees)
    return field
```

- [ ] **Step 4: 통과 확인**

Run: `uv run python -m unittest tests.test_attendance_field -v`
Expected: PASS (3 tests)

- [ ] **Step 5: 전체 테스트 회귀 확인**

Run: `uv run python -m unittest discover -s tests -v`
Expected: 기존 + 신규 전부 PASS

- [ ] **Step 6: 커밋**

```bash
git add src/timeable/availability.py tests/test_attendance_field.py
git commit -m "feat: add attendance_field (windowed-intersection heatmap scalar)"
```

---

## Task 2: FastAPI 의존성 + 앱 스켈레톤 + /health

**Files:**
- Modify: `pyproject.toml`
- Create: `src/timeable/api/__init__.py`, `src/timeable/api/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: 의존성 추가**

Run:
```bash
uv add fastapi "uvicorn[standard]"
uv add --dev httpx
```
Expected: `pyproject.toml` 의 `dependencies` 에 `fastapi`, `uvicorn[standard]` 추가, `[dependency-groups] dev` 에 `httpx` 추가. `uv.lock` 갱신.

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_api.py` 생성:

```python
"""FastAPI 엔드포인트 계약 테스트.

실행: uv run python -m unittest discover -s tests
TestClient 는 httpx 기반이라 dev 의존성에 httpx 필요.
"""

import unittest

from fastapi.testclient import TestClient

from timeable.api.main import app

client = TestClient(app)


class HealthTest(unittest.TestCase):
    def test_health_ok(self):
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 실패 확인**

Run: `uv run python -m unittest tests.test_api -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'timeable.api'`

- [ ] **Step 4: 패키지 마커 생성**

`src/timeable/api/__init__.py` 생성 (내용 1줄):

```python
"""TimeAble FastAPI 앱. 계산 코어(timeable.availability)를 HTTP로 노출한다."""
```

- [ ] **Step 5: 앱 생성**

`src/timeable/api/main.py` 생성:

```python
"""FastAPI 진입점.

실행: uv run uvicorn timeable.api.main:app --reload
문서: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="TimeAble API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 6: 통과 확인**

Run: `uv run python -m unittest tests.test_api -v`
Expected: PASS (1 test)

- [ ] **Step 7: 커밋**

```bash
git add pyproject.toml uv.lock src/timeable/api/__init__.py src/timeable/api/main.py tests/test_api.py
git commit -m "feat: scaffold FastAPI app with /health"
```

---

## Task 3: 그룹 로더 (`db.load_group`)

Plan 1은 로컬 `data/dummy_students.json` 하나를 "dummy" 그룹으로 제공한다. 알 수 없는 group_id는 `GroupNotFound`. Plan 2에서 이 파일만 Supabase 조회로 교체한다.

**Files:**
- Create: `src/timeable/api/db.py`
- Test: `tests/test_api.py` (클래스 추가)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_api.py` 의 `HealthTest` 클래스 아래, `if __name__` 위에 추가. 파일 상단 import에 다음 한 줄 추가:

```python
from timeable.api.db import GroupNotFound, load_group
```

추가할 테스트 클래스:

```python
class LoadGroupTest(unittest.TestCase):
    def test_dummy_group_loads_students(self):
        data = load_group("dummy")
        self.assertIn("students", data)
        self.assertEqual(data["days"], ["Mon", "Tue", "Wed", "Thu", "Fri"])
        self.assertGreater(len(data["students"]), 0)

    def test_unknown_group_raises(self):
        with self.assertRaises(GroupNotFound):
            load_group("nope")
```

- [ ] **Step 2: 실패 확인**

Run: `uv run python -m unittest tests.test_api -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'timeable.api.db'`

- [ ] **Step 3: 구현**

`src/timeable/api/db.py` 생성:

```python
"""그룹 데이터 로더.

Plan 1: 로컬 data/dummy_students.json 하나를 'dummy' 그룹으로 제공.
Plan 2: 이 모듈만 Supabase(Postgres) 조회로 교체하면 라우트는 그대로 동작한다.
"""

from __future__ import annotations

from pathlib import Path

from ..schedule import load

# src/timeable/api/db.py -> parents[3] = 저장소 루트
_DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "dummy_students.json"


class GroupNotFound(Exception):
    """존재하지 않는 group_id."""


def load_group(group_id: str) -> dict:
    """group_id 로 시간표 데이터 dict 를 돌려준다.

    Plan 1에서는 'dummy' 하나만 유효하다.
    """
    if group_id != "dummy":
        raise GroupNotFound(group_id)
    return load(_DATA_PATH)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run python -m unittest tests.test_api -v`
Expected: PASS (3 tests: health + load 2개)

- [ ] **Step 5: 커밋**

```bash
git add src/timeable/api/db.py tests/test_api.py
git commit -m "feat: add load_group loader over local dummy data"
```

---

## Task 4: Pydantic 스키마 + `/field` 엔드포인트

**Files:**
- Create: `src/timeable/api/schemas.py`, `src/timeable/api/routes.py`
- Modify: `src/timeable/api/main.py` (라우터 포함)
- Test: `tests/test_api.py` (클래스 추가)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_api.py` 에 추가:

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `uv run python -m unittest tests.test_api -v`
Expected: FAIL — `/groups/dummy/field` 가 404 (라우트 없음)

- [ ] **Step 3: 스키마 작성**

`src/timeable/api/schemas.py` 생성:

```python
"""API 응답 Pydantic 모델. 프론트 TS 가 이 shape 를 그대로 소비한다."""

from __future__ import annotations

from pydantic import BaseModel


class Block(BaseModel):
    """handler/top_candidates 가 돌려주는 가용성 블록."""

    day_index: int
    day: str
    start_slot: int
    end_slot: int
    length: int
    start_label: str
    end_label: str
    min_free: int
    attendees: list[str]
    attendance: int


class FieldResponse(BaseModel):
    """히트맵/지형용 스칼라 필드."""

    days: list[str]
    field: list[list[int]]  # [day][slot] = 창 내내 비는 공통 인원 수
    min_duration: int
```

- [ ] **Step 4: 라우트 작성**

`src/timeable/api/routes.py` 생성:

```python
"""가용성 계산을 HTTP 로 노출하는 라우터."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..availability import attendance_field
from .db import GroupNotFound, load_group
from .schemas import FieldResponse

router = APIRouter()


def _load(group_id: str) -> dict:
    try:
        return load_group(group_id)
    except GroupNotFound:
        raise HTTPException(status_code=404, detail=f"group '{group_id}' not found")


@router.get("/groups/{group_id}/field", response_model=FieldResponse)
def get_field(group_id: str, min_duration: int = Query(1, ge=1)) -> FieldResponse:
    data = _load(group_id)
    return FieldResponse(
        days=data["days"],
        field=attendance_field(data, min_duration),
        min_duration=min_duration,
    )
```

- [ ] **Step 5: 라우터 포함**

`src/timeable/api/main.py` 를 수정 — `from fastapi import FastAPI` 아래에 import 추가하고, `app = FastAPI(...)` 아래에 `include_router` 한 줄 추가:

```python
from fastapi import FastAPI

from .routes import router

app = FastAPI(title="TimeAble API")
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 6: 통과 확인**

Run: `uv run python -m unittest tests.test_api -v`
Expected: PASS (field 2개 포함 전부)

- [ ] **Step 7: 커밋**

```bash
git add src/timeable/api/schemas.py src/timeable/api/routes.py src/timeable/api/main.py tests/test_api.py
git commit -m "feat: add /field endpoint with Pydantic schemas"
```

---

## Task 5: `/availability` + `/candidates` 엔드포인트

**Files:**
- Modify: `src/timeable/api/routes.py`
- Test: `tests/test_api.py` (클래스 추가)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_api.py` 에 추가:

```python
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
        self.assertLessEqual(len(cands), 3)
        attendances = [c["attendance"] for c in cands]
        self.assertEqual(attendances, sorted(attendances, reverse=True))

    def test_candidates_unknown_group_404(self):
        resp = client.get("/groups/nope/candidates", params={"min_free": 10})
        self.assertEqual(resp.status_code, 404)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run python -m unittest tests.test_api -v`
Expected: FAIL — availability/candidates 라우트가 404

- [ ] **Step 3: 라우트 추가**

`src/timeable/api/routes.py` 를 수정. import 줄을 다음으로 교체:

```python
from ..availability import attendance_field, handler, top_candidates
from .db import GroupNotFound, load_group
from .schemas import Block, FieldResponse
```

그리고 `get_field` 함수 아래에 추가:

```python
@router.get("/groups/{group_id}/availability", response_model=list[Block])
def get_availability(
    group_id: str,
    min_free: int = Query(..., ge=0),
    min_duration: int = Query(1, ge=1),
) -> list[dict]:
    data = _load(group_id)
    return handler(data, min_free, min_duration)


@router.get("/groups/{group_id}/candidates", response_model=list[Block])
def get_candidates(
    group_id: str,
    min_free: int = Query(..., ge=0),
    k: int = Query(3, ge=1),
) -> list[dict]:
    data = _load(group_id)
    return top_candidates(data, min_free, k)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run python -m unittest tests.test_api -v`
Expected: PASS (availability/candidates 4개 포함 전부)

- [ ] **Step 5: 커밋**

```bash
git add src/timeable/api/routes.py tests/test_api.py
git commit -m "feat: add /availability and /candidates endpoints"
```

---

## Task 6: CORS + 실행 문서 + 수동 확인

**Files:**
- Modify: `src/timeable/api/main.py` (CORS)
- Create: `docs/backend-run.md`

- [ ] **Step 1: CORS 미들웨어 추가**

`src/timeable/api/main.py` 를 수정. 최종 형태:

```python
"""FastAPI 진입점.

실행: uv run uvicorn timeable.api.main:app --reload
문서: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router

app = FastAPI(title="TimeAble API")

# 프론트(Next.js)에서 브라우저가 직접 호출하므로 CORS 허용.
# Plan 3/배포에서 allow_origins 를 실제 도메인으로 좁힌다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 2: 전체 테스트 통과 확인**

Run: `uv run python -m unittest discover -s tests -v`
Expected: 모든 테스트 PASS (availability 코어 + attendance_field + api)

- [ ] **Step 3: 서버 수동 기동 확인**

Run: `uv run uvicorn timeable.api.main:app --port 8000 &` 후
`curl -s "http://127.0.0.1:8000/groups/dummy/candidates?min_free=15&k=3"`
Expected: 블록 JSON 배열 출력 (예: 목/금 오후 후보). 확인 후 `kill %1` 로 서버 종료.
브라우저로 `http://127.0.0.1:8000/docs` 를 열면 3개 엔드포인트가 자동 문서화되어 있다.

- [ ] **Step 4: 실행 문서 작성**

`docs/backend-run.md` 생성:

```markdown
# 백엔드 실행 (Plan 1)

## 개발 서버
    uv run uvicorn timeable.api.main:app --reload
- API 문서(자동): http://127.0.0.1:8000/docs
- 헬스체크: GET /health

## 엔드포인트 (Plan 1, 그룹은 'dummy' 하나)
- GET /groups/{id}/field?min_duration=1        히트맵/지형 스칼라 필드
- GET /groups/{id}/availability?min_free=&min_duration=1   수위 블록 목록
- GET /groups/{id}/candidates?min_free=&k=3    상위 후보

## 테스트
    uv run python -m unittest discover -s tests

## 다음 (Plan 2)
db.load_group() 을 Supabase 조회로 교체하면 라우트는 그대로 동작한다.
```

- [ ] **Step 5: 커밋**

```bash
git add src/timeable/api/main.py docs/backend-run.md
git commit -m "feat: add CORS and backend run docs"
```

---

## 완료 기준 (Plan 1)

- `uv run python -m unittest discover -s tests` 전부 PASS.
- `uv run uvicorn timeable.api.main:app` 기동 후 `/docs` 에서 3개 엔드포인트 확인 가능.
- `/groups/dummy/field|availability|candidates` 가 올바른 JSON 반환, 알 수 없는 그룹은 404, `min_free` 누락은 422.
- `attendance_field(data, 1) == free_counts(data)` 불변식 유지.

## 범위 밖 (다음 플랜)
- Supabase 스키마·JWT 검증·`load_group` 교체 → Plan 2.
- Next.js 복셀 프론트 → Plan 3.
- Canvas import / 투표 → Plan 4(부가).
