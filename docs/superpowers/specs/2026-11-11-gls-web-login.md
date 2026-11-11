# GLS 웹 로그인 / 시간표 import 설계

> 상태: **설계 합의용 초안**. 구현 전 이 문서로 흐름·결정 확정.
> 전제(기존 아키텍처 스펙): FastAPI = **Render 상주 프로세스**, 앱 인증 = **Supabase JWT**(FastAPI는 검증만), 저장 = **Supabase `members.busy`**.

## 1. 배경 & 범위

- 목표: 사용자의 **GLS 시간표**를 웹에서 가져와 availability 격자로 저장.
- 앞서 확정: 웹앱이라 진짜 OAuth 화면 재사용 불가(cross-origin) → **백엔드 스크립트 로그인**(비번 일시 보유)으로 간다.
- GLS 로그인은 앱 로그인이 아니라, **이미 인증된 앱 유저가 자기 SKKU 계정을 연결해 시간표를 import**하는 2차 자격증명 흐름.

## 2. 핵심 결정 — "세션 유지"가 아니라 "일회성 import"

이전 논의의 "세션 캐싱/반복 OTP 완화"는 대부분 **불필요**하다. 이유:

- GLS 세션을 계속 들고 있을 필요가 없다. **로그인 → `timetable()` → busy 격자 → `members` upsert → 세션·비번 즉시 폐기**로 끝난다.
- 내구성 있는 산출물은 **`members.busy` 격자**(민감정보 아님)뿐. **GLS 세션/비밀번호는 서버에 하나도 안 남는다.**
- OTP는 "import할 때 1회"(학기당 몇 번 재import). 요청마다가 아니다.

> 결론: 서버에 남는 건 busy 격자뿐. 비번·GLS세션 at-rest = 0. 보안 표면이 크게 준다.

## 3. 엔드포인트 (2단계 OTP 비동기)

둘 다 **Supabase JWT 필수**(유저 식별).

```
POST /me/gls/import        { gls_id, gls_pw }
  → 200 { status: "IMPORTED",     summary }          # 저위험 → OTP 없이 바로 완료
  → 202 { status: "OTP_REQUIRED", attempt_id }       # worksmobile 2단계 요구

POST /me/gls/import/otp    { attempt_id, code }
  → 200 { status: "IMPORTED", summary }
  → 410 attempt 만료/없음 → 재시작
```

`summary` = `{ courses: 7, days: 5, slots: 24, imported_at }` 정도.

## 4. 진행중 로그인 상태 유지 (OTP suspend/resume)

**문제**: OTP가 두 HTTP 요청에 걸쳐 있어, 로그인 흐름을 요청 사이에 **살려둬야** 한다. (Render 상주 단일 인스턴스라 가능 — 서버리스면 불가능했음)

**방법**:
- `GLSClient`는 동기(blocking urllib) → **스레드풀**(`anyio.to_thread`)에서 `login()` 실행.
- `finish_works_email(ask=...)`의 `ask` 콜백을 **"OTP future를 blocking get"** 으로 주입. 스레드가 거기서 멈춤(suspend).
- **attempt 레지스트리**(in-memory, 단일 상주 인스턴스):
  ```
  attempts[attempt_id] = { task, otp_future, user_id, created_at }   # TTL ~3분, 만료 청소
  ```
- `POST .../otp` 가 `otp_future.set_result(code)` → 스레드의 `ask`가 깨어나 로그인 계속(resume) → 완료.

```
client          /import            레지스트리           스레드(login)         worksmobile
  │── id,pw ───▶│                                                               │
  │             │── spawn ─────────▶ attempt_id ──▶ login() 시작 ──────────────▶│ (SSO…)
  │             │                                   ask()=future.get()  ◀─2단계 요구
  │◀ 202 OTP_REQUIRED(attempt_id) ◀─ (future 대기)                               │
  │── code ────▶│ /otp                                                          │
  │             │── future.set_result(code) ──────▶ ask 깨어남 → OTP 제출 ─────▶│ ✓
  │             │                                   timetable()→격자→Supabase    │
  │◀ 200 IMPORTED(summary) ◀──────────────────────── 완료, 세션·pw 폐기         │
```

