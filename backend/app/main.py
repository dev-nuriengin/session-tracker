import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import anthropic

load_dotenv()  # reads ../.env → ANTHROPIC_API_KEY

app = FastAPI(title="Session Tracker API")
client = anthropic.Anthropic()  # picks up ANTHROPIC_API_KEY from the environment

# Stub data — later this comes from each project's .ai/_tracker.md
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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"app": "session-tracker", "message": "backend is running"}


class ChatIn(BaseModel):
    message: str


@app.post("/chat")
def chat(body: ChatIn):
    """Stream Claude's reply back token-by-token as Server-Sent Events."""

    def event_stream():
        with client.messages.stream(
            model="claude-opus-4-8",
            max_tokens=1024,
            messages=[{"role": "user", "content": body.message}],
        ) as stream:
            for text in stream.text_stream:
                yield f"data: {text}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---- The agent loop (built by hand, no framework) ----

TOOLS = [
    {
        "name": "list_projects",
        "description": "List all of the user's projects. Call this when the user asks what projects exist or what they are working on.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_tracker",
        "description": "Read the status and next step for a single project. Call this when the user asks 'what's next on <project>?' or wants the status of a specific project. Use list_projects first if you don't know the exact project name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "The project name, e.g. 'korpus' or 'growthhq'.",
                }
            },
            "required": ["project"],
        },
    },
]


def run_tool(name: str, tool_input: dict) -> str:
    """Execute a tool by name and return a string result."""
    if name == "list_projects":
        return ", ".join(PROJECTS)
    if name == "read_tracker":
        project = tool_input.get("project", "").strip().lower()
        if project in TRACKERS:
            return TRACKERS[project]
        return f"No tracker found for '{project}'. Known projects: {', '.join(PROJECTS)}."
    return f"Unknown tool: {name}"


@app.post("/agent")
def agent(body: ChatIn):
    """Manual agentic loop: call Claude → run any tool it asks for → feed the
    result back → repeat until Claude stops asking for tools."""
    messages = [{"role": "user", "content": body.message}]
    tool_calls = []  # so we can SEE which tools fired

    while True:
        resp = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=1024,
            tools=TOOLS,
            messages=messages,
        )

        # Claude is done asking for tools → exit the loop
        if resp.stop_reason != "tool_use":
            break

        # Record Claude's turn (includes the tool_use blocks)
        messages.append({"role": "assistant", "content": resp.content})

        # Run each requested tool, collect the results
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                output = run_tool(block.name, block.input)
                tool_calls.append({"tool": block.name, "result": output})
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": output}
                )

        # Send all results back as one user turn, then loop
        messages.append({"role": "user", "content": results})

    final_text = "".join(b.text for b in resp.content if b.type == "text")
    return {"reply": final_text, "tool_calls": tool_calls}
