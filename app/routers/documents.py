from typing import List

from fastapi import APIRouter, Depends, HTTPException, status  # BackgroundTasks
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..database import get_db
from ..services.vector_store import (
    delete_document,
    get_collection_stats,
    ingest_document,
)

router = APIRouter(
    prefix="/tenants/{slug}/documents",
    tags=["Documents"],
)


@router.post(
    "/",
    response_model=schemas.DocumentIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_document_endpoint(
    slug: str,
    doc_in: schemas.DocumentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Ingest a document into the tenant's vector store.

    Flow:
    1. Auth check — must be tenant member
    2. Save document metadata to PostgreSQL
    3. Chunk + embed + store in ChromaDB
    4. Update PostgreSQL record with chunk count + is_indexed=True
    5. Return ingestion summary

    Why save to PostgreSQL AND ChromaDB?
    - PostgreSQL: metadata, ownership, audit trail, fast lookup by ID
    - ChromaDB: vectors for semantic search
    - They're complementary — PostgreSQL document ID is used as ChromaDB document_id
      so you can always cross-reference between them
    """
    # 1. Auth
    tenant = auth.get_tenant_or_404(
        db, slug=slug, current_user=current_user, required_role=models.UserRole.MEMBER
    )

    # 2. Save metadata to PostgreSQL
    document = models.Document(
        tenant_id=tenant.id,
        author_id=current_user.id,
        title=doc_in.title,
        content=doc_in.content,
        is_indexed=False,
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    # 3. Ingest into Chromadb

    try:
        result = ingest_document(
            tenant_slug=slug,
            document_id=str(document.id),
            text=doc_in.content,
            metadata={
                "title": doc_in.title,
                "author_id": str(current_user.id),
                "tenant_slug": slug,
                "document_id": str(document.id),
            },
        )

        # 4. Update PostgreSQL record with chunk count + is_indexed=True
        document.chunk_count = result["chunks_stored"]
        document.is_indexed = True
        db.commit()

    except Exception as e:
        # If ChromaDB fails, mark document as not indexed but don't delete
        # It can be re-indexed later
        document.is_indexed = False
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document ingested to DB but failed to index: {str(e)}",
        )
    # 5. Return ingestion summary
    return schemas.DocumentIngestResponse(
        document_id=document.id,
        title=document.title,
        chunks_stored=result["chunks_stored"],
        collection=result["collection"],
        status="indexed",
        chunk_strategy=result["chunk_strategy"],
        avg_tokens_per_chunk=result["avg_tokens_per_chunk"],
    )


@router.get("/", response_model=List[schemas.DocumentResponse])
def list_documents(
    slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """List all documents in this tenant."""
    tenant = auth.get_tenant_or_404(
        db,
        slug=slug,
        current_user=current_user,
        required_role=models.UserRole.MEMBER,
    )
    documents = (
        db.query(models.Document)
        .filter(models.Document.tenant_id == tenant.id)
        .order_by(models.Document.created_at.desc())
        .all()
    )
    return documents


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document_endpoint(
    slug: str,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Delete a document from both PostgreSQL and ChromaDB.
    Must be the author OR an ADMIN/OWNER to delete.
    """
    tenant = auth.get_tenant_or_404(
        db,
        slug=slug,
        user=current_user,
        required_role=models.UserRole.MEMBER,
    )

    document = (
        db.query(models.Document)
        .filter(
            models.Document.id == document_id, models.Document.tenant_id == tenant.id
        )
        .first()
    )

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )

    # Check if current user is author or has elevated role
    if document.author_id != current_user.id:
        membership = (
            db.query(models.TenantUser)
            .filter(
                models.TenantUser.tenant_id == tenant.id,
                models.TenantUser.user_id == current_user.id,
            )
            .first()
        )

        roles_hierarchy = {
            models.UserRole.OWNER: 3,
            models.UserRole.ADMIN: 2,
            models.UserRole.MEMBER: 1,
        }

        if roles_hierarchy[membership.role] < roles_hierarchy[models.UserRole.ADMIN]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete this document",
            )
    # Delete from ChromaDB first
    delete_document(slug, str(document_id))
    db.delete(document)
    db.commit()


@router.get("/stats")
def get_vector_store_stats(
    slug: str,
    current_user: models.User = Depends(auth.get_current_user),
):
    """Dev endpoint — stats about this tenant's vector collection."""
    return get_collection_stats(slug)
