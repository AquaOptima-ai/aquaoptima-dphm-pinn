"""Optimizer Lite runtime contracts: modes, snapshots, quality, and authority gate."""

from .authority_gate import evaluate_authority
from .models import (
    AuthorityGateDecision,
    ControlIntent,
    PumpState,
    QualityDecision,
    StationSnapshot,
    snapshot_from_dict,
)
from .modes import RuntimeMode
from .quality import evaluate_quality
from .reason_codes import ReasonCode

__all__ = [
    "AuthorityGateDecision",
    "ControlIntent",
    "PumpState",
    "QualityDecision",
    "ReasonCode",
    "RuntimeMode",
    "StationSnapshot",
    "evaluate_authority",
    "evaluate_quality",
    "snapshot_from_dict",
]
