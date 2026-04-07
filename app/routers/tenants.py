from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..database import get_db

router = APIRouter(prefix="/tenants", tags=["Tenants"])


@router.post(
    "/", response_model=schemas.TenantResponse, status_code=status.HTTP_201_CREATED
)
async def create_tenant(
    tenant_data: schemas.TenantCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    # Check if tenant with the same name already exists
    existing_tenant = (
        db.query(models.Tenant).filter(models.Tenant.slug == tenant_data.slug).first()
    )
    if existing_tenant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Slug '{tenant_data.slug}' is already taken",
        )

    tenant = models.Tenant(name=tenant_data.name, slug=tenant_data.slug)
    db.add(tenant)
    db.flush()  # Flush to get tenant.id for the association

    # Create association with the current user as admin
    membership = models.TenantUser(
        user_id=current_user.id, tenant_id=tenant.id, role=models.UserRole.OWNER
    )

    db.add(membership)
    db.commit()
    db.refresh(tenant)

    return tenant


@router.get("/", response_model=List[schemas.TenantResponse])
async def list_my_tenants(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    tenants = (
        db.query(models.Tenant)
        .join(models.TenantUser, models.TenantUser.tenant_id == models.Tenant.id)
        .filter(
            models.TenantUser.user_id == current_user.id,
            models.Tenant.is_active,
        )
        .all()
    )
    return tenants


@router.get("/{slug}", response_model=schemas.TenantResponse)
async def get_tenant(
    slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
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
        user=current_user,
        tenant_id=tenant.id,
        required_role="member",  # Allow any role to view tenant details
        db=db,
    )
    return tenant


@router.post("/{slug}/invite", status_code=status.HTTP_200_OK)
async def invite_user_to_tenant(
    slug: str,
    invite_data: schemas.InviteUser,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    tenant = (
        db.query(models.Tenant)
        .filter(
            models.Tenant.slug == slug,
        )
        .first()
    )
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
        )

    auth.check_user_permissions(
        user=current_user,
        tenant_id=tenant.id,
        required_role="admin",  # Only admins can invite users
        db=db,
    )

    user_to_invite = (
        db.query(models.User).filter(models.User.email == invite_data.email).first()
    )
    if not user_to_invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User to invite not found"
        )

    existing_membership = (
        db.query(models.TenantUser)
        .filter(
            models.TenantUser.tenant_id == tenant.id,
            models.TenantUser.user_id == user_to_invite.id,
        )
        .first()
    )
    if existing_membership:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member of this tenant",
        )

    membership = models.TenantUser(
        user_id=user_to_invite.id,
        tenant_id=tenant.id,
        role=invite_data.role or models.UserRole.MEMBER,
    )
    db.add(membership)
    db.commit()

    return {"detail": f"User {invite_data.email} invited to tenant '{tenant.name}'"}


@router.get("/{slug}/members", response_model=List[schemas.TenantUserResponse])
async def list_tenant_members(
    slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    tenant = db.query(models.Tenant).filter(models.Tenant.slug == slug).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
        )

    auth.check_user_permissions(
        user=current_user, tenant_id=tenant.id, required_role="member", db=db
    )

    members = (
        db.query(models.TenantUser)
        .filter(models.TenantUser.tenant_id == tenant.id)
        .all()
    )
    return members
