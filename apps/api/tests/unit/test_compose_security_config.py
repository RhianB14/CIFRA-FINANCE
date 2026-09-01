from pathlib import Path

import yaml

from app.core.settings import Settings, ensure_secure_configuration

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_compose_api_defaults_satisfy_security_configuration() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    environment = compose["services"]["api"]["environment"]
    values = {
        "environment": environment["ENVIRONMENT"],
        "jwt_signing_key": environment["JWT_SIGNING_KEY"].split(":-", 1)[1][:-1],
        "totp_encryption_key": environment["TOTP_ENCRYPTION_KEY"].split(":-", 1)[1][:-1],
        "backup_code_pepper": environment["BACKUP_CODE_PEPPER"].split(":-", 1)[1][:-1],
    }
    settings = Settings.model_validate(values)
    ensure_secure_configuration(settings)
    assert len(settings.backup_code_pepper) >= 32
