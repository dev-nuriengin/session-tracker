"""Phase 9 — LLM-as-judge eval on the graph brain's summaries.

Runs the brain on a project and has Claude score the summary (faithfulness +
conciseness, 1-5). A lightweight quality gate you can talk through in an
interview. Local; uses the same Claude model the app already uses.
"""

from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field

from . import repository
from .graph import run_graph

_judge = init_chat_model("anthropic:claude-opus-4-8")


class Judgement(BaseModel):
    faithfulness: int = Field(description="1-5: does the summary match the source status?")
    conciseness: int = Field(description="1-5: is it appropriately short and clear?")
    reason: str = Field(description="one-line justification")


def evaluate(projects: list[str] | None = None) -> list[dict]:
    """Run the brain + judge for each project; return per-project scores."""
    projects = projects or repository.list_projects()
    results: list[dict] = []
    for slug in projects:
        state = run_graph(slug)
        summary = state.get("summary")
        if summary is None:  # unknown project / routed to list_known
            continue
        verdict = _judge.with_structured_output(Judgement).invoke(
            f"Source status:\n{state['context']}\n\n"
            f"Summary produced:\n{summary.headline}\n\n"
            "Score the summary on faithfulness and conciseness."
        )
        results.append({
            "project": slug,
            "faithfulness": verdict.faithfulness,
            "conciseness": verdict.conciseness,
            "reason": verdict.reason,
        })
    return results


if __name__ == "__main__":
    import json

    print(json.dumps(evaluate(), indent=2))
