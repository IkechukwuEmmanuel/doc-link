from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+asyncpg://spacepad:spacepad@localhost:5432/spacepad"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:5173"

    # Upload caps (Phase 3). Kept here as configurable constants, not magic numbers.
    anon_max_files_per_pad: int = 5
    anon_max_file_bytes: int = 10 * 1024 * 1024
    anon_max_total_bytes: int = 25 * 1024 * 1024
    auth_max_files_per_pad: int = 50
    auth_max_file_bytes: int = 50 * 1024 * 1024
    auth_max_total_bytes: int = 500 * 1024 * 1024

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
