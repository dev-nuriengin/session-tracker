"""The status vocabulary — pure, so no Postgres is involved."""

import pytest

from app import statuses


def test_the_four_classes_are_fixed():
    assert statuses.CLASSES == {"open", "active", "waiting", "closed"}


def test_shipped_defaults_map_every_name_to_a_class():
    assert statuses.DEFAULTS == {
        "todo": "open",
        "doing": "active",
        "blocked": "waiting",
        "done": "closed",
    }
    assert set(statuses.DEFAULTS.values()) <= statuses.CLASSES


def test_resolve_with_no_extras_is_the_defaults():
    assert statuses.resolve(None) == statuses.DEFAULTS
    assert statuses.resolve({}) == statuses.DEFAULTS


def test_resolve_adds_extras_on_top_of_the_defaults():
    vocabulary = statuses.resolve({"parked": "waiting"})
    assert vocabulary["parked"] == "waiting"
    # the whole point: adding a name never removes one
    assert vocabulary["todo"] == "open"
    assert vocabulary["done"] == "closed"


def test_an_extra_can_never_override_a_default():
    # a stray row claiming done->open must not be able to un-close every done item
    vocabulary = statuses.resolve({"done": "open"})
    assert vocabulary["done"] == "closed"


def test_resolve_does_not_mutate_defaults():
    statuses.resolve({"parked": "waiting"})
    assert "parked" not in statuses.DEFAULTS


def test_behaves_as_knows_defaults_and_extras():
    assert statuses.behaves_as("blocked") == "waiting"
    assert statuses.behaves_as("parked", {"parked": "waiting"}) == "waiting"


def test_behaves_as_is_none_for_an_unknown_name():
    assert statuses.behaves_as("nonsense") is None


def test_is_valid_follows_the_resolved_vocabulary():
    assert statuses.is_valid("todo") is True
    assert statuses.is_valid("parked") is False
    assert statuses.is_valid("parked", {"parked": "waiting"}) is True


def test_names_in_collects_every_name_of_a_class():
    assert statuses.names_in("closed") == {"done"}
    assert statuses.names_in("waiting", extra={"parked": "waiting"}) == {"blocked", "parked"}


def test_names_in_accepts_several_classes():
    assert statuses.names_in("open", "active") == {"todo", "doing"}


def test_names_in_rejects_an_unknown_class():
    with pytest.raises(ValueError, match="unknown status class"):
        statuses.names_in("sideways")


def test_class_order_is_the_lifecycle_order():
    assert statuses.CLASS_ORDER == ("open", "active", "waiting", "closed")


def test_classes_and_class_order_hold_the_same_names():
    assert statuses.CLASSES == frozenset(statuses.CLASS_ORDER)
