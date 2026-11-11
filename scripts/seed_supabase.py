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
