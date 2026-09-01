from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)


class TokenPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TwoFactorChallengeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: str
    two_factor_required: bool = True


class ChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: str
    code: str = Field(min_length=1, max_length=16)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str


class SetupTwoFactorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    otpauth_uri: str
    qr_data_uri: str


class VerifyTwoFactorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    refresh_token: str
    backup_codes: list[str]


class ConfirmTwoFactorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=6, max_length=16)


class DisableTwoFactorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=16)


class PasswordRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=1, max_length=128)


class MeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: EmailStr
    name: str
    totp_enabled: bool
