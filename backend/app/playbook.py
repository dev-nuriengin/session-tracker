"""Trackden's own rules for using Trackden — product-owned, read-only.

Distinct from `guidance.py`, which serves the HUMAN's rules for ONE project. This is
the same for every user and ships with the code, so it lives here as a module constant
rather than a data file: `pyproject.toml` declares `packages = ["app"]`, and a Python
constant is guaranteed into the wheel with no packaging configuration, and is directly
assertable in a pure test.

The two are allowed to disagree. When they do, the project's way-of-work wins — rule 11
says so, because a product should not overrule the person using it.

Pure by design: no DB, no filesystem, no `app.*` imports.
"""

from __future__ import annotations

VERSION = 1

# The digest rides inside EVERY `overview` response. That is deliberate: an agent cannot
# be relied on to call a second tool for the rules, so the rules travel in the payload it
# already wants. The budget is asserted by a test — see MAX_DIGEST.
#
# MAX_DIGEST exists so that growing the digest is a deliberate decision, not a habit —
# every call to `overview` pays for these bytes. The number itself isn't meaningful;
# it's a ceiling with enough room that a normal wording fix doesn't force character-
# shaving, not a target to fill.
MAX_DIGEST = 1700

DIGEST = """TRACKDEN PLAYBOOK v1

1.  Read before you work: overview, then get_guidance("way-of-work").
2.  Trackden remembers; it never decides. Don't let it gate or approve work.
3.  Save on any of four triggers: a step finished; a decision made; you hold
    findings that aren't written down yet; the user says save.
4.  Work not yet tracked? add_item() it before you start. Ask before inventing
    folders - the shape of the user's work is theirs, not yours.
5.  Status: set `doing` freely and silently. Announce a `waiting` change in one
    line. ASK before you close anything, unless the user just said it's done.
6.  Never invent a status name - `statuses` in this payload is the valid set. If
    an item comes back with a name that is NOT in it, that is deliberate: an
    unclassifiable status is surfaced so a human can fix it. Offer to fix it.
7.  The set is meant to grow. If the user's real state has no name ("on hold" is
    not "blocked"), offer add_status(), and explain what the CLASS does.
8.  A decision needs its reason: add_decision(decision, because).
9.  Files stay in the user's folders. Ask where it goes, then record the path
    with add_memory(kind="file"). Trackden never creates, moves or reads files.
10. Attach to the item, not the project: add_memory(item_id=...) and
    save_progress(item_id=...). Resume one item with get_history(item_id=...).
11. The project's way-of-work outranks this playbook. Conflict: follow the
    project - unless it's an untouched template, which outranks nothing.
"""

TEXT = """# Trackden playbook v1

Trackden's own rules for using Trackden. Read this once per session; the short digest
in every `overview` response is the reminder.

## 1. What Trackden is, and what it is not

A local, private memory of the user's work. It holds structure and progress so a new
session does not start from nothing.

It is NOT an agent. It does no work, and it does not gate, approve or sequence yours.
It never refuses a status change, never enforces an order, never locks anything. When
you find yourself treating it as an authority, you have the relationship backwards: it
records, the user decides.

## 2. Opening a session

Call `overview(project)` first. It is cheap and carries the next step, how many items
are open, how many are waiting, the last activity, this project's valid status names,
and this digest.

Then `get_guidance(project, "way-of-work")` before you change anything — those are the
human's rules for this codebase. If it comes back `template`, it is untouched
boilerplate; do not over-read it.

Resuming one specific item? `get_history(project, item_id=...)` gives that item's whole
story — its logs, its files, its status — instead of the project's last N entries mixed
with every other item's.

If the project is unknown, say so and ask. Do not invent a slug.

## 3. When to save

Four triggers. Any one of them is enough:

- **A step finished.** `save_progress(project, thread_id, note, kind="step")`.
- **A decision was made.** `add_decision(project, decision, because=...)`.
- **You hold findings that are not written down yet.** This is the one that gets
  missed. If the session ended right now, would anything you learned be lost? Then
  save. A cause identified but not fixed is exactly this case.
- **The user says save.**

You cannot reliably tell how much time has passed, so do not try to save "every N
minutes".

## 4. Statuses

Every status name behaves as one of four CLASSES:

- `open` — not started. Can be offered as the next step.
- `active` — being worked on. Also offered; an item someone is on IS the next step.
- `waiting` — started, stalled. Skipped as the next step, but counted and still listed.
- `closed` — finished or abandoned. Hidden from the queue.

How loudly to speak scales with how expensive being wrong is:

- Setting `doing` — just do it, silently. Cheap and obvious.
- Setting a `waiting` name — do it, then say so in one line. The user needs to know
  something stalled, but it is reversible.
- Closing anything — ASK first, unless the user just told you it is finished. Closing
  hides an item from the queue.

`set_status(project, item_id, status)` returns `unknown_status` with the `valid` list if
you get a name wrong, so correct yourself from that rather than guessing again.

**An item whose status is in no vocabulary at all will be offered to you as the next
step.** That is deliberate, not a bug: a legacy row or one edited by hand surfaces
instead of hiding, so it gets noticed. Tell the user and offer to set a real status.

## 5. Growing the vocabulary

The four shipped names — `todo`, `doing`, `blocked`, `done` — are a starting set, not a
limit. A project can add its own with `add_status(project, name, behaves_as)`.

Offer; do not impose. When the user's real situation has no matching name, name the
mismatch rather than forcing their state into a label that is nearly right:

> "This isn't blocked — nothing is in your way, you chose to set it aside. Want a
> `parked` status? It would behave as `waiting`, so it stays visible but stops showing
> up as your next step."

Explain what the class DOES, not just what the name is. The user is choosing behaviour.

## 6. Files and the hybrid rule

The user's folder layout is theirs. Trackden stores WHERE something is and never creates,
moves, deletes or reads it.

So: ask where a file belongs, let the user answer, then record the path with
`add_memory(project, content, kind="file", path=..., item_id=...)`. The path is stored
absolute, so it survives a different working directory. A path that does not exist yet
is still recorded, with a warning — recording where something is about to go is
legitimate.

Attach memory and progress to the item they belong to (`item_id=...`) whenever the fact
is about one item. Project-level is right for genuinely project-level facts and wrong
for a specific bug's findings.

Decisions do not go here. `add_memory` accepts `link`, `note`, `transcript` and `file`,
and rejects `decision` — use `add_decision`, so a decision has exactly one home.

## 7. Precedence and anti-patterns

**The project's `_way-of-work.md` outranks this playbook.** Where they conflict, follow
the project. This document is a default, not an authority. An untouched template (see
`template` in section 2) is not filled in yet, so it outranks nothing.

Do not:

- guess a status name — `statuses` in the `overview` payload is the valid set;
- record a decision without its reason — `because` is required, and a decision without
  it is worthless to the next session;
- invent a folder structure without asking;
- create, move or read a file the user did not ask you to;
- offer to delete a project — there is no delete tool, so say so rather than promise it.
  Removing a project is the user's own `trackden delete` command;
- claim you saved something you did not;
- treat Trackden as an approval step. It is memory.
"""
