from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..database import get_db

router = APIRouter(
    prefix="/tenants/{slug}/notes",
    tags=["notes"],
)


def get_tenant_and_check_membership(
    db: Session, slug: str, current_user: models.User, required_role: models.UserRole
):
    tenant = (
        db.query(models.Tenant)
        .filter(models.Tenant.slug == slug, models.Tenant.is_active)
        .first()
    )
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
        )

    auth.check_user_permissions(
        user=current_user, tenant_id=tenant.id, db=db, required_role=required_role
    )

    return tenant


@router.post(
    "/", response_model=schemas.NoteResponse, status_code=status.HTTP_201_CREATED
)
def create_note(
    slug: str,
    note_in: schemas.NoteCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    tenant = get_tenant_and_check_membership(
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
    tenant = get_tenant_and_check_membership(
        db, slug, current_user, required_role=models.UserRole.MEMBER
    )

    notes = (
        db.query(models.Note)
        .filter(models.Note.tenant_id == tenant.id, not models.Note.is_archived)
        .order_by(models.Note.created_at.desc())
        .all()
    )
    return notes


@router.get("/{note_id}", response_model=schemas.NoteResponse)
def get_note(
    slug: str,
    note_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    tenant = get_tenant_and_check_membership(
        db,
        slug,
        current_user,
        required_role=[
            models.UserRole.OWNER,
            models.UserRole.ADMIN,
            models.UserRole.MEMBER,
        ],
    )

    note = (
        db.query(models.Note)
        .filter(models.Note.id == note_id, models.Note.tenant_id == tenant.id)
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
    tenant = get_tenant_and_check_membership(
        db, slug, current_user, required_role=models.UserRole.MEMBER
    )

    note = (
        db.query(models.Note)
        .filter(models.Note.id == note_id, models.Note.tenant_id == tenant.id)
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
    tenant = get_tenant_and_check_membership(
        db, slug, current_user, required_role=models.UserRole.MEMBER
    )

    note = (
        db.query(models.Note)
        .filter(models.Note.id == note_id, models.Note.tenant_id == tenant.id)
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
