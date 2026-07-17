"""LangChain tools — thin wrappers so the LangGraph pipeline can call the core.

These now read from the **real DB** via the repository (the stub `data.py` is only
a seed source). main.py's /agent uses its own raw-SDK tool dicts — these are the
LangChain-native versions for the graph.
"""

from langchain_core.tools import tool

from . import repository


@tool
def list_projects() -> str:
    """List all of the user's projects."""
    return ", ".join(repository.list_projects())


@tool
def read_tracker(project: str) -> str:
    """Read the status and next step for one project. Returns '' if unknown."""
    return repository.get_status(project)
