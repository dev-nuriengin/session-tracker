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

## 2 · Onboard your first project (1 min)

One command brings a project in: it scans the repo you point it at, offers to import
any checklist it finds, and scaffolds the rest. **Your repo is never modified.** The CLI
lives in `backend/`, so run it from there (it talks to the DB started in step 1, default
`localhost:5433` — no config needed):

```bash
cd backend
uv run trackden onboard                 # interactive wizard
```

Already have a `_tracker.md`, `CLAUDE.md`, or `AGENTS.md`? It finds them and asks before
importing anything — blank/`y` imports the whole file, `n` skips it, `edit` lets you pick
items by number:

```
Found 3 items in _tracker.md
    1. [done] Scaffold the repo
    2. [todo] Wire the API
    3. [todo] Ship it
Import? (y / n / edit) [y]:
```

Nothing imports until you say yes — decline (or have nothing to import yet) and the same
gate is offered again next run. Once a project holds items it's never re-imported, so
re-running `onboard` can't create duplicates; new items from then on come from
`trackden add-item` or an MCP tool. `--no-import` skips the scan entirely (no guidance is
seeded from the repo either).

Guidance lands centrally in `~/.trackden/projects/<slug>/` (`_way-of-work.md`, `_arch.md`,
`_decisions.md`, plus a **generated** `_tracker.md` mirror — don't hand-edit it), and
`~/.trackden` is a git repo of its own, so one push backs up every project's guidance.

Prefer to build the map by hand? The primitives are still there:

```bash
uv run trackden add-project my-first-project
uv run trackden add-item my-first-project "Set up the repo"
uv run trackden list
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
| `overview` | call this FIRST for a project — compact summary, not a full dump |
| `get_history` | pull a project's history **first when resuming** — never start blind. Pass `item_id` to narrow the whole payload (open items, memory, logs) to one item instead of the project |
| `list_items` | drill-down: a project's items (open only unless asked for done too) |
| `set_status` | move an item to a new status — `doing`, `waiting`, `done`, or a project's own |
| `list_statuses` | the status names this project accepts, each with the class it behaves as |
| `list_memory` | drill-down: a project's durable memory (links, notes, transcripts, files) |
| `get_guidance` | read the project's rules / architecture / decisions — one doc per call |
| `whats_next` | suggested next steps |
| `save_progress` | capture what was done, behind the scenes. Pass `item_id` to attach the entry to one item instead of the whole project |
| `add_memory` | store a repo link, note, meeting transcript, or a pointer to a local file (`kind="file"` + `path` — Trackden never touches the file itself). Pass `item_id`/`folder_id` to attach it to one item or folder instead of the whole project |
| `add_decision` | record a decision **and why**, into the project's decisions log |
| `search` | semantic search across all session logs |
| `add_item` | create a new item — an agent can put work into the tracker itself |
| `add_folder` | create a new (optionally nested) folder |
| `add_status` | add a project-specific status name, with the behaviour class it follows |
| `get_playbook` | Trackden's own rules for using Trackden — full text, version, no arguments, works before any project exists. A short digest already rides inside the MCP `overview` response, so an agent gets the reminder without a second call |

Tool count was 16 through the item-scoping work above — those parameters (`item_id`,
`folder_id`, `path` on `add_memory`; `item_id` on `save_progress` and `get_history`) extend
existing tools rather than adding new ones. `get_playbook` is the one genuinely new tool:
16 → 17.

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
