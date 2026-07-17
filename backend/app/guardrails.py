"""Phase 9 — PII redaction at BOUNDARIES (never on local storage).

The local store keeps your real, private data intact. Redaction runs only when
text is about to LEAVE the machine — e.g. into an LLM prompt (the graph brain) or
a future cloud export — so PII isn't shipped off-device.
"""

import re

_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"\b\+?\d[\d\s()-]{7,}\d\b"), "[phone]"),
    (re.compile(r"\b(?:sk|pk|ghp|xox[bp])[-_][A-Za-z0-9_-]{10,}\b"), "[secret]"),
]


def redact(text: str) -> str:
    """Replace obvious PII / secrets with placeholders before text leaves local."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
