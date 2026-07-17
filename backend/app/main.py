import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager

from pydantic import BaseModel
import anthropic

from . import repository
from .graph import run_graph

load_dotenv()  # reads ../.env → ANTHROPIC_API_KEY


@asynccontextmanager
async def lifespan(app: FastAPI):
    repository.setup()  # create tables + seed once, on startup
    yield


app = FastAPI(title="Session Tracker API", lifespan=lifespan)
client = anthropic.Anthropic()  # picks up ANTHROPIC_API_KEY from the environment


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
    """Execute a tool by name and return a string result (reads the real DB)."""
    if name == "list_projects":
        return ", ".join(repository.list_projects())
    if name == "read_tracker":
        status = repository.get_status(tool_input.get("project", ""))
        return status or f"No project found. Known: {', '.join(repository.list_projects())}."
    return f"Unknown tool: {name}"


@app.post("/agent")
def agent(body: ChatIn):
    """Manual agentic loop: call Claude → run any tool it asks for → feed the
    result back → repeat until Claude stops asking for tools."""
    messages = [{"role": "user", "content": body.message}]
    tool_calls = []  # so we can SEE which tools fired

    while True:
        resp = client.messages.create(
            # QUESTIONs-Armanc: Why static claude-opus-4-8? Should we make this configurable?
            model="claude-opus-4-8",
            max_tokens=1024, # QUESTIONs-Armanc: Why static max_tokens? Should we make this configurable?
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


# ---- Phase 2: the LangGraph session pipeline (load → summarize → plan → approve) ----


class GraphIn(BaseModel):
    project: str
    thread_id: str | None = None  # names the session for checkpointing/resume


@app.post("/graph")
def graph(body: GraphIn):
    """Run the LangGraph pipeline for a project and return the final state
    (context, summary, plan, approved). Framework version of /agent."""
    return run_graph(body.project, body.thread_id)


# ---- Core read endpoints (projects live in the DB) ----


@app.get("/projects")
def projects():
    """List all projects (from the core DB)."""
    return {"projects": repository.list_projects()}


@app.get("/projects/{slug}")
def project_detail(slug: str):
    """Compact overview (summary-first). Drill into /history for the full payload."""
    ov = repository.overview(slug)
    if not ov:
        return {"error": f"unknown project '{slug}'"}
    return ov


@app.get("/projects/{slug}/history")
def project_history(slug: str):
    """Deeper drill-down: open items + full memory + recent session logs."""
    h = repository.get_history(slug)
    if not h:
        return {"error": f"unknown project '{slug}'"}
    return h
