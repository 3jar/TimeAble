# TimeAble 백엔드/프론트 아키텍처 설계

작성일: 2026-11-10 · 상태: 승인됨 (구현 계획 대기)

## 목적

TimeAble은 등록한 학생 전원의 시간표를 합쳐 공통 빈 시간을 복셀 지형도(호수/마을)로
보여주는 웹 서비스다. 이 문서는 그 **런타임 아키텍처** — 프론트/백엔드 분리, 저장소,
계산 책임, 인증 — 를 확정한다. 히트맵 수학 모델 비교는 별도 메모
(`docs/temp-heatmap-models.md`)에 있고, 그 모델이 백엔드 계산의 대상이다.

핵심 제약(team_plan): **백엔드는 Python + uv**. 데이터사이언스 성격(가용성·히트맵 계산)이
있어 Python 백엔드가 쇼케이스가 된다.

## 결정 요약

| 결정 | 선택 | 이유 |
|---|---|---|
| 런타임 분리 | **FastAPI(백엔드) + Next.js(프론트) 분리** | 역할 분담 명확, Python 제약 충족, 둘 다 과시 가능 |
| 백엔드 프레임워크 | **FastAPI** (Django 아님) | 계산 중심 API, Pydantic 검증, 자동 OpenAPI 문서, async |
| 저장소/인증 | **Supabase** (Postgres + Auth + Realtime + Storage) | OAuth 로그인 무료 해결, RLS로 그룹 공유, 투표 realtime |
| 프론트 | **Next.js + TypeScript + three.js** | 복셀 렌더링은 전부 클라이언트, 2026 디폴트 스택 |
| 패키지 | **uv** | team_plan 제약 |

## 아키텍처

```
┌─────────────────────────────────────────┐
│  브라우저: Next.js + three.js (복셀 지도)  │
└───────┬─────────────────────┬────────────┘
        │ Supabase JS client  │ fetch /api
        ▼                     ▼
┌──────────────────┐   ┌──────────────────────────────┐
│    Supabase      │   │   FastAPI (Python · uv)        │
│  · Auth (OAuth)  │◄──│  · Supabase JWT 검증           │
│  · Postgres      │   │  · free_counts / handler /     │
│  · Realtime/투표 │   │    top_candidates /            │
│  · Storage/포스터│   │    attendance_field (히트맵)   │
└──────────────────┘   │  · (부가) Canvas OAuth2 import  │
                       └──────────────────────────────┘
```

### 폴더 구조 (루트 = Python 데이터 프로젝트)

FastAPI는 Django처럼 평행한 `backend/`를 만들지 않고, 기존 Python 패키지 안에
하위 모듈로 녹아든다. 기존 루트 경로(`data/`, `src/timeable/`, `generate_dummy.py`)와
`timeable-data` 스킬 참조가 그대로 유지된다.

```
TimeAble/                       # 루트 = Python 데이터 프로젝트
├── pyproject.toml              # uv (기존, FastAPI 의존성 추가)
├── generate_dummy.py           # 기존 유지
├── data/dummy_students.json    # 기존 유지
├── src/timeable/
│   ├── schedule.py             # 기존 계산 코어
│   ├── availability.py         # 기존 (+ attendance_field)
│   └── api/                    # FastAPI 하위 모듈
│       ├── main.py             #   app = FastAPI()
│       ├── routes.py           #   /field, /availability, /candidates
│       ├── schemas.py          #   Pydantic 모델
│       ├── deps.py             #   Supabase JWT 검증
│       └── db.py               #   Supabase 클라이언트
├── tests/                      # 기존 + TestClient API 테스트
├── web/                        # Next.js 프론트 (JS 세계는 여기만)
│   ├── app/ · components/ · lib/supabase.ts · package.json
├── supabase/                   # DB 스키마·마이그레이션 (supabase CLI)
│   └── migrations/
└── docs/
```

실행: 백엔드 `uv run uvicorn timeable.api.main:app --reload`, 프론트 `cd web && npm run dev`.
두 프로세스, 한 저장소. FastAPI 내부는 지금은 평평한 4파일, 커지면 `routes/`를 디렉터리로 분할.

### 역할 분담

- **Supabase** — 지루하지만 편한 것: 로그인(OAuth), 영속 저장, 그룹 공유(RLS),
  투표 realtime, 포스터 storage.
- **FastAPI** — 흥미로운 것(Python 쇼케이스): 히트맵/가용성 계산, (부가) Canvas 연동.
  Supabase가 발급한 JWT를 검증해 사용자를 신뢰하고, service key로 Postgres를 읽는다.
- **Next.js** — 복셀 렌더링·UI. Supabase(인증·CRUD)와 FastAPI(계산) 둘 다 호출.

### 인증은 두 종류 (혼동 금지)

- (a) **Supabase Auth** = 앱 로그인 (구글/카카오 OAuth).
- (b) **Canvas OAuth2** = 학교 포털 시간표를 가져오는 데이터 소스 토큰. 앱 로그인과 별개.
  서버(FastAPI)에서만 다루고 학번/비번은 받지 않는다 (기획안 보안 주의 준수).

## 컴포넌트

