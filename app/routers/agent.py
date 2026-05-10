import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.messages import AIMessage, ToolMessage  # HumanMessage

# from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..database import get_db
from ..services.vector_store import query_documents

router = APIRouter(
    prefix="/tenants/{slug}/agent",
    tags=["Agent"],
)

AGENT_MODEL = "gpt-5-nano"


# - Define tools for the agent-----------------------------------------------
def create_tenant_tools(tenant_slug: str, db: Session):
    """
    Create tools scoped to a specific tenant.
    Each tool has the tenant_slug baked in — agent can't access other tenants.
    """

    @tool
    def search_tenant_documents(query: str) -> str:
        """
        Search this tenant's documents for relevant information.
        Use for questions about documentation, guides, or knowledge base content.
        Returns top 5 most relevant passages ranked by semantic similarity.
        """
        try:
            results = query_documents(
                tenant_slug=tenant_slug,
                query=query,
                top_k=5,
            )
            if not results:
                return f"No relevant documents found for query: '{query}'"

            parts = []
            for i, r in enumerate(results, 1):
                title = r.get("metadata", {}).get("title", "Untitled")
                score = r.get("score", 0)
                parts.append(
                    f"[Source {i} - {title} (score: {score:.2f})]\n{r['text']}"
                )
            return "\n\n".join(parts)
        except Exception as e:
            return f"Error during document search: {str(e)}"

    @tool
    def get_tenant_stats() -> str:
        """
        Get statistics about this tenant's data — note count, document count,
        member count, and recent activity.
        Use when asked about data volume, usage, or system statistics.
        """
        try:
            note_count = (
                db.query(models.Note)
                .join(models.Tenant, models.Tenant.slug == tenant_slug)
                .filter(models.Note.tenant_id == models.Tenant.id)
                .count()
            )

            document_count = (
                db.query(models.Document)
                .join(models.Tenant, models.Tenant.slug == tenant_slug)
                .filter(models.Document.tenant_id == models.Tenant.id)
                .count()
            )

            member_count = (
                db.query(models.TenantUser)
                .join(models.Tenant, models.Tenant.slug == tenant_slug)
                .filter(models.TenantUser.tenant_id == models.Tenant.id)
                .count()
            )

            return (
                f"Tenant '{tenant_slug}' statistics:\n"
                f"  Notes: {note_count}\n"
                f"  Documents: {document_count}\n"
                f"  Members: {member_count}\n"
            )
        except Exception as e:
            return f"Error retrieving tenant stats: {str(e)}"

    @tool
    def list_recent_notes(limit: int = 5) -> str:
        """
        List the most recently created notes in this tenant.
        Use when asked about recent activity or what notes exist.
        limit: number of notes to return (max 10)
        """
        try:
            limit = min(limit, 10)
            tenant = (
                db.query(models.Tenant)
                .filter(models.Tenant.slug == tenant_slug)
                .first()
            )

            if not tenant:
                return f"Tenant with slug '{tenant_slug}' not found."

            notes = (
                db.query(models.Note)
                .filter(
                    models.Note.tenant_id == tenant.id,
                    models.Note.is_archived.is_(False),
                )
                .order_by(models.Note.created_at.desc())
                .limit(limit)
                .all()
            )

            if not notes:
                return f"No notes found for tenant '{tenant_slug}'."

            parts = []
            for note in notes:
                parts.append(
                    f"- [{note.id}] {note.title} "
                    f"(created: {note.created_at.strftime('%Y-%m-%d')})"
                )
            return (
                f"Recent {len(notes)} notes for tenant '{tenant_slug}':\n"
                + "\n".join(parts)
            )
        except Exception as e:
            return f"Error listing recent notes: {str(e)}"

    return [search_tenant_documents, get_tenant_stats, list_recent_notes]


checkpointer = InMemorySaver()


