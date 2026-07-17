"""Phase 8 — LOCAL embeddings (privacy-first: nothing leaves the machine).

fastembed runs a small ONNX model on-device. The model is downloaded once on
first use, then every embedding is computed locally — consistent with the
local-first data rule (session logs never go to an external embedding API).
"""

from functools import lru_cache

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIM = 384  # bge-small-en-v1.5 output dimension


@lru_cache(maxsize=1)
def _model():
    # Lazy import + lazy load — keeps app/CLI startup fast when RAG isn't used.
    from fastembed import TextEmbedding

    return TextEmbedding(MODEL_NAME)


def embed(text: str) -> list[float]:
    """Embed a single string → a DIM-length vector (computed locally)."""
    return [float(x) for x in next(_model().embed([text]))]
