from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from .. import auth, models, schemas
from ..database import get_db

router = APIRouter(
    prefix="/tenants/{slug}/notes",
    tags=["Notes"],
)


@router.post(
    "/", response_model=schemas.NoteResponse, status_code=status.HTTP_201_CREATED
)
def create_note(
    slug: str,
    note_in: schemas.NoteCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    tenant = auth.get_tenant_or_404(
        db, slug, current_user, required_role=models.UserRole.MEMBER
    )

    new_note = models.Note(
        tenant_id=tenant.id,
        author_id=current_user.id,
        title=note_in.title,
        content=note_in.content,
    )
    db.add(new_note)
    db.commit()
    db.refresh(new_note)

    return new_note


@router.get("/", response_model=List[schemas.NoteResponse])
def list_notes(
    slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    tenant = auth.get_tenant_or_404(
        db, slug, current_user, required_role=models.UserRole.MEMBER
    )

    notes = (
        db.query(models.Note)
        .filter(
            models.Note.tenant_id == tenant.id,
            models.Note.is_archived.is_(False),
        )
        .order_by(models.Note.created_at.desc())
        .all()
    )
    return notes


# ── SEARCH must come BEFORE /{note_id} ───────────────────────────────────────
# FastAPI matches routes top to bottom. If /{note_id} comes first,
# "search" gets interpreted as a note_id integer and the route never matches.
@router.get("/search", response_model=List[schemas.NoteResponse])
def search_notes(
    slug: str,
    q: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Full-text search across notes within a specific tenant.

    Uses PostgreSQL's built-in full-text search engine:
    - to_tsvector() converts title + content into stemmed, searchable tokens
    - plainto_tsquery() converts the user's search string into a query
    - @@ is the match operator — does this document match this query?
    - ts_rank() scores relevance — higher score = better match

    The slug in the URL path scopes the search to that tenant only.
    Auth check via get_tenant_or_404 ensures the user is a member.

    Example: GET /api/v1/tenants/my-company/notes/search?q=postgresql+index
    """
    if not q or len(q.strip()) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Search query must be at least 2 characters",
        )

    # Auth + tenant resolution — user must be a member of this tenant
    # get_tenant_or_404 raises 404 if tenant doesn't exist, 403 if not a member
    tenant = auth.get_tenant_or_404(
        db, slug, current_user, required_role=models.UserRole.MEMBER
    )

    # search_vector: combines title + content into one searchable tsvector
    # coalesce() handles NULL — if title is NULL, treats it as empty string
    # 'english' applies English stemming: "indexes" → "index", "running" → "run"
    search_vector = func.to_tsvector(
        "english",
        func.coalesce(models.Note.title, "") + " " + func.coalesce(models.Note.content, "")
    )

    # plainto_tsquery converts plain text to a tsquery
    # "postgresql index performance" → 'postgresql' & 'index' & 'perform'
    # More forgiving than to_tsquery — doesn't require operator syntax from user
    search_query = func.plainto_tsquery("english", q)

    results = (
        db.query(models.Note)
        .filter(
            # Scope to this tenant — tenant isolation
            models.Note.tenant_id == tenant.id,
            # Exclude archived notes from search results
            models.Note.is_archived.is_(False),
            # Full-text match — @@ operator
            search_vector.op("@@")(search_query),
        )
        # ts_rank returns a float score — higher means better match
        # DESC = best matches first
        .order_by(func.ts_rank(search_vector, search_query).desc())
        .limit(20)
        .all()
    )

    return results


@router.get("/{note_id}", response_model=schemas.NoteResponse)
def get_note(
    slug: str,
    note_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    tenant = auth.get_tenant_or_404(
        db,
        slug,
        current_user,
        required_role=models.UserRole.MEMBER,
    )

    note = (
        db.query(models.Note)
        .filter(
            models.Note.id == note_id,
            models.Note.tenant_id == tenant.id,
        )
        .first()
    )
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Note not found"
        )

    return note


@router.put("/{note_id}", response_model=schemas.NoteResponse)
def update_note(
    slug: str,
    note_id: int,
    note_data: schemas.NoteUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    tenant = auth.get_tenant_or_404(
        db, slug, current_user, required_role=models.UserRole.MEMBER
    )

    note = (
        db.query(models.Note)
        .filter(
            models.Note.id == note_id,
            models.Note.tenant_id == tenant.id,
        )
        .first()
    )
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Note not found"
        )

    if note.author_id != current_user.id:
        membership = (
            db.query(models.TenantUser)
            .filter(
                models.TenantUser.tenant_id == tenant.id,
                models.TenantUser.user_id == current_user.id,
            )
            .first()
        )
        role_hierarchy = {
            models.UserRole.OWNER: 3,
            models.UserRole.ADMIN: 2,
            models.UserRole.MEMBER: 1,
        }
        if role_hierarchy[membership.role] < role_hierarchy[models.UserRole.ADMIN]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to update this note",
            )

    for field, value in note_data.model_dump(exclude_unset=True).items():
        setattr(note, field, value)

    db.commit()
    db.refresh(note)

    return note


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    slug: str,
    note_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    tenant = auth.get_tenant_or_404(
        db, slug, current_user, required_role=models.UserRole.MEMBER
    )

    note = (
        db.query(models.Note)
        .filter(
            models.Note.id == note_id,
            models.Note.tenant_id == tenant.id,
        )
        .first()
    )
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Note not found"
        )

    if note.author_id != current_user.id:
        membership = (
            db.query(models.TenantUser)
            .filter(
                models.TenantUser.tenant_id == tenant.id,
                models.TenantUser.user_id == current_user.id,
            )
            .first()
        )
        role_hierarchy = {
            models.UserRole.OWNER: 3,
            models.UserRole.ADMIN: 2,
            models.UserRole.MEMBER: 1,
        }
        if role_hierarchy[membership.role] < role_hierarchy[models.UserRole.ADMIN]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete this note",
            )

    db.delete(note)
    db.commit()