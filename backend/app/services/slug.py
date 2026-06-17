import random
import re

from app.wordlists.adjectives import ADJECTIVES
from app.wordlists.nouns import NOUNS

# Slugs the system reserves for routes/endpoints (PRD §4).
RESERVED_SLUGS = frozenset(
    {
        "login", "signup", "api", "account", "admin", "static",
        "assets", "raw", "new", "health", "about",
    }
)

# 3–40 chars, lowercase alphanumeric + hyphens, start/end alphanumeric,
# no consecutive hyphens.
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?!-)){1,38}[a-z0-9]$")


class SlugError(ValueError):
    """Raised when a custom slug fails validation."""


def validate_custom_slug(slug: str) -> str:
    """Validate a user-supplied slug. Returns it normalized, or raises SlugError."""
    if not isinstance(slug, str):
        raise SlugError("Slug must be a string.")
    slug = slug.strip().lower()
    if len(slug) < 3 or len(slug) > 40:
        raise SlugError("Slug must be between 3 and 40 characters.")
    if "--" in slug:
        raise SlugError("Slug cannot contain consecutive hyphens.")
    if not _SLUG_RE.match(slug):
        raise SlugError(
            "Slug must be lowercase letters, numbers, and hyphens, "
            "and start and end with a letter or number."
        )
    if slug in RESERVED_SLUGS:
        raise SlugError("That slug is reserved.")
    return slug


def is_reserved(slug: str) -> bool:
    return slug in RESERVED_SLUGS


def generate_slug(rng: random.Random | None = None) -> str:
    """Generate a memorable {adjective}-{noun}-{NN} slug."""
    r = rng or random
    adjective = r.choice(ADJECTIVES)
    noun = r.choice(NOUNS)
    number = r.randint(0, 99)
    return f"{adjective}-{noun}-{number:02d}"
