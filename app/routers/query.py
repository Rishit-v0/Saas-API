"""
Query router — semantic search endpoint for RAG retrieval.
This is the retrieval layer of the RAG pipeline:
  User question → embed → ChromaDB similarity search → ranked chunks
"""

from fastapi import APIRouter, Depends  # HTTPException, status
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..database import get_db
from ..services.vector_store import query_documents, rerank_chunks

RAG_MODEL = "gpt-5-nano"

RAG_SYSTEM_PROMPT = """
You are a helpful assistant that answers questions based strictly on the provided context documents.

STRICT RULES:
- Answer ONLY using information present in the context below
- If the context does not contain sufficient information, respond with exactly:
  "I don't have enough information to answer this question."
- Do NOT use knowledge from your training data
- Do NOT fabricate facts or details not in the context
- Reference sources using their label e.g. [Source 1] when relevant
- Be concise and accurate

Context:
{context}
"""


def _build_rag_chain():
    llm = ChatOpenAI(
        model=RAG_MODEL,
        temperature=0.0,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", RAG_SYSTEM_PROMPT),
            ("human", "{question}"),
        ]
    )

    return prompt | llm | StrOutputParser()


def _format_context(chunks: list[dict]) -> str:
    if not chunks:
        return "No relevant context found."
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        title = chunk.get("metadata", {}).get("title", "Document")
        parts.append(f"[Source {i} - {title}]:\n{chunk['text']}")

    return "\n\n".join(parts)


router = APIRouter(
    prefix="/tenants/{slug}/query",
    tags=["Query"],
)


@router.post("/", response_model=schemas.QueryResponse)
async def query_tenant_documents(
    slug: str,
    query_in: schemas.QueryRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Semantic search across all documents in a tenant's vector store.

    How it works:
    1. Auth check — user must be tenant member
    2. Embed the question using text-embedding-3-small
    3. ChromaDB cosine similarity search — find top_k most relevant chunks
    4. Return ranked results with scores

    Score interpretation:
    - 1.0 = perfect match (identical text)
    - 0.7+ = highly relevant
    - 0.5-0.7 = somewhat relevant
    - < 0.5 = likely not relevant
    """

    # 1. Auth check tenant =
    auth.get_tenant_or_404(
        db,
        slug=slug,
        current_user=current_user,
        required_role=models.UserRole.MEMBER,
    )

    # 2 + 3 - Embed and query vector store(search ChromaDB)
    raw_results = query_documents(
        tenant_slug=slug,
        query=query_in.question,
        top_k=query_in.top_k,
    )

    if not raw_results:
        return schemas.QueryResponse(
            question=query_in.question,
            tenant_slug=slug,
            chunks_retrieved=0,
            results=[],
        )

    # 4. Format results
    formatted_results = []
    for chunk in raw_results:
        meta = chunk.get("metadata", {})
        formatted_results.append(
            schemas.RetrivedChunk(
                text=chunk["text"],
                score=chunk["score"],
                document_id=meta.get("document_id", ""),
                chunk_index=int(meta.get("chunk_index", 0)),
                title=meta.get("title", ""),
                metadata=meta,
            )
        )

    return schemas.QueryResponse(
        question=query_in.question,
        tenant_slug=slug,
        chunks_retrieved=len(formatted_results),
        results=formatted_results,
    )


@router.post("/explain", response_model=dict)
async def explain_query(
    slug: str,
    query_in: schemas.QueryRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Returns raw scores and metadata without formatting.
    Useful for tuning top_k and understanding retrieval quality.
    Remove or restrict before production deployment.
    """

    # tenant =
    auth.get_tenant_or_404(
        db,
        slug=slug,
        current_user=current_user,
        required_role=models.UserRole.MEMBER,
    )

    # Embed and query vector store (search ChromaDB)
    raw_results = query_documents(
        tenant_slug=slug,
        query=query_in.question,
        top_k=query_in.top_k,
    )

    return {
        "question": query_in.question,
        "top_k_requested": query_in.top_k,
        "results_returned": len(raw_results),
        "raw_results": raw_results,
        "score_distribution": {
            "max": max((r["score"] for r in raw_results), default=0),
            "min": min((r["score"] for r in raw_results), default=0),
            "avg": (
                round(sum(r["score"] for r in raw_results) / len(raw_results), 4)
                if raw_results
                else 0
            ),
        },
    }


@router.post("/answer", response_model=schemas.AnswerResponse)
async def answer_question(
    slug: str,
    query_in: schemas.QueryRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    # 1. Auth check
    auth.get_tenant_or_404(
        db,
        slug=slug,
        current_user=current_user,
        required_role=models.UserRole.MEMBER,
    )

    # 2. Retrieve relevant chunks
    candidate_count = max(query_in.top_k * 4, 20)
    raw_chunks = query_documents(
        tenant_slug=slug,
        query=query_in.question,
        top_k=candidate_count,
    )

    if not raw_chunks:
        return schemas.AnswerResponse(
            question=query_in.question,
            answer="I don't have enough information to answer this question.",
            sources=[],
            chunks_used=0,
            model=RAG_MODEL,
            tenant_slug=slug,
        )

    reranked_chunks = rerank_chunks(
        query=query_in.question,
        chunks=raw_chunks,
        top_n=query_in.top_k,
    )

    context = _format_context(reranked_chunks)

    chain = _build_rag_chain()
    answer_text = chain.invoke({"context": context, "question": query_in.question})

    sources = []
    for chunk in reranked_chunks:
        meta = chunk.get("metadata", {})
        sources.append(
            schemas.SourceCitation(
                document_title=meta.get("title", "Document"),
                chunk_preview=chunk["text"][:100]
                + ("..." if len(chunk["text"]) > 100 else ""),
                relevance_score=chunk.get("reranked_score", chunk.get("score", 0)),
                document_id=meta.get("document_id", ""),
                chunk_index=int(meta.get("chunk_index", 0)),
            )
        )

    return schemas.AnswerResponse(
        question=query_in.question,
        answer=answer_text,
        sources=sources,
        chunks_used=len(reranked_chunks),
        model=RAG_MODEL,
        tenant_slug=slug,
    )
