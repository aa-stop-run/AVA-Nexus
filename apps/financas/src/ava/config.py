from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    paperless_url: str
    paperless_token: str
    worker_shared_token: str
    llm_base_url: str


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
