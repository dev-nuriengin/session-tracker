from app.tracker_md import parse_tracker_md

SAMPLE = """# Trackden — build progress

> Rules: `[x]` done, `[ ]` not. The first `[ ]` item is NEXT.

## Phase 0 — Scaffold & method
- [x] docker-compose: Postgres+pgvector
- [ ] Repo bootstrap

## Phase 4 — Core data model ← THE STORE ✅
- [X] DB engine/session
"""


def test_parse_extracts_title_status_and_folder():
    parsed = parse_tracker_md(SAMPLE)
    assert [(i.title, i.status, i.folder) for i in parsed.items] == [
        ("docker-compose: Postgres+pgvector", "done", "Phase 0 — Scaffold & method"),
        ("Repo bootstrap", "todo", "Phase 0 — Scaffold & method"),
        ("DB engine/session", "done", "Phase 4 — Core data model"),
    ]


def test_parse_lists_folders_in_first_seen_order_without_duplicates():
    assert parse_tracker_md(SAMPLE).folders == [
        "Phase 0 — Scaffold & method",
        "Phase 4 — Core data model",
    ]


def test_parse_ignores_blockquoted_examples_and_prose():
    assert parse_tracker_md("> - [ ] not a real item\njust prose\n").items == []


def test_parse_keeps_items_that_appear_before_any_heading_unfiled():
    parsed = parse_tracker_md("- [ ] loose item\n")
    assert (parsed.items[0].title, parsed.items[0].folder) == ("loose item", None)


def test_parse_accepts_asterisk_bullets():
    assert parse_tracker_md("* [ ] star bullet\n").items[0].title == "star bullet"
