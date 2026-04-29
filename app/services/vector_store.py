import hashlib
import os
import re
from typing import Optional

import chromadb
import numpy as np
import tiktoken
from chromadb.config import Settings
from dotenv import load_dotenv
from openai import OpenAI

# from sqlalchemy import text

load_dotenv()


# ── Client  ────────────────────────────────────────────────────────────────────────────
# openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
# GOOD — only fails when actually called
openai_client = None


def get_openai_client():
    global openai_client
    if openai_client is None:
        openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return openai_client


EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_MAX_TOKENS = 8191  # conservative limit for embedding input size
CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")

# tiktoken encoder — cl100k_base is the tokenizer for text-embedding-3-small
# Initialised once at module level — tokenizer loading is expensive
_encoder = tiktoken.get_encoding("cl100k_base")


# ── ChromaDB client (singleton) ───────────────────────────────────────────────
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


# ── Token utilities ───────────────────────────────────────────────────────────


def count_tokens(text: str) -> int:
    """
    Count tokens in a string using the embedding model's tokenizer.
    Use this before embedding to verify chunks don't exceed EMBEDDING_MAX_TOKENS.
    """
    return len(_encoder.encode(text))


# ── Chunking Strategies ───────────────────────────────────────────────────────
def chunk_by_token(
    text: str,
    chunk_size: int = 256,
    overlap: int = 32,
) -> list[str]:
    """
    Chunk text by token count using tiktoken. More precise for
    embedding limits than character count.
    """
    token_ids = _encoder.encode(text)
    if len(token_ids) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(token_ids):
        end = min(start + chunk_size, len(token_ids))
        chunk_token_ids = token_ids[start:end]

        chunk_text = _encoder.decode(chunk_token_ids)
        if chunk_text.strip():
            chunks.append(chunk_text)
        start = end - overlap  # move forward by chunk_size minus overlap
        if end == len(token_ids):
            break  # reached the end
    return chunks


def chunk_by_recursive_separators(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
    separators: list[str] = None,
) -> list[str]:
    """Recursively split text by separators (e.g. paragraphs, sentences)
    to create chunks that respect natural boundaries.
    Separator hierarchy:
        \\n\\n → paragraphs (best semantic unit)
        \\n   → lines
        . + space → sentences
        space → words (last resort before character split)
    """
    if separators is None:
        separators = ["\\n\\n", "\\n", ". ", " ", ""]
    if len(text) <= chunk_size:
        return [text]

    chosen_seprator = separators[-1]
    remaining_separators = []
    for i, sep in enumerate(separators):
        if sep in text:
            chosen_seprator = sep
            # fmt: off
            remaining_separators = separators[i+1:]
            # fmt: on
            break

    splits = text.split(chosen_seprator) if chosen_seprator else [text]
    chunks = []
    current = ""

    for split in splits:
        candidate = (current + chosen_seprator + split).strip() if current else split

        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current.strip():
                chunks.append(current.strip())

            if len(split) > chunk_size and remaining_separators:
                sub_chunks = chunk_by_recursive_separators(
                    split, chunk_size, overlap, remaining_separators
                )
                chunks.extend(sub_chunks)
                current = ""
            else:
                current = split

    if current.strip():
        chunks.append(current.strip())

    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            tail = (
                overlapped[-1][-overlap:]
                if len(chunks[i - 1]) > overlap
                else chunks[i - 1]
            )
            overlapped.append(tail + " " + chunks[i])
        return [c for c in overlapped if c.strip()]

    return [c for c in chunks if c.strip()]


