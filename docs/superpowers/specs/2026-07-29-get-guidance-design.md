# Guidance read/write path — design

**Status:** approved 2026-07-29 · **Parent spec:** `BUILD_NOTES.md` → "LOCKED DESIGN — Storage model (hybrid)"

## Why this exists

Onboarding scaffolds `_way-of-work.md`, `_arch.md` and `_decisions.md` into
`~/.trackden/projects/<slug>/`, but **no MCP tool reads them.** `mcp_server.py` serves only
DB-backed data, so the guidance layer is write-only today: visible to a human who opens the
files, invisible to every agent. The storage model's stated purpose for central guidance is
that it reaches agents over MCP, so until a read path exists the layer delivers zero
agent-facing value.

This increment adds that read path, plus the one write that accumulates naturally during
work: recording a decision.

## Scope

**In:**
- `get_guidance` — an agent reads one guidance document.
- `add_decision` — an agent appends a decision, with its reasoning, to `_decisions.md`.
- CLI doors for both, so a human can use them without an agent present.
- Narrowing `add_memory` so decisions have exactly one home.

**Out, deliberately:**
- `update_guidance` — letting an agent rewrite a human's rules file needs its own safety
  thinking (overwrite vs. patch, backup, confirmation). Separate increment.
- `set_status` — DB-side, unrelated to guidance.
- Indexing guidance files in `search` (pgvector). The storage model requires it eventually;
  it is a different piece of work with its own embedding and staleness concerns.
- cwd→project resolution. `projects.repo_path` exists to power it, but the launcher/alias
  design it belongs to is still deferred.

## Architecture

The same layering onboarding used, plus one small orchestrator.

**Correction (made while planning):** an earlier draft of this section said "no new
modules". That was wrong. The status vocabulary needs a single owner, and neither existing
layer can hold it — `workspace.py` cannot decide `unknown_project` (that is DB state) and
putting it in the wrappers would duplicate it across the MCP and CLI doors, which is how two
doors drift apart. So a small `guidance.py` orchestrates `repository` + `workspace` and owns
the statuses, exactly as `onboard.py` orchestrates onboarding. The wrappers stay thin.

| Layer | Responsibility | Change |
|---|---|---|
| `workspace.py` | Owns the `~/.trackden` tree. Filesystem only, base path injectable. | Gains the read path it currently lacks, plus the decision append. |
| `mcp_server.py` | Agent-facing door. Thin wrappers, no logic. | Two new tools. |
| `cli.py` | Human-facing door. Thin Typer commands. | Two new commands. |
| `repository.py` | DB state. | No new functions — the existing `get_project()` confirms a project is real. |

**Why `workspace.py` and not a new module:** it already owns every path under
`~/.trackden` and every guidance filename. Splitting reads into a sibling module would put
two owners on one directory. The file grows by roughly 60 lines and keeps one
responsibility.

**One change of shape:** the guidance filenames currently live in a dict *inside*
`scaffold_project`. Reading needs them too, so they move out to a module-level constant
mapping the public document name to its filename:

```python
GUIDANCE_DOCS = {
    "way-of-work": "_way-of-work.md",
    "arch": "_arch.md",
    "decisions": "_decisions.md",
}
```

`scaffold_project` then uses the same constant, so the two paths cannot drift.

## Contracts

### `get_guidance(project: str, doc: str = "way-of-work") -> dict`

One document per call. There are exactly three, so the tool description enumerates them and
no index step is needed — an agent fetching the rules at session start pays nothing for arch
or decisions it is not using.

`doc` defaults to `"way-of-work"` because reading the rules at session start is the common
case.

Returns:

```python
{"project": str, "doc": str, "path": str | None, "status": str, "text": str | None}
```

### `add_decision(project: str, decision: str, because: str, rejected: str | None = None) -> dict`

Appends to `_decisions.md` in the shape `workspace.py`'s existing `_DECISIONS_TEMPLATE`
already scaffolds:

```markdown
## 2026-07-29 — Store embeddings locally with fastembed

- **Chose:** Store embeddings locally with fastembed
- **Because:** keeps the core keyless — no API credits
- **Rejected:** OpenAI embeddings (needs a key at read time)
```

`because` is **required**, not optional. A decisions log that records what changed without
why is the failure mode this file exists to prevent. `rejected` is optional — it is often
the most useful line months later, but not every decision has a real alternative.

The date is `datetime.now(timezone.utc).date().isoformat()`, matching `models._now()`'s
timezone-aware UTC convention.

Returns `{"project": str, "path": str | None, "status": str}`.

### Status vocabulary

