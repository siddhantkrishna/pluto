from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../../.env", extra="ignore", hide_input_in_errors=True
    )
    database_url: str
    migration_database_url: str = ""
    environment: str = "development"
    web_origin: str = "http://localhost:3000"
    session_hours: int = Field(default=12, ge=1, le=168)
    mail_directory: str = ".dev-mail"
    object_directory: str = ".objects"
    institution_storage_bytes: int = Field(default=1099511627776, ge=1)
    max_upload_bytes: int = Field(default=10737418240, ge=1)
    worker_institution: str = ""
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    @model_validator(mode="after")
    def production(self):
        origin = urlsplit(self.web_origin)
        if (
            origin.scheme not in ("http", "https")
            or not origin.hostname
            or origin.path
            or origin.query
            or origin.fragment
            or origin.username
        ):
            raise ValueError("WEB_ORIGIN must be an HTTP(S) origin without a path")
        if self.environment not in ("development", "test", "production"):
            raise ValueError("Invalid environment")
        if self.environment == "production" and (
            not self.web_origin.startswith("https://") or not self.smtp_host or not self.smtp_from
        ):
            raise ValueError("Production requires HTTPS, SMTP and a sender")
        return self

    @property
    def secure(self):
        return self.environment == "production"


settings = Settings()
