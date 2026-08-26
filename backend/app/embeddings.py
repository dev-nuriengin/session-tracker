"""Phase 8 — LOCAL embeddings (privacy-first: nothing leaves the machine).

fastembed runs a small ONNX model on-device. The model is downloaded once on
first use, then every embedding is computed locally — consistent with the
local-first data rule (session logs never go to an external embedding API).

**Optional since the dependency split.** fastembed brings onnxruntime, numpy,
tokenizers and Pillow — on its own more than every other dependency combined — and it
serves exactly one feature, semantic search. So it lives in the `search` extra, and
this module degrades instead of exploding when it is absent: `embed` returns `None`,
`add_session_log` stores a NULL embedding, and `search_logs` skips those rows, which
it already did for other reasons. Saving your work never depends on an optional
package; only finding it by meaning does.
"""

from __future__ import annotations

from functools import lru_cache

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIM = 384  # bge-small-en-v1.5 output dimension

INSTALL_HINT = (
    "semantic search needs the `search` extra — reinstall with "
    "`uv tool install 'trackden-backend[search]'` (or `[all]`)"
)


@lru_cache(maxsize=1)
def available() -> bool:
    """Is the embedding model installed? Cached — the answer cannot change mid-process.

    An import check rather than a `pip` query: what matters is whether *this*
    interpreter can load it, which is the same question `_model()` will ask.
    """
    try:
        import fastembed  # noqa: F401
    except ImportError:
        return False
    return True


@lru_cache(maxsize=1)
def _model():
    # Lazy import + lazy load — keeps app/CLI startup fast when RAG isn't used.
    from fastembed import TextEmbedding

    return TextEmbedding(MODEL_NAME)


def embed(text: str) -> list[float] | None:
    """Embed a single string → a DIM-length vector, or None when unavailable.

    `None` rather than an exception because the hot caller is `add_session_log`: a user
    without the `search` extra must still be able to save progress. The column is
    nullable and `search_logs` already filters NULL embeddings out, so an un-embedded
    log is a log you cannot find by meaning — not a log you lost.
    """
    if not available():
        return None
    return [float(x) for x in next(_model().embed([text]))]
