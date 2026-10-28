from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Role = Literal["owner", "administrator", "analyst", "viewer"]
Category = Literal["google_drive", "database", "api", "file_storage", "local_file"]
Name = Annotated[str, Field(min_length=1, max_length=160)]
Password = Annotated[str, Field(min_length=12, max_length=128)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("name", "email", check_fields=False, mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class Email(Input):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize(cls, value):
        return value.lower()


class Register(Email):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    password: Password


class Login(Email):
    password: Annotated[str, Field(min_length=1, max_length=128)]


class ChangePassword(Input):
    current_password: str = Field(max_length=128)
    password: Password


class ResetPassword(Input):
    token: str = Field(min_length=32, max_length=128)
    password: Password


class Token(Input):
    token: str = Field(min_length=32, max_length=128)


class InstitutionInput(Input):
    name: Name


class SettingsInput(InstitutionInput):
    description: str = Field(default="", max_length=5000)


class InviteInput(Email):
    role: Role


class RoleInput(Input):
    role: Role


class StatusInput(Input):
    status: Literal["active", "suspended"]


class AccountStatus(Input):
    status: Literal["active", "disabled"]


class SourceInput(Input):
    name: Name
    category: Category
    description: str = Field(default="", max_length=5000)
    reference: str = Field(default="", max_length=500, pattern=r"^[^?@#]*$")


class DatasetInput(Input):
    name: Name
    description: str = Field(default="", max_length=5000)
    source_category: Category
    file_type: str = Field(default="", max_length=80)
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    status: Literal["draft", "registered", "archived"] = "draft"
    tags: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(
        default_factory=list, max_length=30
    )
    record_count: int | None = Field(default=None, ge=0, le=9223372036854775807)
    storage_bytes: int | None = Field(default=None, ge=0, le=9223372036854775807)
    source_reference: str = Field(default="", max_length=500, pattern=r"^[^?@#]*$")
    owner_id: UUID
    source_id: UUID | None = None


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RecordOut(Out):
    id: UUID
    created_at: datetime
    updated_at: datetime


class UserOut(RecordOut):
    email: str
    name: str
    status: str


class Me(Out):
    user: UserOut
    csrf: str
    platform_admin: bool


class InstitutionOut(RecordOut):
    name: str
    status: str
    created_by: UUID


class Workspace(Out):
    institution: InstitutionOut
    role: Role


class SettingsOut(Out):
    name: str
    description: str


class MemberOut(Out):
    id: UUID
    user_id: UUID
    role: Role
    name: str
    email: str
    status: str


class InviteOut(RecordOut):
    email: str
    role: Role
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None


class SourceOut(SourceInput, RecordOut):
    institution_id: UUID
    status: str
    created_by: UUID


class DatasetOut(DatasetInput, RecordOut):
    institution_id: UUID


class AuditOut(RecordOut):
    institution_id: UUID | None
    actor_id: UUID | None
    action: str
    target: str
    request_id: str


class SessionOut(RecordOut):
    expires_at: datetime


class Message(Out):
    message: str


T = TypeVar("T")


class Page(Out, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int