def chunk_by_character(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> list[str]:
    """Simple character-based chunking with overlap. Fast but may split sentences awkwardly."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - overlap  # move forward by chunk_size minus overlap
        if end >= len(text):
            break  # reached the end
    return chunks


def chunk_by_semantic(
    text: str,
    threshold: float = 0.3,
    min_chunk_char: int = 100,
) -> list[str]:
    """
    Split at semantic boundaries — where sentence topics change.

    Algorithm:
      1. Split text into sentences
      2. Embed all sentences (one batch API call)
      3. Compute cosine similarity between adjacent sentence embeddings
      4. Split where similarity < threshold (topic change detected)
      5. Merge sentences within each segment into a chunk

    threshold=0.3: sentences with cosine similarity < 0.3 are "different topics"
    Tune this value based on your document type:
      - Dense technical docs: lower threshold (0.2) — topics change subtly
      - Narrative text: higher threshold (0.4) — topics change gradually

    Cost: one embedding API call per ingestion (O(sentences) tokens)
    Worth it for: long heterogeneous docs (research papers, books)
    Avoid for: short docs, real-time ingestion, cost-sensitive systems
    """
    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) <= 1:
        return sentences if sentences else [text]

    response = get_openai_client().embeddings.create(input=sentences, model=EMBEDDING_MODEL)
    embeddings = [emb.embedding for emb in response.data]

    split_indices = [0]

    for i in range(len(embeddings) - 1):
        a = np.array(embeddings[i])
        b = np.array(embeddings[i + 1])

        similarity = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
        if similarity < threshold:
            split_indices.append(i + 1)

    split_indices.append(len(sentences))

    chunks = []
    for i in range(len(split_indices) - 1):
        start = split_indices[i]
        end = split_indices[i + 1]
        chunk = " ".join(sentences[start:end])
        if len(chunk) >= min_chunk_char:
            chunks.append(chunk)

    return chunks if chunks else [text]


def chunk_text(
    text: str,
    strategy: str = "token",
    chunk_size: int = None,
    overlap: int = None,
) -> list[str]:
    """
    Main chunking dispatcher — choose strategy based on use case.

    strategy options:
      "token"     → chunk_by_tokens()      DEFAULT — use for all production cases
      "recursive" → chunk_by_recursive_separators()  — good for structured docs
      "semantic"  → chunk_by_semantic()    — best quality, expensive
      "character" → chunk_by_character()   — legacy, avoid

    chunk_size and overlap use strategy-appropriate defaults if not provided.
    """
    if strategy == "token":
        return chunk_by_token(
            text,
            chunk_size=chunk_size or 256,
            overlap=overlap or 32,
        )
    elif strategy == "recursive":
        return chunk_by_recursive_separators(
            text,
            chunk_size=chunk_size or 500,
            overlap=overlap or 50,
        )
    elif strategy == "semantic":
        return chunk_by_semantic(
            text,
            threshold=0.3,
            min_chunk_char=100,
        )
    elif strategy == "character":
        return chunk_by_character(
            text,
            chunk_size=chunk_size or 500,
            overlap=overlap or 50,
        )
    else:
        raise ValueError(
            f"Unknown chunking strategy: {strategy}\nChoose from token/recursive/semantic/character"
        )


# ── Embedding Functions ─────────────────────────────────────────────────────────────


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts using OpenAI's embedding model.
    Always batch — one API call for all texts.
    """
    safe_texts = []
    for text in texts:
        token_count = count_tokens(text)
        if token_count > EMBEDDING_MAX_TOKENS:
            token_ids = _encoder.encode(text)[:EMBEDDING_MAX_TOKENS]
            text = _encoder.decode(token_ids)
        safe_texts.append(text)

    response = get_openai_client().embeddings.create(
        input=safe_texts,
        model=EMBEDDING_MODEL,
    )

    return [data.embedding for data in response.data]


# ── Core Operations ───────────────────────────────────────────────────────────


def ingest_document(
    tenant_slug: str,
    document_id: str,
    text: str,
    metadata: dict = None,
    chunk_strategy: str = "token",
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
    chunks = chunk_text(text, strategy=chunk_strategy)
    if not chunks:
        return {
            "chunks_stored": 0,
            "document_id": document_id,
            "collection": collection.name,
        }
    embeddings = embed_texts(chunks)

    chunk_ids = []
    chunk_metadatas = []

    for i, chunk in enumerate(chunks):
        chunk_id = hashlib.md5(
            f"{document_id}:{i}".encode()
        ).hexdigest()  # stable ID for this chunk
        chunk_ids.append(chunk_id)

        chunk_meta = {
            "document_id": document_id,
            "chunk_index": i,
            "tenant_slug": tenant_slug,
            "chunk_token": count_tokens(chunk),
            "chunk_strategy": chunk_strategy,
            **(metadata or {}),
        }
        chunk_metadatas.append(chunk_meta)

    collection.upsert(
        ids=chunk_ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=chunk_metadatas,
    )

    return {
        "document_id": document_id,
        "chunks_stored": len(chunks),
        "collection": collection.name,
        "chunk_strategy": chunk_strategy,
        "avg_tokens_per_chunk": (
            sum(count_tokens(c) for c in chunks) // len(chunks) if chunks else 0
        ),
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

    query_embedding = embed_texts([query])[0]

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
                    max(0.0, 1 - results["distances"][0][i]), 4
                ),  # convert distance to similarity score
            }
        )

    return formatted


def delete_document(tenant_slug: str, document_id: str) -> None:
    """
    Delete all chunks belonging to a document from the collection.
    Call this when a note is deleted so stale vectors don't pollute search.
    Returns number of chunks deleted.
    """
    collection = get_collection(tenant_slug)
    collection.delete(where={"document_id": document_id})


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
