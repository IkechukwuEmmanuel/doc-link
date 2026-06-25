"""Username validation and normalization for user accounts.

Usernames occupy the same top-level URL namespace as pads and reserved routes,
so they use the same reserved word list. They are case-insensitive, stored
lowercase, but can be displayed as entered.
"""

import re

from app.services.slug import RESERVED_SLUGS

# 3–40 chars, lowercase alphanumeric + hyphens/underscores, start/end alphanumeric,
# no consecutive hyphens.
_USERNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_]|-(?!-)){1,38}[a-z0-9]$")


class UsernameError(ValueError):
    """Raised when a username fails validation."""


def validate_username(username: str) -> str:
    """Validate and normalize a user-supplied username.
    
    Returns the normalized lowercase version, or raises UsernameError.
    Allows alphanumeric, hyphens, and underscores. Reserved words are rejected.
    """
    if not isinstance(username, str):
        raise UsernameError("Username must be a string.")
    username = username.strip().lower()
    if len(username) < 3 or len(username) > 40:
        raise UsernameError("Username must be between 3 and 40 characters.")
    if "--" in username:
        raise UsernameError("Username cannot contain consecutive hyphens.")
    if not _USERNAME_RE.match(username):
        raise UsernameError(
            "Username must be lowercase letters, numbers, hyphens, and underscores, "
            "and start and end with a letter or number."
        )
    if username in RESERVED_SLUGS:
        raise UsernameError("That username is reserved.")
    return username


def is_reserved(username: str) -> bool:
    """Check if a username is reserved."""
    return username.lower() in RESERVED_SLUGS
