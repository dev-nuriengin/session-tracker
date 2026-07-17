# QUESTIONs-Armanc: Why inline data? Shoul not come from a db?
"""Shared stub data — later this comes from each project's .ai/_tracker.md.

Lives in its own module so both the Phase 1 loop (main.py) and the Phase 2
graph (graph.py) can import it without a circular import.
"""

PROJECTS = ["korpus", "visionbank", "hinbunakurdi", "growthhq", "integral", "resho-hub"]

# Stub per-project status — real file/RAG reads land in Phase 5
TRACKERS = {
    "korpus": "Phase 2/5. NEXT: wire pgvector retrieval into the FastAPI search endpoint.",
    "visionbank": "Kickoff. NEXT: scaffold the repo + pick the stack.",
    "hinbunakurdi": "Live SaaS. NEXT: add spaced-repetition scheduling to the lesson flow.",
    "growthhq": "Ongoing. NEXT: finish SumUp interview prep in the Companies tab.",
    "integral": "Work project. NEXT: (private).",
    "resho-hub": "Ship-fast. NEXT: deploy the MVP and gather first feedback.",
}
