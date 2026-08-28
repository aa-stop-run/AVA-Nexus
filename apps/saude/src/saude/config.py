from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://ava:ava@localhost:5433/ava"
    servidor_porta: int = 8003
    paperless_url: str = "http://paperless:8000"
    paperless_token: str = "demo_paperless_token_1234567890abcdef"
    google_calendar_ical_url: str = "https://calendar.google.com/calendar/ical/example%40gmail.com/private-demo-token/basic.ics"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
