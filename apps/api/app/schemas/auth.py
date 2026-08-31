from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TwoFactorRequired(BaseModel):
    challenge_id: str
    two_factor_required: bool = True


class ChallengeRequest(BaseModel):
    challenge_id: str
    code: str = Field(min_length=1, max_length=16)


class RefreshRequest(BaseModel):
    refresh_token: str


class SetupTwoFactorResponse(BaseModel):
    otpauth_uri: str


class VerifyTwoFactorResponse(BaseModel):
    access_token: str
    refresh_token: str
    backup_codes: list[str]


class ConfirmTwoFactorRequest(BaseModel):
    code: str = Field(min_length=6, max_length=16)


class DisableTwoFactorRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=16)


class MeResponse(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    totp_enabled: bool
