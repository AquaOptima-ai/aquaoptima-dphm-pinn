"""Projections from Phase 1 telemetry CSV text into SDK shadow replay.

The Sprint 42 SDK does NOT absorb ``aquaoptima.dphm.shadow_replay``
runtime logic (no Network-keyed validation, no unit-conversion table,
no timestamp staleness check). The projection helper here is a thin
canonical *shape* mapper: it parses an offline CSV body and projects
the cells through an SDK :class:`TelemetryTagMap` into the canonical
SDK :class:`ShadowReplayDataset` shape.

This helper is suitable for read-only audit / review contexts where
the consumer only needs the canonical projection. Production replay
construction continues to use the Phase 1 runtime loader.
"""

from __future__ import annotations

import csv
import io
import math

from ..base.envelope import ContractError
from .replay import ShadowReplayDataset, ShadowReplayDiagnostics, ShadowReplayFrame
from .tag_map import TelemetryTagMap


def project_phase1_replay_csv_text(
    csv_text: str,
    tag_map: TelemetryTagMap,
    *,
    timestamp_key: str = "timestamp",
) -> ShadowReplayDataset:
    """Project an offline CSV body + SDK tag-map into a dataset.

    The CSV must have a header row containing ``timestamp_key`` and
    one column per SDK tag. Every cell is parsed as a float for
    numeric axes; empty cells are skipped (no diagnostic). This
    helper does NOT perform unit conversion — the SDK projection
    represents what the caller wrote, and the Phase 1 runtime
    continues to be the authority for runtime numerical behavior.
    """

    if not isinstance(csv_text, str):
        raise ContractError(
            f"project_phase1_replay_csv_text requires a string body, got "
            f"{type(csv_text).__name__}"
        )
    if not isinstance(tag_map, TelemetryTagMap):
        raise ContractError(
            f"project_phase1_replay_csv_text requires a TelemetryTagMap, got "
            f"{type(tag_map).__name__}"
        )
    if csv_text == "":
        raise ContractError(
            "project_phase1_replay_csv_text: csv_text is empty"
        )

    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        raise ContractError(
            "project_phase1_replay_csv_text: CSV has no header row"
        )
    if timestamp_key not in reader.fieldnames:
        raise ContractError(
            f"project_phase1_replay_csv_text: timestamp column "
            f"{timestamp_key!r} not in CSV header "
            f"{list(reader.fieldnames)!r}"
        )

    tag_index = {spec.tag: spec for spec in tag_map.tags}
    warnings: list[str] = []

    frames: list[ShadowReplayFrame] = []
    for row_index, raw_row in enumerate(reader):
        timestamp = raw_row.get(timestamp_key)
        if not timestamp:
            warnings.append(
                f"row[{row_index}]: missing timestamp value; row skipped"
            )
            continue
        per_axis: dict[str, dict[int, float]] = {}
        for column, cell in raw_row.items():
            if column == timestamp_key or column is None:
                continue
            if cell is None or cell == "":
                continue
            spec = tag_index.get(column)
            if spec is None:
                warnings.append(
                    f"row[{row_index}]: column {column!r} has no entry in "
                    f"tag_map; cell ignored"
                )
                continue
            try:
                numeric = float(cell)
            except ValueError:
                warnings.append(
                    f"row[{row_index}]: tag {spec.tag!r} cell {cell!r} is "
                    f"not parseable as float; cell ignored"
                )
                continue
            if math.isnan(numeric) or math.isinf(numeric):
                warnings.append(
                    f"row[{row_index}]: tag {spec.tag!r} cell {cell!r} is "
                    f"non-finite; cell ignored"
                )
                continue
            per_axis.setdefault(spec.axis, {})[spec.target_id] = numeric
        frames.append(
            ShadowReplayFrame(timestamp=str(timestamp), values=per_axis)
        )

    return ShadowReplayDataset(
        frames=tuple(frames),
        diagnostics=ShadowReplayDiagnostics(
            warnings=tuple(warnings),
            errors=(),
        ),
    )
