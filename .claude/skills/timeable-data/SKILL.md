---
name: timeable-data
description: Use when working with TimeAble timetable data or availability logic - documents the dummy data JSON schema, how to regenerate it, and the count-based call handler API (free_counts / handler / top_candidates)
---

# TimeAble 데이터 & 개수기반 핸들러

TimeAble은 등록한 학생들의 시간표를 합쳐 공통 빈 시간을 복셀 지형도로 보여준다.
이 스킬은 그 바탕이 되는 **더미 데이터 스키마**와 **개수기반 호출 핸들러**의 사용법을 기록한다.

## 핵심 개념

- 하루는 30분 단위 칸으로 쪼갠다. 9~21시 → **24칸/일**, 월~금 → **5일**.
- 각 칸 상태는 2단계: `busy[day][slot]`이 `True`면 수업/바쁨, `False`면 빔(자유).
- **개수기반**: 각 칸마다 "몇 명이 비는지"를 센 값이 지형 높이의 반대값이자 수위 판정 기준.
- **수위(min_free)**: "최소 몇 명이 비어야 하는가". 수위 슬라이더가 `handler(data, min_free)`를 호출해 지형(호수)을 다시 그린다.

## 파일 구조 (TimeAble 루트 기준)

```
TimeAble/
├── pyproject.toml              # uv 프로젝트 (의존성 0, stdlib만)
├── generate_dummy.py           # 더미 20명 생성 → data/dummy_students.json
├── data/dummy_students.json    # 생성 결과 (source of truth, 프론트가 그대로 fetch)
├── src/timeable/
│   ├── schedule.py             # 데이터 모델·로더·slot_label
│   └── availability.py         # 개수기반 호출 핸들러
└── tests/test_availability.py  # unittest
```

## 데이터 스키마 (`data/dummy_students.json`)

```jsonc
{
  "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
  "start_hour": 9,          // 하루 시작 (포함)
  "end_hour": 21,           // 하루 끝 (제외)
  "slot_minutes": 30,       // 한 칸 길이 → 24칸/일
  "students": [
    {
      "id": "s01",
      "name": "김민준",
      "dept": "컴퓨터공학",
      "year": 2,
      "color": "#4FA3D1",   // 캐릭터 색
      "busy": [[false, true, ...], ...]  // [요일 5][칸 24], true = 바쁨
    }
    // ... 20명
  ]
}
```

더미는 완전 랜덤이 아니라 4개 코호트(학과·학년)별 공통 수업 블록 + 개인 선택 과목으로
생성해, 기획안의 '읽히는 지형'(월~수 오전 고원, 점심 계곡, 금요일 오후 평야)이 나온다.
시드 고정이라 재실행해도 동일.

**재생성:**
```bash
uv run python generate_dummy.py
```

## 핸들러 API (`src/timeable/availability.py`)

모든 함수는 평범한 `data` dict를 받는다 (`schedule.load(path)`로 로드).

### `free_counts(data) -> list[list[int]]`
각 칸의 비는 인원 수. `grid[day][slot]`.

### `handler(data, min_free, min_duration=1) -> list[dict]`
**개수기반 호출의 핵심 진입점.** `min_free` 이상이 비는 칸들이 `min_duration` 칸 이상
연속되는 구간을 블록으로 묶어 돌려준다. 각 블록:

```jsonc
{
  "day_index": 3, "day": "Thu",
  "start_slot": 12, "end_slot": 16,   // [start, end)
  "length": 4,                         // 연속 칸 수
  "start_label": "15:00", "end_label": "17:00",
  "min_free": 9,                       // 블록 안 최소 자유 인원
  "attendees": ["s03", "s07", ...],    // 블록 내내 자유인 학생 (칸별 자유 집합의 교집합)
  "attendance": 8                      // len(attendees) = 실제 모임 가능 인원
}
```

> `min_free`(칸별 자유 인원의 바닥)와 `attendance`(블록 내내 공통 참석)는 다를 수 있다.
> 모임 확정에 의미 있는 숫자는 `attendance`.

### `top_candidates(data, min_free, k=3) -> list[dict]`
상위 k개 후보. 참석 인원 많은 순 → 같으면 길이 긴 순. 기획안 '추천 리스트'용.

### 사용 예

```python
from timeable.schedule import load
from timeable.availability import handler, top_candidates

data = load("data/dummy_students.json")

# 수위 15: 15명 이상 비는, 1시간(2칸) 이상 연속 블록
blocks = handler(data, min_free=15, min_duration=2)

# 수위 18 상위 3개 모임 후보
for b in top_candidates(data, min_free=18, k=3):
    print(f"{b['day']} {b['start_label']}-{b['end_label']} · {b['attendance']}명 가능")
```

### 눈으로 확인 (데모)
```bash
uv run python -m timeable.availability   # 비는 인원 격자 + 수위별 상위 후보 출력
```

## 테스트
```bash
uv run python -m unittest discover -s tests
```

## 다음 확장 지점

- 2단계(바쁨/빔) → 3단계(수업/애매/자유)로 넓히려면 `busy`를 상태 enum으로 바꾸고
  `free_counts`가 '애매'를 별도 카운트하도록 확장 (기획안의 반투명 캐릭터·늪지 연출용).
- `attendees`에 핀 고정(필수 인원) 필터를 추가하면 기획안의 '필수 인원 지정'이 된다.
- 블록 결과를 three.js 프론트가 그대로 소비해 호수/후보 리스트를 렌더.
