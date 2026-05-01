from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


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
    avg_tokens_per_chunk: int = 0


# ── Query Schemas  ──────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    question: str
    top_k: int = 5

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, v: str) -> str:
        if not v or len(v.strip()) < 3:
            raise ValueError("Question must be at least 3 characters!")
        return v.strip()

    @field_validator("top_k")
    @classmethod
    def top_k_range(cls, v: int) -> int:
        if v < 1 or v > 20:
            raise ValueError("top_k must be between 1 and 20!")
        return v


class RetrivedChunk(BaseModel):
    text: str
    score: float
    document_id: str
    chunk_index: int
    title: str = ""
    metadata: dict = {}


class QueryResponse(BaseModel):
    question: str
    tenant_slug: str
    chunks_retrieved: int
    results: list[RetrivedChunk]


# ── Answer Schema ───────────────────────────────────────────────────────
class SourceCitation(BaseModel):
    document_title: str
    chunk_preview: str
    relevance_score: float
    document_id: int
    chunk_index: int


class AnswerResponse(BaseModel):
    question: str
    answer: str
    sources: list[SourceCitation]
    chunks_used: int
    model: str
    tenant_slug: str