def build_agent_executor(tenant_slug: str, db: Session):
    """
    Build an agent executor for a specific tenant.
    The agent will have access to tools that are scoped to this tenant.
    """
    llm = ChatOpenAI(model=AGENT_MODEL, temperature=0)
    tools = create_tenant_tools(tenant_slug, db)

    system_prompt = f"""You are an intelligent assistant for tenant '{tenant_slug}'.
You help users find information and understand their data.

You have access to:
- search_tenant_documents: semantic search over this tenant's documents
- get_tenant_stats: database statistics for this tenant
- list_recent_notes: recent notes in this tenant

Rules:
- Only access data for tenant '{tenant_slug}' — never other tenants
- Use tools when you need current data, not for general knowledge questions
- Be concise — answer the question directly after gathering data
- If tools return no results, say so honestly"""
    return create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
        middleware=[
            ToolCallLimitMiddleware(run_limit=5, exit_behavior="continue"),
        ],
    )


def extract_tools_used(messages: list) -> list[str]:
    """
    Extract a list of tool names used from the agent's message history.
    """
    return [msg.name for msg in messages if isinstance(msg, ToolMessage)]


# ── Non-Streaming Endpoint ────────────────────────────────────────────────────
@router.post("/", response_model=schemas.AgentResponse)
async def run_agent(
    slug: str,
    request: schemas.AgentRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    auth.get_tenant_or_404(db, slug, current_user, required_role=models.UserRole.MEMBER)
    agent_executor = build_agent_executor(slug, db)

    config = {"configurable": {"thread_id": f"{slug}_{current_user.id}"}}
    result = agent_executor.invoke(
        {"messages": [{"role": "user", "content": request.message}]}, config=config
    )

    all_messages = result.get("messages", [])

    last_message = all_messages[-1] if all_messages else None
    answer = (
        last_message.content
        if isinstance(last_message, AIMessage)
        else "No answer generated."
    )

    tools_used = extract_tools_used(result["messages"])

    return schemas.AgentResponse(
        message=request.message,
        answer=answer,
        tools_used=tools_used,
        iterations=len(tools_used),
        tenant_slug=slug,
    )


# ── Streaming Endpoint ───────────────────────────────────────────────────────
@router.post("/stream")
async def run_agent_streaming(
    slug: str,
    request: schemas.AgentRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Run agent with Server-Sent Events streaming.

    Returns a stream of events:
      data: {"type": "token", "content": "Hello"}
      data: {"type": "tool_start", "tool": "search_tenant_documents"}
      data: {"type": "tool_end", "tool": "search_tenant_documents", "result": "..."}
      data: {"type": "done", "tools_used": [...], "iterations": 3}

    stream_mode="messages" yields individual message chunks as they arrive,
    enabling token-by-token streaming of the final answer.
    """
    auth.get_tenant_or_404(db, slug, current_user, required_role=models.UserRole.MEMBER)
    agent = build_agent_executor(slug, db)
    config = {"configurable": {"thread_id": f"{slug}_{current_user.id}"}}

    async def event_generator() -> AsyncGenerator[str, None]:
        tools_used: list[str] = []
        # stream_mode="messages" yields (message_chunk, metadata) tuples
        # AIMessage chunks = LLM tokens streaming in real time
        # ToolMessage chunks = tool call results

        try:
            async for chunk, metadata in agent.astream(
                {"messages": [("user", request.message)]},
                config=config,
                stream_mode="messages",
            ):
                # LLM token streaming -> send each chunk immediately
                if isinstance(chunk, AIMessage) and chunk.content:
                    payload = json.dumps(
                        {
                            "type": "token",
                            "content": chunk.content,
                        }
                    )
                    yield f"data: {payload}\n\n"
                # Tool call result -> tool has finished executing
                elif isinstance(chunk, ToolMessage):
                    tool_name = getattr(chunk, "name", "unknown_tool")
                    if tool_name not in tools_used:
                        tools_used.append(tool_name)

                    payload = json.dumps(
                        {
                            "type": "tool_end",
                            "tool": tool_name,
                            "result_preview": (chunk.content or "")[:150],
                        }
                    )
                    yield f"data: {payload}\n\n"

            # Final done event -> signals client the stream is complete
            yield f"data: {json.dumps({
                'type': 'done',
                'tools_used': tools_used,
                'iterations': len(tools_used),
            })}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
