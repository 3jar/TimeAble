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
