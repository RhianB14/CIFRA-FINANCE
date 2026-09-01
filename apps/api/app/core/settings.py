import base64
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "cifra-api"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://cifra:cifra_local_development@localhost:5432/cifra"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"

    jwt_signing_key: str = ""
    jwt_issuer: str = "cifra-api"
    jwt_audience: str = "cifra-clients"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    two_factor_challenge_ttl_seconds: int = 300

    totp_encryption_key: str = ""
    backup_code_pepper: str = ""
    totp_issuer: str = "CIFRA"
    totp_period: int = 30
    totp_drift_seconds: int = 30

    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536
    argon2_parallelism: int = 4
    argon2_hash_length: int = 32
    password_min_length: int = 12
    password_max_length: int = 128

    hibp_enabled: bool = False
    hibp_timeout_seconds: float = 2.0
    hibp_base_url: str = ""
    external_http_timeout_seconds: float = 5.0

    trust_proxy_headers: bool = False
    trusted_proxies: str = ""
    cors_allowed_origins: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


def trusted_proxies_list(settings: Settings) -> tuple[str, ...]:
    return tuple(item.strip() for item in settings.trusted_proxies.split(",") if item.strip())


CONFIG_VALIDATION_EXEMPT_ENVIRONMENTS = frozenset({"test"})

DEVELOPMENT_SECRET_MARKERS: tuple[str, ...] = (
    "dev-only",
    "change-me",
)

FERNET_KEY_BYTES = 32


def _validate_secret_format(name: str, value: str, environment: str) -> str | None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        return f"{name} must be encodable as utf-8: {error}"
    if environment == "production":
        for marker in DEVELOPMENT_SECRET_MARKERS:
            if marker in value:
                return f"{name} must not contain the development marker '{marker}' in production"
    return None


def _validate_fernet_key(name: str, value: str) -> str | None:
    try:
        key_bytes = base64.urlsafe_b64decode(value.encode("utf-8"))
    except (ValueError, TypeError) as error:
        return f"{name} must be a valid Fernet key: {error}"
    if len(key_bytes) != FERNET_KEY_BYTES:
        return f"{name} must be a valid Fernet key"
    return None


def ensure_secure_configuration(
    settings: Settings,
    exempt_environments: frozenset[str] | set[str] | None = None,
) -> None:
    exemptions = (
        CONFIG_VALIDATION_EXEMPT_ENVIRONMENTS
        if exempt_environments is None
        else exempt_environments
    )
    problems: list[str] = []
    if settings.trust_proxy_headers and not trusted_proxies_list(settings):
        problems.append(
            "trusted_proxies must list at least one proxy when trust_proxy_headers is enabled"
        )
    if settings.environment in exemptions:
        if problems:
            raise RuntimeError("; ".join(problems))
        return
    if settings.totp_period <= 0:
        problems.append("totp_period must be greater than zero")
    if settings.totp_drift_seconds < 0:
        problems.append("totp_drift_seconds must be greater than or equal to zero")
    if settings.access_token_ttl_minutes <= 0:
        problems.append("access_token_ttl_minutes must be greater than zero")
    if settings.refresh_token_ttl_days <= 0:
        problems.append("refresh_token_ttl_days must be greater than zero")
    if settings.two_factor_challenge_ttl_seconds <= 0:
        problems.append("two_factor_challenge_ttl_seconds must be greater than zero")
    if settings.hibp_timeout_seconds <= 0:
        problems.append("hibp_timeout_seconds must be greater than zero")
    if settings.trust_proxy_headers and not trusted_proxies_list(settings):
        problems.append(
            "trusted_proxies must list at least one proxy when trust_proxy_headers is enabled"
        )
    if len(settings.jwt_signing_key.encode("utf-8", errors="replace")) < 32:
        problems.append(
            "jwt_signing_key must be set with at least 32 bytes outside the test environment"
        )
    jwt_problem = _validate_secret_format(
        "jwt_signing_key", settings.jwt_signing_key, settings.environment
    )
    if jwt_problem:
        problems.append(jwt_problem)
    if not settings.totp_encryption_key:
        problems.append("totp_encryption_key must be set outside the test environment")
    else:
        fernet_problem = _validate_fernet_key("totp_encryption_key", settings.totp_encryption_key)
        if fernet_problem:
            problems.append(fernet_problem)
        else:
            secret_problem = _validate_secret_format(
                "totp_encryption_key", settings.totp_encryption_key, settings.environment
            )
            if secret_problem:
                problems.append(secret_problem)
    if not settings.backup_code_pepper:
        problems.append("backup_code_pepper must be set outside the test environment")
    else:
        if len(settings.backup_code_pepper.encode("utf-8", errors="replace")) < 32:
            problems.append("backup_code_pepper must contain at least 32 bytes")
        pepper_problem = _validate_secret_format(
            "backup_code_pepper", settings.backup_code_pepper, settings.environment
        )
        if pepper_problem:
            problems.append(pepper_problem)
    if settings.backup_code_pepper and settings.backup_code_pepper == settings.jwt_signing_key:
        problems.append("backup_code_pepper must differ from jwt_signing_key")
    if settings.backup_code_pepper and settings.backup_code_pepper == settings.totp_encryption_key:
        problems.append("backup_code_pepper must differ from totp_encryption_key")
    if settings.totp_encryption_key and settings.totp_encryption_key == settings.jwt_signing_key:
        problems.append("totp_encryption_key must differ from jwt_signing_key")
    if problems:
        raise RuntimeError("; ".join(problems))
