"""The status vocabulary — four fixed CLASSES, a growable set of NAMES.

`whats_next` has to answer "is this item something to offer next?", and a name
alone cannot tell it: `blocked`, `parked` and `postponed` are three names for one
behaviour. So behaviour is fixed here in code as four classes, and names are data
a project may add to (see `models.ItemStatus`).

The shipped defaults are ALWAYS valid: a project's extra names are added on top,
never substituted, so adding `parked` can never invalidate `todo` or `done` — and
every item already in the database keeps a meaningful status the moment this lands.

Pure by design: no DB, no filesystem, no `app.*` imports. `repository` reads a
project's extras and hands them in.
"""

from __future__ import annotations

# ---- the four classes (code owns these; they never grow) ----

OPEN = "open"          # not started — `whats_next` may return it
ACTIVE = "active"      # someone is on it — `whats_next` reports it
WAITING = "waiting"    # started, not actionable now — skipped, but counted
CLOSED = "closed"      # finished or abandoned — hidden by default

CLASSES = frozenset({OPEN, ACTIVE, WAITING, CLOSED})

# A queue offers anything that is NOT `waiting` and NOT `closed` — a complement,
# not an allowlist. The deliberate consequence: a status this vocabulary cannot
# classify (a legacy row, or one set by hand in `psql`) is offered too, because it
# is neither waiting nor closed. That is on purpose — it surfaces the item instead
# of hiding it, so a human notices and corrects it.

# ---- the shipped default names (data owns the rest) ----

TODO = "todo"
DOING = "doing"
BLOCKED = "blocked"
DONE = "done"

DEFAULTS: dict[str, str] = {
    TODO: OPEN,
    DOING: ACTIVE,
    BLOCKED: WAITING,
    DONE: CLOSED,
}


def resolve(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The valid vocabulary: the shipped defaults, plus a project's extra names.

    `setdefault`, not `update` — a row that claimed `done -> open` would otherwise
    un-close every finished item in that project. Defaults win, always.
    """
    vocabulary = dict(DEFAULTS)
    for name, cls in (extra or {}).items():
        vocabulary.setdefault(name, cls)
    return vocabulary


def behaves_as(name: str, extra: dict[str, str] | None = None) -> str | None:
    """Which class this name behaves as, or None when the name is unknown."""
    return resolve(extra).get(name)


def is_valid(name: str, extra: dict[str, str] | None = None) -> bool:
    return name in resolve(extra)


def names_in(*classes: str, extra: dict[str, str] | None = None) -> frozenset[str]:
    """Every status name belonging to the given class(es).

    This is what the repository's queries are written against — they ask for
    "the closed names" or "the waiting names", never for a literal `"done"`.
    """
    unknown = set(classes) - CLASSES
    if unknown:
        raise ValueError(f"unknown status class: {', '.join(sorted(unknown))}")
    wanted = set(classes)
    return frozenset(
        name for name, cls in resolve(extra).items() if cls in wanted
    )