### 1. 가용성 계산 코어 (`src/timeable/`, 기존)
- `schedule.py`, `availability.py` — 순수 함수. 프레임워크 무관, 단위 테스트 대상.
- 히트맵 1단계로 `attendance_field(data, min_duration)` 추가 예정
  (windowed-intersection attendance, temp 메모 모델 #2).

### 2. FastAPI 앱 (신규, `src/timeable/api/` 또는 `api/`)
- 계산 코어를 엔드포인트로 노출. Pydantic 모델로 블록/필드 스키마 선언.
- Supabase에서 그룹 데이터 로드 → 계산 → JSON 반환.
- JWT 검증 의존성(`Depends`)으로 보호된 라우트.

### 3. Supabase 스키마 (신규)
- `groups` (id, name, 생성자, created_at)
- `members` (group_id, user_id, 캐릭터 색/모자)
- `timetables` (member_id, busy 격자 또는 slot 단위 상태: 수업/애매/자유)
- `votes` (group_id, user_id, 후보 블록, 부가)
- RLS: 멤버만 자기 그룹 조회/수정.

### 4. Next.js 프론트 (신규, `web/` 또는 별도)
- three.js `InstancedMesh` 복셀 렌더, 정사영 아이소메트릭 카메라.
- 수위 슬라이더 → FastAPI `/availability` 호출 → 지형 재계산.
- Supabase JS client로 로그인·그룹 CRUD.

## API 표면 (초안)

| 메서드 | 경로 | 역할 |
|---|---|---|
| GET | `/groups/{id}/field?min_duration=` | 칸별 attendance 스칼라 필드 (히트맵/지형 높이) |
| GET | `/groups/{id}/availability?min_free=&min_duration=` | 수위 블록 목록 (`handler`) |
| GET | `/groups/{id}/candidates?min_free=&k=` | 상위 후보 (`top_candidates`) |
| POST | `/groups/{id}/import/canvas` | (부가) Canvas 토큰 → busy 격자 파싱·저장 |

모든 응답은 Pydantic 모델로 타입 고정 → 프론트 TS가 그대로 소비.

## 데이터 흐름

1. 로그인 (Next.js ↔ Supabase Auth).
2. 그룹 생성/참여, 시간표 입력 (Next.js ↔ Supabase, 또는 부가로 Canvas import via FastAPI).
3. 지도 감상: Next.js가 FastAPI `/field` 호출 → 복셀 지형 렌더.
4. 수위/필터 조절: 슬라이더 → `/availability`, `/candidates` 재호출 → 호수/추천 갱신.
5. (부가) 투표: Supabase Realtime으로 깃발 반영 → 확정 → .ics 내보내기.

## 배포 (분리 배포)

세 조각을 각자 잘하는 매니지드 플랫폼에 올린다. 폴더 레이아웃은 바꾸지 않는다.

| 조각 | 플랫폼 | 방법 |
|---|---|---|
| Next.js | **Vercel** | Root Directory = `web/` → Next.js만 빌드, 루트 Python은 무시 |
| FastAPI | **Render** (또는 Railway) | Git 연결 + Python 런타임 build/start 커맨드 (Dockerfile 불필요) |
| DB/Auth | **Supabase** | 이미 매니지드 |

- "web/에 프레임워크 두 개" 아님: `web/`는 순수 Next.js, FastAPI는 루트 `src/timeable/`.
  물리적으로 다른 폴더 + 다른 플랫폼이라 **빌드 충돌이 구조적으로 불가능**.
- 전부 무료 티어 → 과제 비용 0.
- 대안(지금은 안 함): Vercel Python serverless / Vercel Services로 한 배포에 합칠 수 있으나
  Python을 Next.js 앱 안으로 재배치해야 해 과투자.

**주의:**
- Render 무료 티어는 유휴 15분 후 슬립(cold start) → 발표 직전 1회 깨우기. 상시 가동 원하면 Railway/유료.
- FastAPI에 `CORSMiddleware`로 Vercel 도메인 허용. 인증은 프론트↔Supabase 직접, FastAPI는 JWT 검증만.
- Supabase 키·FastAPI URL은 각 플랫폼 env로 주입.

## 에러 처리

- FastAPI: Pydantic 검증 실패 → 422 자동. JWT 무효 → 401. 그룹 없음 → 404.
- Supabase 접근 실패(네트워크) → 백엔드가 503 반환, 프론트는 재시도/안내.
- 오프라인 데모 대비: `supabase` CLI 로컬 스택(Docker) 또는 SQLite 폴백을 옵션으로 둔다.

## 테스트

- 계산 코어: 기존 `unittest` 유지·확장 (`attendance_field` 포함).
- API: FastAPI `TestClient`로 엔드포인트 계약 테스트 (Supabase는 모킹/로컬).

## 범위

### 핵심 (2주차 끝까지)
- 가용성 계산 코어 + `attendance_field`.
- FastAPI: `/field`, `/availability`, `/candidates`.
- Supabase: 그룹·멤버·시간표 스키마 + 로그인.
- Next.js: 복셀 지도 + 수위 슬라이더 + 추천 리스트.

### 부가 (시간 남으면)
- Canvas OAuth2 import, 투표/확정 realtime, .ics 내보내기, 포스터 export.
- 3단계 상태(수업/애매/자유) → 확률적 기대참석 히트맵(temp 메모 모델 #4).

### 이번에는 안 함
- GP/ILP 등 고급 히트맵 모델 (격자 작아 과투자), OCR 입력.

## 열린 질문 (기획안에서 이어짐)
- 인원 비율 구간(소수/중간/다수) 경계값.
- 시간 경계 "아쉬움" 겹침 허용치 (10분? 15분?).
