"""Sprint 27 governance guardrails (A+B pivot foundation).

Two pure, IO-light guards the offline advisory product runs in CI and before any scorecard
is accepted:

1. :func:`assert_holdout_isolated` -- the data-leakage guard. Given the train/val index
   keys (or timestamps) and the locked-holdout window, prove March 2026 never appears in
   train/val. Mirrors the ``holdout_isolation`` block already emitted in the scorecards.

2. :func:`scan_modeling_source_for_governance_violations` -- static text scan over the
   modeling source tree. FAILs if modeling code imports the edge SDK or names a
   write-capable OT connector. A violation forces the scorecard safety status to FAIL
   regardless of model metrics (PRD requirement).

Neither guard opens a network/OT connection or loads a model. They are deny-by-default
value functions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

# --- Leakage guard ---------------------------------------------------------

# The locked holdout is March 2026. Any train/val record whose month key falls in this
# window is leakage.
LOCKED_HOLDOUT_PREFIX = "2026-03"


@dataclass(frozen=True)
class HoldoutIsolationResult:
    isolated: bool
    leaked_keys: tuple[str, ...] = ()
    holdout_prefix: str = LOCKED_HOLDOUT_PREFIX
    n_train_val_checked: int = 0


def assert_holdout_isolated(
    train_val_keys: Iterable[str],
    *,
    holdout_prefix: str = LOCKED_HOLDOUT_PREFIX,
) -> HoldoutIsolationResult:
    """Return an isolation result; ``isolated=False`` if any key falls in the holdout.

    ``train_val_keys`` are ISO-ish timestamp/date strings (e.g. ``"2025-07-01 12:00:00"``)
    or pre-bucketed month keys (``"2025-07"``). We compare by prefix so both work.
    """
    keys = [str(k) for k in train_val_keys]
    leaked = tuple(sorted({k for k in keys if k.startswith(holdout_prefix)}))
    return HoldoutIsolationResult(
        isolated=not leaked,
        leaked_keys=leaked,
        holdout_prefix=holdout_prefix,
        n_train_val_checked=len(keys),
    )


# --- Governance import / connector scan ------------------------------------

# Forbidden imports in MODELING code: the edge SDK and any live-control surface.
FORBIDDEN_IMPORT_PATTERNS = (
    re.compile(r"\bimport\s+aquaoptima\.edge\b"),
    re.compile(r"\bfrom\s+aquaoptima\.edge\b"),
    re.compile(r"\bimport\s+aquaoptima_contracts\.edge\b"),
    re.compile(r"\bfrom\s+aquaoptima_contracts\.edge\b"),
)

# Write-capable / actuation connector tokens that must not appear in modeling code.
# Word-boundary matched, case-insensitive. (Plain substrings like "scada" are matched
# whole-word to avoid false hits inside docstrings describing the boundary.)
FORBIDDEN_CONNECTOR_TOKENS = (
    "modbus_write",
    "opcua_write",
    "write_setpoint",
    "send_command",
    "actuate",
    "plc_write",
    "pac_write",
    "ethercat_write",
    "codesys_write",
    "historian_write",
)


@dataclass(frozen=True)
class GovernanceScanResult:
    clean: bool
    violations: tuple[str, ...] = field(default_factory=tuple)
    files_scanned: int = 0

    @property
    def safety_status(self) -> str:
        return "PASS" if self.clean else "FAIL"


def scan_text_for_governance_violations(text: str, *, label: str = "<text>") -> list[str]:
    """Return a list of human-readable violation strings found in ``text``."""
    out: list[str] = []
    for pat in FORBIDDEN_IMPORT_PATTERNS:
        m = pat.search(text)
        if m:
            out.append(f"{label}: forbidden edge import {m.group(0)!r}")
    low = text.lower()
    for tok in FORBIDDEN_CONNECTOR_TOKENS:
        if re.search(rf"\b{re.escape(tok)}\b", low):
            out.append(f"{label}: forbidden write/actuation token {tok!r}")
    return out


def scan_modeling_source_for_governance_violations(
    roots: Sequence[Path | str],
    *,
    file_glob: str = "*.py",
    exclude_names: Sequence[str] = ("governance.py",),
) -> GovernanceScanResult:
    """Scan modeling source trees and FAIL on any edge import / write-connector token.

    Pass the MODELING source dirs only (e.g. the advisory/training/models packages). Do
    NOT pass the contracts SDK tree -- it legitimately defines the edge package and the
    forbidden-vocabulary list. ``exclude_names`` skips files that legitimately *define*
    the forbidden tokens (this module itself, by default).
    """
    violations: list[str] = []
    scanned = 0
    excluded = set(exclude_names)
    for root in roots:
        root_path = Path(root)
        if root_path.is_file():
            files = [root_path]
        else:
            files = sorted(root_path.rglob(file_glob))
        for f in files:
            if f.name in excluded:
                continue
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            scanned += 1
            violations.extend(scan_text_for_governance_violations(text, label=str(f)))
    return GovernanceScanResult(
        clean=not violations,
        violations=tuple(violations),
        files_scanned=scanned,
    )


__all__ = [
    "LOCKED_HOLDOUT_PREFIX",
    "HoldoutIsolationResult",
    "assert_holdout_isolated",
    "FORBIDDEN_IMPORT_PATTERNS",
    "FORBIDDEN_CONNECTOR_TOKENS",
    "GovernanceScanResult",
    "scan_text_for_governance_violations",
    "scan_modeling_source_for_governance_violations",
]
