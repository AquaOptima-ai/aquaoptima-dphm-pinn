"""Canonical denylist of forbidden vocabulary tokens.

This module is the **single source of truth** for tokens that must
never appear as a safety-flag name, capability token, runtime-mode
identifier, or any other contract verb anywhere in the AquaOptima
SDK or in any deployable component. Sprint 40's
``docs/architecture/contracts-inventory.md`` and
``docs/safety/capability-model-and-safety-gates.md`` define this list;
this module is its machine-readable projection.

The Sprint 41 forbidden-vocabulary grep scan (see
``tests/aquaoptima_contracts/test_forbidden_vocabulary_scan.py``)
exempts **only** this module. Every other file under
``src/aquaoptima_contracts/``, ``tests/aquaoptima_contracts/``, and
``src/aquaoptima_contracts/fixtures/`` is scanned. If any forbidden
token is found outside this module, CI fails.

Reminder of the non-negotiable product boundary:

- No live OT binding.
- No PLC/PAC/SCADA write (required exact phrase: no PLC/PAC/SCADA write).
- No command emission.
- No setpoint output.
- No control-loop closure.

"Deployment" in this SDK refers to a packaging / audit-evidence
bundle. It does not authorize any write, dispatch, actuation, or
control surface. See ``docs/product/sprint39-shadow-deployment-mvp-plan.md``
for the audit-only framing.
"""

from __future__ import annotations

# -- BEGIN FORBIDDEN VOCABULARY DENYLIST ------------------------------------
# Every literal below is intentionally enumerated. The Sprint 41
# forbidden-vocabulary scan grants a single exemption (this section
# of this module) and CI fails on any other occurrence.
FORBIDDEN_VOCABULARY: frozenset[str] = frozenset(
    {
        "live_ot_bind_write",
        "plc_write",
        "pac_write",
        "scada_write",
        "setpoint_output",
        "command_emit",
        "actuator_control",
        "closed_loop_control",
        "remote_control_api",
        "llm_command_execution",
        "operator_chat_to_control",
        "unreviewed_package_activation",
    }
)
# -- END FORBIDDEN VOCABULARY DENYLIST --------------------------------------


def contains_forbidden_token(text: str) -> frozenset[str]:
    """Return the set of forbidden tokens found in ``text``.

    Uses an exact substring match against the canonical denylist. The
    SDK's lowercase snake_case token convention makes substring
    collisions rare, but callers that need word-boundary scanning
    should layer their own regex on top of this helper.
    """

    if not isinstance(text, str):
        raise TypeError(
            f"contains_forbidden_token requires str, got {type(text).__name__}"
        )
    hits: set[str] = set()
    for token in FORBIDDEN_VOCABULARY:
        if token in text:
            hits.add(token)
    return frozenset(hits)
