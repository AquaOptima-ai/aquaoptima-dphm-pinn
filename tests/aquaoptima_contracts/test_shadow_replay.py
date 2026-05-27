"""TDD — shadow replay SDK projections (Sprint 42).

Acceptance: SDK ``ShadowReplayFrame`` / ``ShadowReplayDataset`` /
``ShadowReplayDiagnostics`` types capture the *shape* of the Phase 1
artifact. The SDK does NOT absorb ``load_shadow_replay_csv`` runtime
logic — but it can validate / represent a canonical dataset shape
projected from the Phase 1 fixture telemetry.csv.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aquaoptima_contracts import (
    ContractError,
    ShadowReplayDataset,
    ShadowReplayDiagnostics,
    ShadowReplayFrame,
    TelemetryTagMap,
    dump_canonical_json,
    load_canonical_json,
)
from aquaoptima_contracts.telemetry.adapters import (
    project_phase1_tag_map_document,
)
from aquaoptima_contracts.telemetry.replay_adapters import (
    project_phase1_replay_csv_text,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SDK_FIXTURE_DIR = (
    REPO_ROOT / "src" / "aquaoptima_contracts" / "fixtures" / "phase1_shadow"
)


def test_minimal_frame_round_trip() -> None:
    frame = ShadowReplayFrame(timestamp="0.0", values={"node_pressure": {0: 35.0}})
    raw = dump_canonical_json(frame)
    decoded = load_canonical_json(raw)
    assert decoded["timestamp"] == "0.0"
    assert decoded["values"]["node_pressure"]["0"] == 35.0
    restored = ShadowReplayFrame.from_dict(decoded)
    assert restored == frame


def test_frame_rejects_unknown_axis() -> None:
    with pytest.raises(ContractError):
        ShadowReplayFrame(
            timestamp="0.0",
            values={"not_an_axis": {0: 1.0}},
        )


def test_frame_rejects_negative_target_id() -> None:
    with pytest.raises(ContractError):
        ShadowReplayFrame(
            timestamp="0.0",
            values={"node_pressure": {-1: 1.0}},
        )


def test_frame_rejects_non_numeric_value_for_numeric_axis() -> None:
    with pytest.raises(ContractError):
        ShadowReplayFrame(
            timestamp="0.0",
            values={"node_pressure": {0: "thirty-five"}},  # type: ignore[dict-item]
        )


def test_frame_empty_timestamp_rejected() -> None:
    with pytest.raises(ContractError):
        ShadowReplayFrame(timestamp="", values={"node_pressure": {0: 35.0}})


def test_dataset_round_trip_with_diagnostics() -> None:
    frame = ShadowReplayFrame(
        timestamp="0.0",
        values={"node_pressure": {0: 35.0}, "edge_flow": {1: 0.025}},
    )
    diagnostics = ShadowReplayDiagnostics(
        warnings=("note",),
        errors=(),
    )
    dataset = ShadowReplayDataset(
        frames=(frame,),
        diagnostics=diagnostics,
    )
    raw = dump_canonical_json(dataset)
    decoded = load_canonical_json(raw)
    restored = ShadowReplayDataset.from_dict(decoded)
    assert restored == dataset


def test_dataset_rejects_non_tuple_frames() -> None:
    with pytest.raises(ContractError):
        ShadowReplayDataset(
            frames=[
                ShadowReplayFrame(timestamp="0.0", values={"node_pressure": {0: 35.0}})
            ],  # type: ignore[arg-type]
        )


def test_project_phase1_replay_csv_text_matches_fixture() -> None:
    tag_map_doc = load_canonical_json(
        (SDK_FIXTURE_DIR / "tag_map.json").read_text(encoding="utf-8")
    )
    tag_map = project_phase1_tag_map_document(tag_map_doc)
    csv_text = (SDK_FIXTURE_DIR / "telemetry.csv").read_text(encoding="utf-8")
    dataset = project_phase1_replay_csv_text(csv_text, tag_map)
    assert isinstance(dataset, ShadowReplayDataset)
    assert len(dataset.frames) == 3
    first = dataset.frames[0]
    assert first.values["node_pressure"][0] == 35.0
    assert first.values["edge_flow"][0] == 0.045
    assert dataset.diagnostics.errors == ()


def test_project_phase1_replay_csv_text_rejects_empty_csv() -> None:
    with pytest.raises(ContractError):
        project_phase1_replay_csv_text("", TelemetryTagMap())


def test_project_phase1_replay_csv_text_rejects_missing_timestamp_column() -> None:
    with pytest.raises(ContractError):
        project_phase1_replay_csv_text("PT_J1\n1.0\n", TelemetryTagMap())
