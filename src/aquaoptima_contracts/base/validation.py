"""Shared validators and token guards used by every SDK schema."""

from __future__ import annotations

import re

_LOWERCASE_SNAKE_CASE_RE: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9_]*$")


def is_lowercase_snake_case_token(value: object) -> bool:
    """Return ``True`` when ``value`` is a lowercase snake_case token.

    The SDK uses lowercase snake_case for every canonical token in
    safety flags, capability tokens, runtime modes, and contract
    family identifiers. Anything else is rejected by the construction
    validators.
    """

    return isinstance(value, str) and _LOWERCASE_SNAKE_CASE_RE.match(value) is not None


def validate_token(
    value: object,
    *,
    field: str,
    allowed: frozenset[str] | None = None,
    forbidden: frozenset[str] | None = None,
) -> str:
    """Validate ``value`` as a token and return it.

    Parameters
    ----------
    value
        The candidate token.
    field
        Human-readable field name used in error messages.
    allowed
        Optional whitelist; if supplied, ``value`` must be a member.
    forbidden
        Optional blacklist; if supplied, ``value`` must not be a member.
    """

    if not isinstance(value, str):
        raise ValueError(
            f"{field} must be a string token, got {type(value).__name__}"
        )
    if not is_lowercase_snake_case_token(value):
        raise ValueError(
            f"{field} {value!r} is not a lowercase snake_case token"
        )
    if forbidden is not None and value in forbidden:
        raise ValueError(
            f"{field} {value!r} is a forbidden token"
        )
    if allowed is not None and value not in allowed:
        raise ValueError(
            f"{field} {value!r} is not in the allowed token list"
        )
    return value
