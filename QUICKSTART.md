# Quickstart — your first 5 minutes

Get Trackden running locally and give your AI agent memory. Everything stays on
your machine — **no account, no cloud, no API key needed for the core.**

> **Who this is for:** anyone who uses an AI coding agent (Claude Code, Codex, …) and wants
> it to remember project history across sessions. Full design lives in [`README.md`](./README.md).

## Prerequisites (1 min)

- **Docker** (runs Postgres) — [install](https://docs.docker.com/get-docker/)
- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** (Python runner for the CLI + MCP server)
- *(optional, for the web view)* **Node.js 18+**
- An AI agent that speaks **MCP** (e.g. Claude Code) — this is where the value comes from

## 1 · Install (2 min)

```bash
git clone https://github.com/dev-nuriengin/session-tracker
cd session-tracker/backend
uv tool install .          # installs the `trackden` command (~62 MB)
trackden setup             # database + schema + your agents
```

Want semantic search (`trackden ask`) or the optional summariser? Install the extras:
`uv tool install '.[search]'`, `'.[brain]'`, or `'.[all]'`. They're opt-in because the
local embedding model alone is ~130 MB, and you don't need it to track work.

`trackden setup` starts the Postgres container, creates the tables, and adds Trackden to
whichever AI agents it finds on your machine. It shows you every config file it intends
to write and backs each one up first. Safe to re-run.

Want to see what it would do first? `trackden setup --check` diagnoses and changes nothing.

It starts **empty** — Trackden invents nothing, so `trackden onboard` (next step) is the
only way anything gets in. **No `.env` or API key required** — the core makes zero LLM calls.

> Prefer not to install globally? `docker compose up -d db` from the repo root, then run
> the CLI as `uv run trackden …` from `backend/`. Everything below works the same.

## 2 · Onboard your first project (1 min)

One command brings a project in: it scans the repo you point it at, offers to import
any checklist it finds, and scaffolds the rest. **Your repo is never modified.**

```bash
trackden onboard                 # interactive wizard
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
trackden add-project my-first-project
trackden add-item my-first-project "Set up the repo"
trackden list
```

That's your structure. An "item" is domain-agnostic — a *ticket*, a *bill*, a *deliverable*;
it's just a unit of work.

Onboarded the wrong repo, or done with a project? `trackden delete <project>`
removes it and everything under it (items, folders, memory, sessions, logs) — it previews
what it's about to remove and asks first (`--yes`/`-y` skips the prompt). Your guidance
files in `~/.trackden/projects/<slug>/` are kept either way, and it tells you where.
CLI only — there's no MCP tool for this, so an agent can't do it for you.

The `_tracker.md` mirror rewrites itself after `add-item` and `set-status`, so you rarely
need to think about it. `trackden sync [project]` repairs one that drifted anyway —
if a refresh ever failed, or you edited the database by hand.

## 3 · Connect your agent — the heart (2 min)

This is the point of the product: your agent plugs into the tracker over **MCP** and gets
continuity with **no per-agent setup**.

**`trackden setup` already did this** for every agent it found on your machine, and
printed the config block for any it didn't. Restart your agent so it picks up the change
(Claude Code will ask you to approve the `trackden` server the first time).

**Adding it by hand?** `trackden setup --check` prints the block. It goes in:

| Agent | File |
|---|---|
| Claude Code | `claude mcp add --scope user trackden -- <the command from the block>` |
| Codex | `~/.codex/config.toml`, as `[mcp_servers.trackden]` |
| Cursor | `~/.cursor/mcp.json` |
| Anything else | wherever that tool documents its MCP servers — the block is standard |

The path in the block is **absolute**, so your agent finds Trackden from any project, not
just this repo. (The `.mcp.json` at this repo's root uses a relative path and is only for
working *on* Trackden itself.)

Your agent now has these tools:

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

- **CLI:** `trackden show my-first-project` · `trackden ask "what did I do last?"`
- **Web view:** run `cd frontend && npm run dev` → http://localhost:3000

## You're done 🎉

From now on, as you work with your agent it **reads history first** and **saves progress
behind the scenes** — across sessions, across agents. Your data never leaves your machine.

### Where to go next
- **The optional brain** (on-demand summaries, `trackden eval`) calls Claude — copy
  `.env.example` → `.env` and set `ANTHROPIC_API_KEY` only if you want it. Everything else runs keyless.
- **Full architecture & privacy model:** [`README.md`](./README.md)
- **Working in the repo as an agent/contributor:** [`AGENTS.md`](./AGENTS.md)
