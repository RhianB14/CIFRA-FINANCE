from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "cifra-api"
    environment: str = "development"
    database_url: str = "postgresql://cifra:cifra_local_development@localhost:5432/cifra"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"

    jwt_signing_key: str = ""
    jwt_issuer: str = "cifra-api"
    jwt_audience: str = "cifra-clients"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    two_factor_challenge_ttl_seconds: int = 300

    totp_encryption_key: str = ""
    totp_issuer: str = "Cifra"
    totp_drift_seconds: int = 30

    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536
    argon2_parallelism: int = 4
    argon2_hash_length: int = 32
    password_min_length: int = 12
    password_max_length: int = 128

    hibp_enabled: bool = False
    hibp_timeout_seconds: float = 2.0
    hibp_base_url: str = "https://api.pwnedpasswords.com"
    external_http_timeout_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
