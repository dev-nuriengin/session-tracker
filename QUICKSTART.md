# Quickstart — your first 5 minutes

Get Trackden running locally and give your AI agent memory. Everything stays on
your machine — **no account, no cloud, no API key needed for the core.**

> **Who this is for:** anyone who uses an AI coding agent (Claude Code, Codex, …) and wants
> it to remember project history across sessions. Full design lives in [`README.md`](./README.md).

## Prerequisites (1 min)

- **Docker** (runs Postgres + the API) — [install](https://docs.docker.com/get-docker/)
- **[uv](https://docs.astral.sh/uv/)** (Python runner for the CLI + MCP server)
- *(optional, for the web view)* **Node.js 18+**
- An AI agent that speaks **MCP** (e.g. Claude Code) — this is where the value comes from

## 1 · Start the core (1 min)

```bash
git clone https://github.com/dev-nuriengin/session-tracker
cd session-tracker
docker compose up --build          # Postgres+pgvector + API on :8000
```

First boot creates the vector extension, tables, and a small seed automatically.
**No `.env` or API key required** — the core makes zero LLM calls.

> ✅ Check it's alive: open http://localhost:8000/projects — you should see JSON.

## 2 · Add your first project (1 min)

Use the CLI (`trackden`) to build your map — **Project → folders → items**.
The CLI lives in `backend/`, so run it from there (it talks to the DB started in step 1,
default `localhost:5433` — no config needed):

```bash
cd backend
uv run trackden add-project my-first-project
uv run trackden add-item my-first-project "Set up the repo"
uv run trackden list                   # see it in the tracker
```

That's your structure. An "item" is domain-agnostic — a *ticket*, a *bill*, a *deliverable*;
it's just a unit of work.

## 3 · Connect your agent — the heart (2 min)

This is the point of the product: your agent plugs into the tracker over **MCP** and gets
continuity with **no per-agent setup**.

**Claude Code** — the repo ships a ready `.mcp.json`:

```json
{
  "mcpServers": {
    "trackden": {
      "command": "uv",
      "args": ["--directory", "backend", "run", "python", "-m", "app.mcp_server"]
    }
  }
}
```

Open Claude Code in the repo, **approve the `trackden` server** when prompted (or
restart so it loads). Your agent now has these tools:

| Tool | What it does |
|---|---|
| `list_projects` | cheap overview of everything you track |
| `get_history` | pull an item's history **first** — never start blind |
| `whats_next` | suggested next steps |
| `save_progress` | capture what was done, behind the scenes |
| `add_memory` | store a decision / repo link / note |
| `search` | semantic search across all session logs |

> 💡 Try it: ask your agent *"what's the history of my-first-project?"* — it calls
> `get_history` and answers from the tracker, not from guesswork.

## 4 · See your status (optional)

- **CLI:** from `backend/` → `uv run trackden show my-first-project` · `uv run trackden ask "what did I do last?"`
- **Web view:** run `cd frontend && npm run dev` → http://localhost:3000

## You're done 🎉

From now on, as you work with your agent it **reads history first** and **saves progress
behind the scenes** — across sessions, across agents. Your data never leaves your machine.

### Where to go next
- **The optional brain** (on-demand summaries, `trackden eval`) calls Claude — copy
  `.env.example` → `.env` and set `ANTHROPIC_API_KEY` only if you want it. Everything else runs keyless.
- **Full architecture & privacy model:** [`README.md`](./README.md)
- **Working in the repo as an agent/contributor:** [`AGENTS.md`](./AGENTS.md)
