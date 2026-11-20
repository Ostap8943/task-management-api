from pydantic import PositiveInt, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: SecretStr
    access_token_minutes: PositiveInt = 30
    overdue_check_seconds: PositiveInt = 60

    @field_validator("jwt_secret")
    @classmethod
    def validate_secret(cls, secret: SecretStr) -> SecretStr:
        if len(secret.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("JWT_SECRET must be at least 32 bytes")
        return secret
