from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr


class UserRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


# ── User Schemas ──────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str
    password2: str


class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    is_active: bool
    is_superuser: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    username: Optional[str] = None


# ── Token Schemas ─────────────────────────────────────────────────────────────
class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: str | None = None


class TokenData(BaseModel):
    email: Optional[str] = None


# ── Tenant Schemas ────────────────────────────────────────────────────────────
class TenantCreate(BaseModel):
    name: str
    slug: str


class TenantResponse(BaseModel):
    id: int
    name: str
    slug: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── TenantUser Schemas ──────────────────────────────────────────────────────────
class TenantUserResponse(BaseModel):
    tenant: TenantResponse
    role: UserRole
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserWithTenants(BaseModel):
    tenant_memberships: List[TenantUserResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ── TenantMember Schemas ───────────────────────────────────────────────────────
class InviteUser(BaseModel):
    email: EmailStr
    role: Optional[UserRole] = UserRole.MEMBER


class MemberResponse(BaseModel):
    user: UserResponse
    role: UserRole
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Note Schemas ────────────────────────────────────────────────────────────────
class NoteCreate(BaseModel):
    title: str
    content: str


class NoteResponse(BaseModel):
    id: int
    tenant_id: int
    author_id: int
    title: str
    content: str
    is_archived: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    is_archived: Optional[bool] = None


# ── Document Schemas ─────────────────────────────────────────────────────────────
class DocumentCreate(BaseModel):
    title: str
    content: str


class DocumentResponse(BaseModel):
    id: int
    tenant_id: int
    author_id: int
    title: str
    chunk_count: int
    is_indexed: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentIngestResponse(BaseModel):
    document_id: int
    title: str
    chunks_stored: int
    collection: str
    status: str
    chunk_strategy: str = "token"
    avg_tokens_per_chunk: int = 0.0
