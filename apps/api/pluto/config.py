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
    cache_remote_files: bool = False
    max_record_bytes: int = Field(default=4194304, ge=1024)
    archive_expansion_bytes: int = Field(default=536870912, ge=1)
    max_image_pixels: int = Field(default=40000000, ge=1)
    parser_timeout: int = Field(default=600, ge=1)
    media_keyframes: int = Field(default=1, ge=1, le=8)
    retention_days: int = Field(default=0, ge=0)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_picker_api_key: str = ""
    google_project_number: str = ""
    credential_encryption_key: str = ""
    postgres_allowed_hosts: str = ""
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
