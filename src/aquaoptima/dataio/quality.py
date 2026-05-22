"""Quality flags for telemetry samples.

Every telemetry source (PLC, PAC, SCADA historian, MQTT broker, CSV
import) eventually surfaces samples that are *not* trustworthy: a
disconnected sensor, a flatline due to a frozen scan, an out-of-range
value, an operator override. Sprint 4.5 introduces a single canonical
vocabulary so downstream code can reason about sample quality without
each adapter inventing its own status enum.

The Sprint 4.5 deliverable is the vocabulary only. Adapters and the
``WindowDataset`` will start consuming :class:`QualityFlag` from Sprint
5 onward, when the physics-consistent training loop also begins to
gate the data-loss term on quality.
"""

from __future__ import annotations

from enum import Enum


class QualityFlag(str, Enum):
    """Per-sample telemetry quality classification.

    Members
    -------
    GOOD
        Sample is trustworthy and may be used for both supervised loss
        and physics-consistency residual evaluation.
    MISSING
        No value was received (gap in the stream, dropped packet).
    STALE
        The value has not changed for longer than the source's expected
        update interval — typically a stuck transmitter.
    FLATLINE
        Indistinguishable from ``STALE`` from the data side but tagged
        by upstream signal-processing rather than time-based logic.
    OUTLIER
        Value is finite but outside physically plausible bounds for the
        tag's :class:`~aquaoptima.dataio.tag_map.TagKind`.
    BAD_QUALITY
        Upstream protocol-level bad-quality flag (OPC-UA / OPC-DA /
        Modbus exception code, etc.).
    MANUAL_OVERRIDE
        An operator forced this value via SCADA or HMI; it does not
        reflect the field measurement and should not be used for
        physics training.
    """

    GOOD = "good"
    MISSING = "missing"
    STALE = "stale"
    FLATLINE = "flatline"
    OUTLIER = "outlier"
    BAD_QUALITY = "bad_quality"
    MANUAL_OVERRIDE = "manual_override"


def is_usable(flag: QualityFlag) -> bool:
    """Return ``True`` iff a sample with this flag is safe to train on.

    The single-member allowlist is deliberate: any non-``GOOD`` flag
    indicates the value is suspect for at least one purpose (training,
    physics evaluation, or both). Callers that need a more permissive
    policy should branch on the specific :class:`QualityFlag` values.
    """
    return flag is QualityFlag.GOOD


__all__ = ["QualityFlag", "is_usable"]
