from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://ava:ava@localhost:5432/ava"
    paperless_url: str = "http://paperless:8000"
    paperless_token: str = "demo_paperless_token_1234567890abcdef"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


def get_settings() -> Settings:
    return Settings()
