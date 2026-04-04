from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, EmailStr, ConfigDict


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"
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