Shared by both tools, except `unknown_doc`, which only `get_guidance` can return —
`add_decision` takes no `doc` argument. `status` carries more weight than it appears to:

| `status` | Meaning | Why it is distinct |
|---|---|---|
| `filled` | Document exists and has been edited. | The normal case. |
| `template` | Document exists but is untouched boilerplate. | Tells an agent not to spend a turn reasoning about placeholder prose. `text` is still returned. |
| `not_scaffolded` | Project exists in the DB, its workspace folder does not. | A real state — reachable by an interrupt during onboarding, or a database restored onto a fresh machine. The message points at `trackden onboard <slug>`, which is idempotent. |
| `unknown_project` | No such project in the DB. | Distinct from `not_scaffolded`; the fix is different. |
| `unknown_doc` | `doc` is not one of the three. | Returned with the valid names, since a wrong enum from a model is the likely cause. |
| `appended` | `add_decision` succeeded. | — |

### CLI doors

```
trackden guidance <project> [--doc way-of-work|arch|decisions]
trackden decide <project> <decision> --because <text> [--rejected <text>]
```

Thin wrappers over the same `workspace` functions, printing the document or a confirmation.
`BUILD_NOTES.md` commits to "one core, three doors"; a human should be able to read their own
guidance with no agent in the room.

## Routing — decisions get exactly one home

`add_memory(kind="decision")` currently writes a decision to the DB `memory` table. Adding
`add_decision` writing to a file would give an agent two tools for one intent — precisely
the ambiguity the storage model's "the tool is the destination" rule exists to prevent.

Therefore `add_memory` narrows to `link | note | transcript`, and its tool description sends
decisions to `add_decision`. `trackden remember --kind` narrows identically.

**Narrowing means rejecting, not merely un-advertising.** `repository.add_memory` validates
`kind` and refuses `"decision"` with a message naming `add_decision` as the right tool.
Validation lives in the repository rather than in each wrapper, so both the MCP and CLI doors
are covered by one check — and an agent that guesses the old kind is told, instead of
silently writing a decision into the wrong home.

**The `memory` table is empty — 0 rows of any kind, verified against the live database on
2026-07-29 — so there is nothing to migrate.** Had rows existed, this would have needed a
migration step and a different decision.

`models.py`'s `Memory` docstring and its `kind` comment get updated so the schema stops
advertising a kind the tools no longer accept.

## Error handling

**No exceptions cross the MCP boundary.** Every failure is a `status` the agent can act on,
because an exception surfaces to an agent as an opaque tool error it cannot reason about.
This matches the existing tools, which return `{}` or `""` rather than raising — but improves
on them by saying *which* failure occurred.

**Neither tool scaffolds anything.** Reading must not write. `add_decision` also refuses to
create a missing workspace: scaffolding stays onboarding's single job, or a project could
end up with a decisions log and no way-of-work file. Both report `not_scaffolded` instead.

Path safety comes free — both tools resolve through `workspace.project_dir()`, which already
validates the slug against a whitelist and raises on anything unsafe.

## Testing

Follows the conventions the onboarding branch established.

- **Guidance read/append:** `tmp_path` plus the existing `home` fixture. No Postgres. Cases:
  a filled document · an untouched template · a missing workspace · an unknown document name
  · appending to an empty decisions file · appending twice (both entries present, order
  preserved) · `rejected` omitted.
- **Template detection:** a scaffolded-then-edited file reports `filled`; a scaffolded and
  untouched one reports `template`.
- **MCP + CLI wrappers:** monkeypatched `repository`, so no database. Assert delegation and
  that the `status` reaches the caller.
- **One `@pytest.mark.db` test** for the project-existence path, against the
  `session_tracker_test` database, using the `temp_slug` fixture for cleanup.
- **Routing:** a test asserting `add_memory` rejects or no longer advertises `decision`.

## Assumptions and limitations

- **Template detection compares text.** "Untouched" is decided by rendering the stored
  template with the project's display name from the DB and comparing exactly. If a project
  is renamed after scaffolding, an untouched file will report `filled` rather than
  `template`. The consequence is mild — an agent reads boilerplate once — and the
  alternative (a machine marker inside a human-edited file) was rejected as worse.
- **`_decisions.md` is append-only by this tool.** Editing or removing an entry is a human
  action in the file. Nothing parses the file back into structured data, so the format is a
  convention rather than an interface.
- Guidance files remain **outside** `search` until the pgvector work lands, so
  "where did we discuss X" still only covers session logs.
- `get_guidance` returns whole documents. If a way-of-work file ever grows large enough that
  this hurts, the answer is section-level retrieval, which is out of scope here.
