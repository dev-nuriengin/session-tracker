"""LangChain tools — the Phase 1 tools, wrapped with @tool so the LangGraph
pipeline (graph.py) can call them as graph steps instead of inlining TRACKERS.

The @tool decorator turns a plain function into a LangChain tool: its
docstring becomes the description and its signature becomes the input schema.
Call one with `.invoke({...})`. main.py's /agent still uses its own raw-SDK
tool dicts — these are the LangChain-native versions for the graph.
"""

from langchain_core.tools import tool

from .data import PROJECTS, TRACKERS


@tool
def list_projects() -> str:
    """List all of the user's projects."""
    return ", ".join(PROJECTS)


@tool
def read_tracker(project: str) -> str:
    """Read the status and next step for one project. Returns '' if unknown."""
    return TRACKERS.get(project.strip().lower(), "")
