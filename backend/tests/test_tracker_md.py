from app.tracker_md import is_generated, parse_tracker_md, render_tracker_md

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


ITEMS = [
    {"title": "Set up the repo", "status": "done", "folder": "Setup"},
    {"title": "Write the parser", "status": "todo", "folder": "Setup"},
    {"title": "Loose end", "status": "todo", "folder": None},
]


def test_render_groups_by_folder_and_marks_status():
    out = render_tracker_md("My Project", ITEMS)
    assert "# My Project — tracker (GENERATED)" in out
    assert "## Setup\n- [x] Set up the repo\n- [ ] Write the parser" in out
    assert "## Items\n- [ ] Loose end" in out


def test_render_reports_progress():
    assert "**Progress:** 1 / 3 done." in render_tracker_md("My Project", ITEMS)


def test_render_warns_against_hand_editing():
    assert "Do not edit by hand" in render_tracker_md("Empty", [])


def test_render_handles_no_items():
    out = render_tracker_md("Empty", [])
    assert "**Progress:** 0 / 0 done." in out


def test_render_round_trips_through_the_parser():
    reparsed = parse_tracker_md(render_tracker_md("P", ITEMS))
    assert [(i.title, i.status, i.folder) for i in reparsed.items] == [
        ("Set up the repo", "done", "Setup"),
        ("Write the parser", "todo", "Setup"),
        ("Loose end", "todo", "Items"),
    ]


def test_is_generated_true_for_the_rendered_mirror():
    assert is_generated(render_tracker_md("P", ITEMS)) is True


def test_is_generated_false_for_hand_written_text():
    assert is_generated("## Phase 0\n- [ ] a hand-written item\n") is False


def test_is_generated_false_for_empty_text():
    assert is_generated("") is False


def test_render_marks_any_closed_name_as_ticked():
    out = render_tracker_md(
        "P",
        [{"title": "abandoned", "status": "dropped", "folder": None}],
        closed={"done", "dropped"},
    )
    assert "- [x] abandoned" in out


def test_render_appends_a_non_default_status_name():
    out = render_tracker_md(
        "P",
        [{"title": "waiting on vendor", "status": "parked", "folder": None}],
    )
    assert "- [ ] waiting on vendor  · parked" in out


def test_render_does_not_annotate_a_plain_todo():
    out = render_tracker_md("P", [{"title": "plain", "status": "todo", "folder": None}])
    assert "- [ ] plain" in out
    assert "· todo" not in out


def test_render_does_not_annotate_a_closed_item():
    # the [x] already says it; the name would be noise
    out = render_tracker_md(
        "P",
        [{"title": "shipped", "status": "dropped", "folder": None}],
        closed={"done", "dropped"},
    )
    assert "· dropped" not in out


def test_render_counts_every_closed_name_as_progress():
    out = render_tracker_md(
        "P",
        [
            {"title": "a", "status": "done", "folder": None},
            {"title": "b", "status": "dropped", "folder": None},
            {"title": "c", "status": "todo", "folder": None},
        ],
        closed={"done", "dropped"},
    )
    assert "**Progress:** 2 / 3 done." in out


def test_render_without_a_closed_set_still_means_just_done():
    # every pre-existing caller relies on this default
    out = render_tracker_md(
        "P",
        [{"title": "a", "status": "dropped", "folder": None}],
    )
    assert "- [ ] a" in out


def test_an_annotated_line_reparses_to_a_todo_item():
    """The parser must survive the annotation the renderer adds."""
    rendered = render_tracker_md(
        "P", [{"title": "waiting on vendor", "status": "parked", "folder": None}]
    )
    reparsed = parse_tracker_md(rendered)
    assert reparsed.items[0].status == "todo"
