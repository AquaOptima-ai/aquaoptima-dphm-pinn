"""``SafetyFlagSet`` and the canonical safety-flag token list.

Sprint 41 ships the seven canonical flags listed in
``docs/safety/capability-model-and-safety-gates.md``. Every flag
defaults to ``True`` for the current product safety boundary and must
remain ``True`` in every Phase 2 manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..base.validation import is_lowercase_snake_case_token
from .vocabulary import FORBIDDEN_VOCABULARY


class SafetyFlagError(ValueError):
    """Raised when a safety-flag set fails validation."""


# Order is significant: it is the canonical iteration order for
# ``to_dict`` callers that want explicit token traversal. JSON output
# itself sorts alphabetically.
CANONICAL_SAFETY_FLAG_TOKENS: tuple[str, ...] = (
    "offline",
    "read_only",
    "no_write",
    "no_control",
    "no_live_ot_binding",
    "no_setpoint_output",
    "packaging_audit_only",
)


_CANONICAL_SET: frozenset[str] = frozenset(CANONICAL_SAFETY_FLAG_TOKENS)


@dataclass(frozen=True)
class SafetyFlagSet:
    """Frozen, hashable canonical safety-flag set.

    Every canonical token must be supplied explicitly. Each must be
    exactly ``True`` for the current product boundary; ``False`` is
    rejected. Unknown flag names are rejected by :meth:`from_dict`.
    Forbidden vocabulary tokens are rejected by :meth:`from_dict` with
    a dedicated error message.
    """

    offline: bool
    read_only: bool
    no_write: bool
    no_control: bool
    no_live_ot_binding: bool
    no_setpoint_output: bool
    packaging_audit_only: bool

    def __post_init__(self) -> None:
        for name in CANONICAL_SAFETY_FLAG_TOKENS:
            value = getattr(self, name)
            if value is not True:
                raise SafetyFlagError(
                    f"safety flag {name!r} must be True for the current "
                    f"product boundary; got {value!r}"
                )

    def to_dict(self) -> dict[str, bool]:
        return {name: getattr(self, name) for name in CANONICAL_SAFETY_FLAG_TOKENS}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SafetyFlagSet":
        if not isinstance(data, Mapping):
            raise SafetyFlagError(
                f"SafetyFlagSet.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        keys = set(data.keys())
        forbidden_hits = keys & FORBIDDEN_VOCABULARY
        if forbidden_hits:
            raise SafetyFlagError(
                f"forbidden vocabulary token(s) used as safety flag "
                f"name(s): {sorted(forbidden_hits)}"
            )
        missing = _CANONICAL_SET - keys
        if missing:
            raise SafetyFlagError(
                f"SafetyFlagSet missing canonical token(s): {sorted(missing)}"
            )
        unknown = keys - _CANONICAL_SET
        if unknown:
            for token in unknown:
                if not isinstance(token, str) or not is_lowercase_snake_case_token(token):
                    raise SafetyFlagError(
                        f"safety flag name {token!r} is not a lowercase "
                        "snake_case token"
                    )
            raise SafetyFlagError(
                f"SafetyFlagSet rejects unknown token(s): {sorted(unknown)}"
            )
        return cls(**{name: bool(data[name]) for name in CANONICAL_SAFETY_FLAG_TOKENS})


def default_safety_flag_set() -> SafetyFlagSet:
    """Return the canonical Sprint 41 safety flag set (all True)."""

    return SafetyFlagSet(
        offline=True,
        read_only=True,
        no_write=True,
        no_control=True,
        no_live_ot_binding=True,
        no_setpoint_output=True,
        packaging_audit_only=True,
    )
