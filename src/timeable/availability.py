"""개수기반 호출 핸들러.

TimeAble의 핵심 로직. 각 시간 칸마다 '몇 명이 비는지'를 세고(개수),
수위(min_free) 값으로 호출하면 그 기준을 넘는 칸·연속 블록만 돌려준다.
수위 슬라이더는 이 `handler`를 호출해서 지형(호수)을 다시 그린다.
"""

from __future__ import annotations

from .schedule import day_count, slot_count, slot_label


def free_counts(data: dict) -> list[list[int]]:
    """각 칸마다 비는 인원 수를 센다.

    반환: ``grid[day][slot]`` = 그 칸에 수업이 없는(자유인) 학생 수.
    지형 높이의 반대값이자 수위 판정의 기준이 된다.
    """
    nd, ns = day_count(data), slot_count(data)
    grid = [[0] * ns for _ in range(nd)]
    for student in data["students"]:
        busy = student["busy"]
        for d in range(nd):
            row = busy[d]
            for t in range(ns):
                if not row[t]:
                    grid[d][t] += 1
    return grid


def _free_ids(data: dict) -> list[list[list[str]]]:
    """각 칸마다 자유인 학생 id 목록. 블록의 공통 참석자 계산에 쓴다."""
    nd, ns = day_count(data), slot_count(data)
    grid = [[[] for _ in range(ns)] for _ in range(nd)]
    for student in data["students"]:
        busy = student["busy"]
        sid = student["id"]
        for d in range(nd):
            row = busy[d]
            for t in range(ns):
                if not row[t]:
                    grid[d][t].append(sid)
    return grid


def handler(
    data: dict,
    min_free: int,
    min_duration: int = 1,
) -> list[dict]:
    """수위(min_free) 기준으로 '그만큼 비는' 연속 블록을 돌려준다.

    개수기반 호출의 핵심 진입점. ``min_free`` 이상이 비는 칸들이 ``min_duration``
    칸 이상 연속으로 이어지는 구간을 하나의 블록으로 묶는다.

    Args:
        data: 시간표 데이터 dict.
        min_free: 수위. 이 인원 수 이상이 비어야 블록으로 인정.
        min_duration: 최소 연속 칸 수(기본 1칸 = 30분).

    Returns:
        블록 dict 리스트. 각 블록::

            {
              "day_index": 3, "day": "Thu",
              "start_slot": 12, "end_slot": 16,   # [start, end)
              "length": 4,                         # 연속 칸 수
              "start_label": "15:00", "end_label": "17:00",
              "min_free": 9,                       # 블록 안 최소 자유 인원
              "attendees": ["s03", "s07", ...],    # 블록 내내 자유인 학생
              "attendance": 8,                     # len(attendees)
            }
    """
    counts = free_counts(data)
    free_ids = _free_ids(data)
    nd, ns = day_count(data), slot_count(data)
    blocks: list[dict] = []

    for d in range(nd):
        t = 0
        while t < ns:
            if counts[d][t] < min_free:
                t += 1
                continue
            # 수위를 넘는 칸이 이어지는 동안 확장한다.
            start = t
            while t < ns and counts[d][t] >= min_free:
                t += 1
            end = t
            length = end - start
            if length < min_duration:
                continue

            block_min_free = min(counts[d][s] for s in range(start, end))
            # 블록 내내 비는 공통 참석자 = 각 칸 자유 집합의 교집합.
            attendees = set(free_ids[d][start])
            for s in range(start + 1, end):
                attendees &= set(free_ids[d][s])

            blocks.append(
                {
                    "day_index": d,
                    "day": data["days"][d],
                    "start_slot": start,
                    "end_slot": end,
                    "length": length,
                    "start_label": slot_label(data, start),
                    "end_label": slot_label(data, end),
                    "min_free": block_min_free,
                    "attendees": sorted(attendees),
                    "attendance": len(attendees),
                }
            )
    return blocks


def top_candidates(data: dict, min_free: int, k: int = 3) -> list[dict]:
    """상위 k개 모임 후보. 참석 인원 많은 순, 같으면 길이 긴 순.

    기획안의 '추천 리스트'(상위 3개 시간대)에 그대로 쓴다.
    """
    blocks = handler(data, min_free)
    blocks.sort(key=lambda b: (b["attendance"], b["length"]), reverse=True)
    return blocks[:k]


def _demo() -> None:
    """`uv run python -m timeable.availability` 로 동작을 눈으로 확인."""
    from pathlib import Path

    from .schedule import load

    data_path = Path(__file__).resolve().parents[2] / "data" / "dummy_students.json"
    data = load(data_path)
    total = len(data["students"])
    counts = free_counts(data)

    print(f"# 학생 {total}명 · 비는 인원 격자 (요일 x 시간)")
    header = "      " + " ".join(slot_label(data, t)[:2] for t in range(slot_count(data)))
    print(header)
    for d, day in enumerate(data["days"]):
        row = " ".join(f"{counts[d][t]:2d}" for t in range(slot_count(data)))
        print(f"{day:>4}  {row}")

    for level in (total, total - 1, total * 2 // 3):
        print(f"\n# 수위 min_free={level} · 상위 후보")
        cands = top_candidates(data, level, k=3)
        if not cands:
            print("  (해당 블록 없음)")
        for b in cands:
            print(
                f"  {b['day']} {b['start_label']}-{b['end_label']} "
                f"· {b['attendance']}명 가능 · 최소 {b['min_free']}명 빔"
            )


if __name__ == "__main__":
    _demo()
