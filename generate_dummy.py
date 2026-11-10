"""더미 시간표 생성기.

학생 20명을 4개 학과·학년 묶음(코호트)으로 나눠, 코호트별 공통 수업 블록 위에
개인 선택 과목을 얹는다. 완전 랜덤이 아니라 패턴을 깔아서 기획안의 '읽히는 지형'
(월~수 오전 고원, 점심 계곡, 금요일 오후 평야)이 나오게 한다.

실행::

    uv run python generate_dummy.py

결과는 data/dummy_students.json 에 저장된다. 시드 고정이라 항상 같은 결과.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
START_HOUR, END_HOUR, SLOT_MINUTES = 9, 21, 30
N_SLOTS = (END_HOUR - START_HOUR) * 60 // SLOT_MINUTES  # 24
SEED = 42

# 코호트: (학과, 학년, 인원, 공통 수업 블록[(요일, 시작칸, 끝칸(제외))])
# 시작칸 0 = 09:00, 칸 하나 = 30분. 점심(칸 6~7 = 12:00~13:00)은 대체로 비워 둔다.
COHORTS = [
    ("컴퓨터공학", 1, 5, [(0, 0, 6), (2, 0, 4), (4, 2, 6)]),   # 월 오전·수 오전·금 오전
    ("컴퓨터공학", 2, 5, [(1, 2, 6), (2, 8, 12), (3, 0, 4)]),  # 화 오전·수 오후·목 오전
    ("전자공학", 2, 5, [(0, 8, 14), (2, 0, 6), (3, 10, 14)]),  # 월 오후·수 오전·목 오후
    ("경영학", 3, 5, [(1, 0, 6), (3, 8, 14), (4, 0, 3)]),      # 화 오전·목 오후·금 오전
]

NAMES = [
    "김민준", "이서연", "박도윤", "최지우", "정하준",
    "강서윤", "조은우", "윤지호", "장수아", "임예준",
    "한유진", "오시우", "서하은", "신준서", "권나윤",
    "황민서", "안지안", "송채원", "홍주원", "전다은",
]

COLORS = [
    "#4FA3D1", "#E6734F", "#6DBF8B", "#C96FD1", "#E0B23C",
    "#5566D6", "#D94F7A", "#3FB0A8", "#8A6DD6", "#D1A14F",
    "#4FBF6D", "#D6565D", "#6D9FD6", "#D68A4F", "#9BD64F",
    "#D64FB0", "#4FD6C4", "#D6C44F", "#7A4FD6", "#4F7AD6",
]


def _mark(busy: list[list[bool]], day: int, start: int, end: int) -> None:
    for t in range(start, min(end, N_SLOTS)):
        busy[day][t] = True


def _add_electives(busy: list[list[bool]], rng: random.Random) -> None:
    """개인 선택 과목 1~3개. 점심은 피하고 오후/저녁 위주로 2~4칸씩."""
    for _ in range(rng.randint(1, 3)):
        day = rng.randrange(len(DAYS))
        length = rng.randint(2, 4)
        # 오후 1시(칸 8) ~ 저녁 사이에서 시작해 점심 계곡을 보존한다.
        start = rng.randint(8, N_SLOTS - length)
        _mark(busy, day, start, start + length)


def build() -> dict:
    rng = random.Random(SEED)
    students: list[dict] = []
    idx = 0
    for dept, year, n, blocks in COHORTS:
        for _ in range(n):
            busy = [[False] * N_SLOTS for _ in range(len(DAYS))]
            for day, start, end in blocks:
                _mark(busy, day, start, end)
            _add_electives(busy, rng)
            students.append(
                {
                    "id": f"s{idx + 1:02d}",
                    "name": NAMES[idx],
                    "dept": dept,
                    "year": year,
                    "color": COLORS[idx],
                    "busy": busy,
                }
            )
            idx += 1

    return {
        "days": DAYS,
        "start_hour": START_HOUR,
        "end_hour": END_HOUR,
        "slot_minutes": SLOT_MINUTES,
        "students": students,
    }


def main() -> None:
    data = build()
    out = Path(__file__).resolve().parent / "data" / "dummy_students.json"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"생성 완료: {out} · 학생 {len(data['students'])}명")


if __name__ == "__main__":
    main()
