import operator
from typing import Annotated, TypedDict

# import langchain_core
# import langchain_core.messages
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

AGENT_MODEL = "gpt-5-nano"


# ── State Schema ──────────────────────────────────────────────────────────────
class SaaSAgentState(TypedDict):
    """
    State shared across all nodes in the agent graph.

    messages: full conversation — new messages APPENDED via operator.add
    tool_call_count: how many tool calls in this turn (for limit enforcement)
    max_tool_calls: safety limit per turn
    tenant_slug: which tenant this agent is serving (for audit/logging)
    """

    messages: Annotated[list[BaseMessage], operator.add]
    tool_call_count: int
    max_tool_calls: int
    tenant_slug: str


# ── Agent Graph Builder ───────────────────────────────────────────────────
def build_saas_agent_graph(
    tools: list[BaseTool],
    system_prompt: str,
    max_tool_calls: int = 5,
    checkpointer: MemorySaver = None,
):
    """
    Build an explicit LangGraph agent graph.

    Nodes:
      model_node  — call LLM, get response or tool call request
      tools_node  — execute requested tool calls

    Edges:
      START → model_node
      model_node → [conditional] → tools_node (if tool calls)
                                 → END (if final answer or limit hit)
      tools_node → model_node (always loop back)
    """

    llm = ChatOpenAI(model=AGENT_MODEL, temperature=0)
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    # ---- Nodes ----
    def model_node(state: SaaSAgentState) -> dict:
        """
        Call the LLM with current message history.
        Prepend system prompt as first message if not already there.
        """
        from langchain_core.messages import SystemMessage

        messages = state["messages"]

        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=system_prompt)] + list(messages)

        response = llm_with_tools.invoke(messages)

        return {"messages": [response]}

    def tools_node(state: SaaSAgentState) -> dict:
        """
        Execute all tool calls from the last AI message.
        Increments tool_call_count for limit tracking.
        """
        last_message = state["messages"][-1]
        tool_results = []
        calls_made = 0

        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]

            if tool_name in tool_map:
                try:
                    result = tool_map[tool_name].invoke(tool_args)
                except Exception as e:
                    result = f"Tool error: {str(e)}"
            else:
                result = f"Unknown tool: {tool_name}"

            tool_results.append(
                ToolMessage(
                    content=str(result),
                    tool_call_id=tool_call["id"],
                    name=tool_name,
                )
            )

            calls_made += 1
        return {
            "messages": tool_results,
            "tool_call_count": state["tool_call_count"] + calls_made,
        }

    # ---- Routing Logic ----
    def should_continue(state: SaaSAgentState) -> str:
        last_message = state["messages"][-1]

        if state["tool_call_count"] >= state["max_tool_calls"]:
            return "end"

        if isinstance(last_message, AIMessage):
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                return "tools"

        return "end"

    # ---- Graph Construction ----
    graph = StateGraph(SaaSAgentState)
    graph.add_node("model", model_node)
    graph.add_node("tools", tools_node)
    graph.set_entry_point("model")
    graph.add_conditional_edges(
        "model",
        should_continue,
        {
            "tools": "tools",
            "end": END,
        },
    )
    graph.add_edge("tools", "model")
    return graph.compile(checkpointer=checkpointer)
