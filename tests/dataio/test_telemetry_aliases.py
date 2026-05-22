"""Tests for the canonical telemetry abstraction and SCADA back-compat aliases.

Sprint 4.5 generalises the data path so that SCADA is one possible
telemetry source (alongside PLC, PAC, historian, CSV, MQTT). The
canonical types are ``TelemetrySeries`` and
``generate_synthetic_telemetry``; the older ``ScadaSeries`` and
``generate_synthetic_scada`` symbols must remain importable and
interchangeable so Sprint 1-4 callers keep working.
"""

from __future__ import annotations

import torch

from aquaoptima.dataio import (
    ScadaSeries,
    TelemetrySeries,
    WindowDataset,
    generate_synthetic_scada,
    generate_synthetic_telemetry,
)
from aquaoptima.dphm import make_branch_network


def test_telemetry_series_is_scada_series_alias() -> None:
    # Backward compatibility: ScadaSeries must be the same type as
    # TelemetrySeries so existing isinstance checks keep working.
    assert ScadaSeries is TelemetrySeries


def test_generate_synthetic_telemetry_returns_correct_shapes() -> None:
    net = make_branch_network()
    series = generate_synthetic_telemetry(net, num_steps=64, seed=0)

    assert isinstance(series, TelemetrySeries)
    assert series.pressure.shape == (64, net.num_nodes)
    assert series.flow.shape == (64, net.num_edges)
    assert series.demand.shape == (64, net.num_nodes)


def test_generate_synthetic_telemetry_seeded_reproducible() -> None:
    net = make_branch_network()
    s1 = generate_synthetic_telemetry(net, num_steps=32, seed=99)
    s2 = generate_synthetic_telemetry(net, num_steps=32, seed=99)
    assert torch.equal(s1.pressure, s2.pressure)
    assert torch.equal(s1.flow, s2.flow)
    assert torch.equal(s1.demand, s2.demand)


def test_scada_alias_matches_telemetry_generator() -> None:
    # The legacy alias must produce identical output to the canonical
    # generator so existing fixtures and golden files do not drift.
    net = make_branch_network()
    s_scada = generate_synthetic_scada(net, num_steps=40, seed=7)
    s_telem = generate_synthetic_telemetry(net, num_steps=40, seed=7)
    assert torch.equal(s_scada.pressure, s_telem.pressure)
    assert torch.equal(s_scada.flow, s_telem.flow)
    assert torch.equal(s_scada.demand, s_telem.demand)


def test_window_dataset_accepts_telemetry_series() -> None:
    net = make_branch_network()
    series = generate_synthetic_telemetry(net, num_steps=64, seed=0)
    ds = WindowDataset(series, window=32)
    assert len(ds) == 32
    sample = ds[0]
    assert sample["x_seq"].shape == (32, net.num_nodes, ds.node_feature_dim)
    assert sample["target_pressure"].shape == (net.num_nodes,)


def test_telemetry_series_quality_optional() -> None:
    # quality may be omitted (default None) or attached as a dict of
    # per-channel quality flag tensors. The dataclass should accept both.
    net = make_branch_network()
    series = generate_synthetic_telemetry(net, num_steps=33, seed=1)
    assert series.quality is None

    custom_quality = {
        "pressure": torch.zeros(33, net.num_nodes, dtype=torch.int8),
    }
    series_with_q = TelemetrySeries(
        pressure=series.pressure,
        flow=series.flow,
        demand=series.demand,
        quality=custom_quality,
    )
    assert series_with_q.quality is not None
    assert "pressure" in series_with_q.quality