## 5. 성공 후 처리 (import)

1. `rows = client.timetable(hakbun, year, term)` → dsGrdMain
2. `busy = gls.grid.busy_from_rows(rows, day_count=…, start_hour=…, …)` (그룹 스키마와 동일 파라미터)
3. Supabase **`members` upsert**: `(group_id, id=앱유저, name, busy)` — 덮어쓰기
4. `GLSClient`·비밀번호 폐기, `summary` 반환

## 6. `finish_works_email` 리팩터 (유일한 코드 변경점, login 로직)

- 현재(`http.py`): `read_code = ask or input` → 터미널 `input()` 루프.
- 변경: `ask`는 이미 주입 가능(설계상 열려 있음). 웹에선 `ask = lambda prompt: otp_future.result()` 형태.
- 재시도(코드 불일치 응답 36/38) 시 **새 OTP 재요청** 흐름 → attempt를 다시 `OTP_REQUIRED`로 돌리는 신호 필요(§9-C).
- 단위테스트: 가짜 `ask`로 OTP 경로/비-OTP 경로 양쪽 커버 (네트워크 모킹).

## 7. 보안

- 비밀번호: **로그인 코루틴 안에서만**. 저장·로그 금지.
- GLS 세션/자격증명 **at-rest 0** (import 후 폐기).
- attempt **TTL 짧게**, 유저당 동시 import 1개, 로그인 시도 **레이트리밋**.
- 전 구간 HTTPS, JWT 필수. 저장은 `members.busy`(비민감)만.

## 8. 실패 / 엣지

| 상황 | 처리 |
|---|---|
| 비번 틀림 | 401, GLSError 메시지 정제 |
| OTP 틀림(36/38) | 재입력 유도(§9-C) |
| attempt 만료/유실(Render 슬립) | 410 → 재시작 (OTP 창 ~1분이라 드묾) |
| 저위험 무-OTP | `/import`에서 바로 IMPORTED |
| GLS 스키마 변동 | 500 + 안전 메시지, 서버 로그만 상세 |

## 9. 미결정 — 합의 필요

- **A. 유저 ↔ member/group 매핑**: 앱 유저를 어느 `group_id`의 `members.id`로 넣나? (유저당 개인 그룹? 공유 그룹에 멤버로? `id`=Supabase user id vs 학번?)
- **B. 재import**: 같은 (group, user) **덮어쓰기 upsert** — *추천*.
- **C. OTP 재시도 UX**: 틀렸을 때 같은 attempt에서 재입력 vs 새 attempt. (worksmobile은 재발송이 필요할 수 있음)

## 10. 구현 단계 (후속 실행계획 밑그림)

1. `finish_works_email`를 `ask`-콜백 기반으로 확정 + 단위테스트(가짜 ask, 네트워크 모킹).
2. attempt 레지스트리 모듈 + `GLSClient.login` 스레드풀 실행 래퍼.
3. `/me/gls/import`, `/me/gls/import/otp` 라우트 + Pydantic 스키마.
4. 성공 시 `grid.busy_from_rows` → Supabase `members` upsert (db 계층 확장).
5. JWT 검증 의존성(현재 미구현이면 선행).
6. 통합 테스트(모킹된 GLS 전 흐름: 비-OTP / OTP / 실패).

---

**요약**: 상주 서버라 OTP suspend/resume가 성립하고, "일회성 import" 모델이라 세션 캐싱·비번 저장이 **전부 불필요**해진다. 유일한 login-로직 변경은 `finish_works_email`의 OTP 입력을 future 콜백으로 바꾸는 것. 남은 합의점은 §9(A/B/C)뿐.
