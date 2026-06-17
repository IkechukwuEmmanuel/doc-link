import random

import pytest

from app.services import slug as slug_service


def test_generated_slug_format():
    rng = random.Random(42)
    for _ in range(100):
        s = slug_service.generate_slug(rng)
        slug_service.validate_custom_slug(s)  # must pass own validator
        parts = s.split("-")
        assert len(parts) == 3
        assert parts[2].isdigit() and len(parts[2]) == 2


@pytest.mark.parametrize(
    "good",
    ["abc", "blue-tiger-42", "a1b", "my-cool-pad", "x-y-z", "a" * 40],
)
def test_valid_slugs(good):
    assert slug_service.validate_custom_slug(good) == good


@pytest.mark.parametrize(
    "bad",
    [
        "ab",            # too short
        "a" * 41,        # too long
        "-abc",          # leading hyphen
        "abc-",          # trailing hyphen
        "a--b",          # consecutive hyphens
        "AbC",           # uppercase -> normalized; but has no other issue
        "a_b",           # underscore
        "a b",           # space
        "café-pad",      # non-ascii
    ],
)
def test_invalid_slugs(bad):
    # Uppercase normalizes to valid lowercase, so handle that one specially.
    if bad == "AbC":
        assert slug_service.validate_custom_slug(bad) == "abc"
        return
    with pytest.raises(slug_service.SlugError):
        slug_service.validate_custom_slug(bad)


@pytest.mark.parametrize("reserved", ["login", "api", "admin", "raw", "new"])
def test_reserved_slugs_rejected(reserved):
    with pytest.raises(slug_service.SlugError):
        slug_service.validate_custom_slug(reserved)
