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

    totp_encryption_key: str | None = None
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


CONFIG_VALIDATION_EXEMPT_ENVIRONMENTS = frozenset({"test"})


def ensure_secure_configuration(
    settings: Settings,
    exempt_environments: frozenset[str] | set[str] | None = None,
) -> None:
    exemptions = (
        CONFIG_VALIDATION_EXEMPT_ENVIRONMENTS
        if exempt_environments is None
        else exempt_environments
    )
    if settings.environment in exemptions:
        return
    problems: list[str] = []
    minimum_signing_key_length = 32
    if len(settings.jwt_signing_key) < minimum_signing_key_length:
        problems.append(
            "jwt_signing_key must be set with at least 32 characters outside the test environment"
        )
    if not settings.totp_encryption_key:
        problems.append("totp_encryption_key must be set outside the test environment")
    elif settings.totp_encryption_key == settings.jwt_signing_key:
        problems.append("totp_encryption_key must differ from jwt_signing_key")
    if problems:
        raise RuntimeError("; ".join(problems))
