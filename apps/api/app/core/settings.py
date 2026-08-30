from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "cifra-api"
    database_url: str = "postgresql://cifra:cifra_local_development@localhost:5432/cifra"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
