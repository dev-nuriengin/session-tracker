"""Phase 9 — optional observability. OFF by default (local-first).

Enable by setting LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY (+ optional
LANGFUSE_HOST — point it at a self-hosted instance to keep everything local).
Without those env vars this is a no-op, so no trace data ever leaves the machine
unless you explicitly opt in.
"""

import os


def callbacks() -> list:
    """LangChain callbacks — a Langfuse handler if configured, else empty list."""
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return []
    from langfuse.langchain import CallbackHandler

    return [CallbackHandler()]
