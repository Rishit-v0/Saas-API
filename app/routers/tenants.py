import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..cache import cache_delete, cache_get, cache_set
from ..database import get_db

router = APIRouter(prefix="/tenants", tags=["Tenants"])

# ── TTL constants — centralised so they're easy to tune ──────────────────────
TENANT_TTL = 300  # 5 minutes — tenant data changes infrequently
MEMBERS_TTL = 120  # 2 minutes — membership changes more often (invites/removes)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _tenant_key(slug: str) -> str:
    """Cache key for a single tenant by slug."""
    return f"tenant:{slug}"


def _members_key(slug: str) -> str:
    """Cache key for a tenant's member list."""
    return f"tenant:{slug}:members"


def _serialize_tenant(tenant: models.Tenant) -> str:
    """
    Serialise a Tenant ORM object to a JSON string for caching.
    We go via the Pydantic schema to ensure only safe, serialisable fields
    are stored — never raw ORM objects which can carry lazy-load traps.
    """
    tenant_data = schemas.TenantResponse.model_validate(tenant).model_dump()
    return json.dumps(tenant_data, default=str)


def _serialize_members(members: List[models.TenantUser]) -> str:
    """
    Serialise a list of TenantUser ORM objects to a JSON string.
    TenantUserResponse includes the nested tenant + user relationships,
    so SQLAlchemy must have loaded them before we call this.
    """
    data = [schemas.TenantUserResponse.model_validate(m).model_dump() for m in members]
    return json.dumps(data, default=str)


# ── CREATE TENANT — no cache read, invalidate nothing (new data) ──────────────
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


# ── LIST MY TENANTS — not cached (user-specific, changes on invite/leave) ─────
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


# ── GET SINGLE TENANT — cached ────────────────────────────────────────────────
@router.get("/{slug}", response_model=schemas.TenantResponse)
async def get_tenant(
    slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    # Always verify membership FIRST — never serve cached data to unauthorised users.
    # The cache stores tenant data, not authorisation decisions.
    # get_tenant_or_404 raises 403/404 if the user isn't a member.
    tenant = auth.get_tenant_or_404(db, slug, current_user, required_role="member")

    cache_key = _tenant_key(slug)
    cached = await cache_get(cache_key)

    if cached:
        # HIT — deserialise and return without touching PostgreSQL
        tenant_data = json.loads(cached)
        return tenant_data

    # MISS — serialise and cache the tenant data for next time
    # Store it and return
    await cache_set(cache_key, _serialize_tenant(tenant), ttl=TENANT_TTL)
    return tenant


# ── INVITE USER — write op, invalidate members cache ─────────────────────────
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

    # Membership changed — members list cache is now stale, delete it.
    # Next GET /members will repopulate from fresh DB data.
    await cache_delete(_members_key(slug))

    return {"detail": f"User {invite_data.email} invited to tenant '{tenant.name}'"}


# ── LIST MEMBERS — cached ─────────────────────────────────────────────────────
@router.get("/{slug}/members", response_model=List[schemas.TenantUserResponse])
async def list_tenant_members(
    slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    # Auth check first — always
    tenant = db.query(models.Tenant).filter(models.Tenant.slug == slug).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
        )

    auth.check_user_permissions(
        user=current_user, tenant_id=tenant.id, required_role="member", db=db
    )

    cache_key = _members_key(slug)
    cached = await cache_get(cache_key)

    if cached:
        return json.loads(cached)

    # Cache miss — query DB with eager loading so relationships are available
    members = (
        db.query(models.TenantUser)
        .filter(models.TenantUser.tenant_id == tenant.id)
        .all()
    )

    await cache_set(cache_key, _serialize_members(members), ttl=MEMBERS_TTL)
    return members


# ── DEV ENDPOINT — check cache status for a tenant ───────────────────────────
# Remove or guard this behind a superuser check before going to production
@router.get("/{slug}/cache-status")
async def get_cache_status(
    slug: str,
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Development helper — shows whether tenant data is currently cached.
    Useful for verifying cache hits/misses during manual testing.
    Remove this or restrict to superusers before deploying to production.
    """
    tenant_cache = await cache_get(_tenant_key(slug))
    members_cache = await cache_get(_members_key(slug))
    return {
        "slug": slug,
        "tenant_cache": "HIT" if tenant_cache else "MISS",
        "members_cache": "HIT" if members_cache else "MISS",
    }
