import hashlib
import os
from typing import Optional

import chromadb
from chromadb.config import Settings
from dotenv import load_dotenv
from openai import OpenAI

# from sqlalchemy import text

load_dotenv()


openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

EMBEDDING_MODEL = "text-embedding-3-small"
CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")

_chroma_client: Optional[chromadb.PersistentClient] = None


def get_chroma_client() -> chromadb.PersistentClient:
    """Singleton ChromaDB client — created once, reused."""
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(
            path=CHROMA_PATH,
            settings=Settings(
                anonymized_telemetry=False,
            ),
        )
    return _chroma_client


def get_collection(tenant_slug: str) -> chromadb.Collection:
    """
    Get or create a ChromaDB collection for a specific tenant.
    """
    client = get_chroma_client()
    collection_name = f"tenant_{tenant_slug.replace('-', '_')}"
    return client.get_or_create_collection(
        name=collection_name, metadata={"tenant_slug": tenant_slug}
    )


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    Split text into overlapping chunks for embedding.

    chunk_size: target characters per chunk (not tokens — simpler for now)
    overlap: characters shared between adjacent chunks
            prevents losing context at chunk boundaries

    Why overlap? If a key sentence spans the boundary between two chunks,
    overlap ensures both chunks contain part of it.

    Production improvement: use tiktoken to chunk by token count instead
    of character count — more precise for embedding model limits.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start = chunk_size - overlap  # move forward by chunk_size minus overlap
    return chunks


def embed_text(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts using OpenAI's embedding model.
    Always batch — one API call for all texts.
    """
    response = openai_client.embeddings.create(input=texts, model=EMBEDDING_MODEL)
    return [embedding.embedding for embedding in response.data]


def ingest_document(
    tenant_slug: str, document_id: str, text: str, metadata: dict = None
) -> dict:
    """
    Chunk, embed, and store a document in the tenant's vector collection.

    Returns summary of what was stored.

    document_id: stable identifier for this document (e.g. note ID, filename)
    used for deduplication and deletion
    metadata: arbitrary dict stored alongside each chunk — searchable later
    e.g. {"source": "note", "note_id": 42, "title": "My Note"}
    """
    collection = get_collection(tenant_slug)
    chunks = chunk_text(text)
    if not chunks:
        return {
            "chunks_stored": 0,
            "document_id": document_id,
        }
    embeddings = embed_text(chunks)

    chunk_ids = []
    chunk_metadatas = []

    for i, chunk in enumerate(chunks):
        chunk_id = hashlib.md5(
            f"{document_id}_{i}".encode()
        ).hexdigest()  # stable ID for this chunk
        chunk_ids.append(chunk_id)

        chunk_meta = {
            "document_id": document_id,
            "chunk_index": i,
            "tenant_slug": tenant_slug,
            **(metadata or {}),
        }
        chunk_metadatas.append(chunk_meta)

    collection.add(
        ids=chunk_ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=chunk_metadatas,
    )

    return {
        "document_id": document_id,
        "chunks_stored": len(chunks),
        "collection": collection.name,
    }


def query_documents(
    tenant_slug: str,
    query: str,
    top_k: int = 5,
    where: dict = None,
) -> list[dict]:
    """
    Semantic search within a tenant's vector collection.

    Embeds the query, finds top_k most similar chunks by cosine similarity.
    Returns list of results with text, score, and metadata.

    where: optional ChromaDB metadata filter
           e.g. {"note_id": 42} to restrict search to one document
    """
    collection = get_collection(tenant_slug)
    if not collection.count():
        return []  # no data to search

    query_embedding = embed_text([query])[0]

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(
            top_k, collection.count()
        ),  # can't return more results than we have
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    formatted = []
    for i, doc in enumerate(results["documents"][0]):
        formatted.append(
            {
                "text": doc,
                "metadata": results["metadatas"][0][i],
                "score": round(
                    1 - results["distances"][0][i], 4
                ),  # convert distance to similarity score
            }
        )

    return formatted


def delete_document(tenant_slug: str, document_id: str) -> int:
    """
    Delete all chunks belonging to a document from the collection.
    Call this when a note is deleted so stale vectors don't pollute search.
    Returns number of chunks deleted.
    """
    collection = get_collection(tenant_slug)
    collection.delete(where={"document_id": document_id})
    return 0


def get_collection_stats(tenant_slug: str) -> dict:
    """
    Get stats about a tenant's vector collection.
    Useful for monitoring and debugging.
    """
    collection = get_collection(tenant_slug)
    return {
        "collection_name": collection.name,
        "tenant_slug": tenant_slug,
        "total_chunks": collection.count(),
    }
