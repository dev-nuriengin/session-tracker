"""Shared test fixtures.

Onboarding's logic is deliberately pure — text in/out, and a filesystem layer whose
base path is injectable — so nearly all of it tests with no Postgres. The few tests
that DO need the DB are marked `@pytest.mark.db` and are pointed at a DEDICATED test
database — never the one `.env` configures — via the `_db_ready` fixture below, so
`uv run pytest` can never create or delete a row in a developer's real data.
"""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

# ---- Point every test process at a dedicated test database, before `app.db` (or
# anything that imports it) is ever imported. This runs at module import time, above
# any `app.*` import (there are none at this point in the file) — conftest.py is
# imported by pytest before it collects test modules in this directory, so setting
# os.environ here is early enough for `app.db`'s module-level `create_engine(...)`
# to pick it up. ----

# Mirrors app.db's own fallback default — duplicated rather than imported, since
# importing app.db here is exactly what must not happen before DATABASE_URL is set.
_DEFAULT_DATABASE_URL = "postgresql+psycopg://session:session@localhost:5433/session_tracker"


def _derive_test_database_url() -> str:
    """The URL tests actually connect to — always distinguishable from `.env`'s.

    Honours `TRACKDEN_TEST_DATABASE_URL` if set. Otherwise derives one from the
    configured `DATABASE_URL` (process env, else `.env`, else the same default
    `app.db` falls back to) by appending `_test` to the database name.
    """
    override = os.environ.get("TRACKDEN_TEST_DATABASE_URL")
    if override:
        return override

    load_dotenv()  # same lookup app.db does — populates os.environ from ../.env
    base = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    url = make_url(base)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


TEST_DATABASE_URL = _derive_test_database_url()

_test_db_name = make_url(TEST_DATABASE_URL).database or ""
if not _test_db_name.endswith(("_test", "_smoke")):
    # Hard safety assertion: fail loudly rather than risk the suite ever opening
    # whatever database a real DATABASE_URL points at (6 real user projects live
    # there). TRACKDEN_TEST_DATABASE_URL, if set, must also end this way.
    raise RuntimeError(
        "Refusing to run tests: the resolved test database "
        f"{_test_db_name!r} is not clearly a test database (it must end in "
        "`_test` or `_smoke`). Set TRACKDEN_TEST_DATABASE_URL to make this "
        "unambiguous — the suite must never be able to open the configured "
        "(real) DATABASE_URL."
    )

# Set BEFORE any `app.*` import can happen. app.db's own load_dotenv() call never
# overrides an already-set environment variable, so this wins.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated ~/.trackden for one test. Never touches the real home."""
    workspace = tmp_path / ".trackden"
    monkeypatch.setenv("TRACKDEN_HOME", str(workspace))
    return workspace


_TEARDOWN_OUTCOMES = ("deleted", "unknown_project")


def _assert_clean_teardown(slug: str, outcome: dict) -> None:
    """Fail loudly if teardown's own delete didn't do what it claims.

    Only `deleted` (the test's project still existed) and `unknown_project` (a test
    already removed it) are legitimate — anything else is a regression that would
    otherwise leak silently: state from THIS test surviving into the next one, only
    surfacing as a confusing failure somewhere else entirely.
    """
    status = outcome.get("status")
    assert status in _TEARDOWN_OUTCOMES, (
        f"teardown delete of {slug!r} returned unexpected status {status!r} "
        f"(expected one of {_TEARDOWN_OUTCOMES}) — the project may not have been "
        "cleaned up, and later tests could see stale state"
    )


@pytest.fixture
def temp_slug():
    """A project slug that is deleted from the (test) DB afterwards (db-marked tests).

    Teardown delegates to `repository.delete_project`, the product's own delete
    semantics (order: session logs -> memory -> project — see its docstring). A
    test that already deleted this slug leaves teardown an honest `unknown_project`
    miss, not an error.
    """
    slug = "pytest-onboard-tmp"
    yield slug
    from app import repository

    _assert_clean_teardown(slug, repository.delete_project(slug))


@pytest.fixture
def temp_slug_b():
    """A SECOND disposable project slug, for tests that need two (db-marked)."""
    slug = "pytest-onboard-tmp-b"
    yield slug
    from app import repository

    _assert_clean_teardown(slug, repository.delete_project(slug))


def _server_reachable(admin_url) -> bool:
    from sqlalchemy import create_engine

    engine = create_engine(admin_url, future=True)
    try:
        with engine.connect():
            return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def _db_ready():
    """Bootstrap the dedicated test database once per session — or explain why not.

    Only requested by `@pytest.mark.db` tests (see `pytest_collection_modifyitems`
    below), so a pure-unit run never touches Postgres at all. When the DB server
    itself is unreachable: skip (dev convenience) unless `CI` is set and no
    explicit skip was opted into, in which case this is a hard failure — a green
    suite must never mean "the DB tests silently didn't run".
    """
    from sqlalchemy import create_engine, text

    url = make_url(TEST_DATABASE_URL)
    admin_url = url.set(database="postgres")
    message = "Postgres not reachable — run `docker compose up -d db`."

    if not _server_reachable(admin_url):
        skip_opt_in = os.environ.get("TRACKDEN_SKIP_DB_TESTS") == "1"
        in_ci = bool(os.environ.get("CI"))
        if skip_opt_in or not in_ci:
            pytest.skip(message)
        pytest.fail(message)

    engine = create_engine(admin_url, future=True, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            ).scalar()
            if not exists:
                try:
                    conn.execute(text(f'CREATE DATABASE "{url.database}"'))
                except Exception as exc:
                    # A different problem from "Postgres is down": the server is
                    # reachable, but this role can't create databases (no CREATEDB
                    # privilege). Report it as clearly as the unreachable-DB path,
                    # not as a raw SQLAlchemy traceback.
                    pytest.fail(
                        f"Could not create test database {url.database!r} on "
                        f"{admin_url.render_as_string(hide_password=True)} — the "
                        "configured role likely lacks CREATEDB privilege. Either "
                        "grant it, or create the database by hand, or point "
                        f"TRACKDEN_TEST_DATABASE_URL at one that already exists. "
                        f"({exc.__class__.__name__}: {exc})"
                    )
    finally:
        engine.dispose()

    from app.db import init_db

    init_db()


def pytest_collection_modifyitems(config, items):
    """Wire `_db_ready` into every `@pytest.mark.db` test — and only those — so
    the schema/skip/fail bootstrap above runs once per session, exactly where
    it's needed, without making every other test implicitly depend on Postgres."""
    for item in items:
        if "db" in item.keywords:
            item.fixturenames.append("_db_ready")
