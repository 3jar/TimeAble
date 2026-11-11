"""GLS 시간표 import 글루 — 로그인 → 시간표 → busy 격자.

`login_flow.LoginRegistry.start(run)` 에 넘길 `run(ask)` 의 몸통. 네트워크(GLS)에
의존하므로 라우트 테스트에선 이 함수를 통째로 mock 한다.
"""
from __future__ import annotations

from datetime import date

from .grid import busy_from_rows
from .http import GLSClient


def current_year_semester(today: date | None = None) -> tuple[int, str]:
    """대략적인 학기 추정. 3~8월 → 1학기, 그 외 → 2학기."""
    today = today or date.today()
    return today.year, "1" if 3 <= today.month <= 8 else "2"


def import_timetable_busy(
    gls_id: str,
    gls_pw: str,
    ask,
    *,
    year: int | None = None,
    semester: str | None = None,
    grid_opts: dict | None = None,
) -> dict:
    """킹고 로그인(필요시 ask로 OTP) → 내 시간표 → busy 격자.

    Returns ``{"busy": [[bool]], "courses": int, "year": int, "semester": str}``.
    비밀번호는 이 함수 밖으로 나가지 않는다(호출부에서 import 후 폐기).
    """
    if year is None or semester is None:
        y, s = current_year_semester()
        year = year or y
        semester = semester or s
    client = GLSClient()
    client.login(gls_id, gls_pw, ask=ask)
    rows = client.timetable(client.active_hakbun, str(year), str(semester))
    busy = busy_from_rows(rows, **(grid_opts or {}))
    return {"busy": busy, "courses": len(rows), "year": int(year), "semester": str(semester)}
