"""Phase 2 — the session pipeline as a LangGraph state graph.

Flow:  load → summarize → plan → approve

Each step is a *node*. LangGraph runs them in order and threads one shared
`state` dict through: a node reads some keys and returns the keys it writes.
This is the framework version of the hand-built while-loop in main.py's
/agent — there *we* owned the control flow; here LangGraph owns it and we
just declare the nodes and edges.

Provider swap lives in ONE line below (`init_chat_model`). Change
"anthropic:claude-opus-4-8" to "openai:gpt-5" or "xai:grok-4" and the whole
graph keeps working — nodes and edges don't change.
"""

from typing import TypedDict

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph, START, END

from .data import PROJECTS, TRACKERS

load_dotenv()  # ANTHROPIC_API_KEY — must be set before the model is created

# The one provider line. Swap the string to change providers.
llm = init_chat_model("anthropic:claude-opus-4-8")


class SessionState(TypedDict):
    """State threaded through every node. Each node reads some keys, writes others."""

    project: str    # input
    context: str    # load      → the tracker text for this project
    summary: str    # summarize → 2-sentence status
    plan: str       # plan      → next steps
    approved: bool  # approve   → human-in-the-loop gate (stubbed for now)


def load(state: SessionState) -> dict:
    """Load the session context for the project (reuses the Phase 1 tracker stub)."""
    project = state["project"].strip().lower()
    context = TRACKERS.get(
        project, f"No tracker found for '{project}'. Known: {', '.join(PROJECTS)}."
    )
    return {"context": context}


def summarize(state: SessionState) -> dict:
    """Ask Claude for a short status summary of where the project stands."""
    prompt = (
        f"Project '{state['project']}' status:\n{state['context']}\n\n"
        "Write a 2-sentence summary of where this project stands."
    )
    return {"summary": llm.invoke(prompt).content}


def plan(state: SessionState) -> dict:
    """Ask Claude to propose next steps, given the context + summary."""
    prompt = (
        f"Project '{state['project']}'.\n"
        f"Status: {state['context']}\n"
        f"Summary: {state['summary']}\n\n"
        "Propose the 3 most important next steps as a short numbered list."
    )
    return {"plan": llm.invoke(prompt).content}


def approve(state: SessionState) -> dict:
    """Human-in-the-loop gate. Auto-approves for now; the real pause lands in Phase 3."""
    return {"approved": True}


def build_graph():
    """Wire the nodes into a linear graph: load → summarize → plan → approve."""
    g = StateGraph(SessionState)
    g.add_node("load", load)
    g.add_node("summarize", summarize)
    g.add_node("plan", plan)
    g.add_node("approve", approve)

    g.add_edge(START, "load")
    g.add_edge("load", "summarize")
    g.add_edge("summarize", "plan")
    g.add_edge("plan", "approve")
    g.add_edge("approve", END)
    return g.compile()


# Compile once at import; reuse across requests.
session_graph = build_graph()


def run_graph(project: str) -> dict:
    """Run the full pipeline for a project and return the final state."""
    return session_graph.invoke({"project": project})
