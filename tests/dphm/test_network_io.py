"""Tests for Sprint 8 source-agnostic JSON topology loader.

The loader consumes an EPANET-style topology description in JSON form
(either a file path or an in-memory dict) and returns the existing
:class:`aquaoptima.dphm.Network` dataclass — same downstream consumers
as the hand-built fixtures (``make_branch_network`` et al.). The
loader is deliberately source-agnostic: it does **not** carry
PLC/PAC/SCADA tag concepts. Field-tag bindings remain the job of
``aquaoptima.dataio.tag_map``.

Schema (canonical form)::

    {
      "nodes": [
        {"id": "n0", "demand": -0.05, "fixed_head": true,
         "head_value": 100.0, "elevation": 0.0},
        ...
      ],
      "edges": [
        {"id": "p0", "source": "n0", "target": "n1", "kind": "pipe",
         "length": 200.0, "diameter": 0.20, "c_factor": 130.0},
        {"id": "pu0", "source": "n5", "target": "n6", "kind": "pump",
         "pump_coeffs": [40.0, 0.0, -800.0], "pump_speed": 1.0}
      ]
    }
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import Network
from aquaoptima.dphm.network_io import load_network_from_json


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def _branch_doc() -> dict:
    """Source-agnostic topology equivalent to ``make_branch_network``."""
    return {
        "nodes": [
            {"id": "n0", "demand": -0.05, "fixed_head": True, "head_value": 100.0},
            {"id": "n1", "demand": 0.0, "fixed_head": False},
            {"id": "n2", "demand": 0.03, "fixed_head": False},
            {"id": "n3", "demand": 0.02, "fixed_head": False},
        ],
        "edges": [
            {"id": "p0", "source": "n0", "target": "n1", "kind": "pipe",
             "length": 200.0, "diameter": 0.20, "c_factor": 130.0},
            {"id": "p1", "source": "n1", "target": "n2", "kind": "pipe",
             "length": 150.0, "diameter": 0.10, "c_factor": 130.0},
            {"id": "p2", "source": "n1", "target": "n3", "kind": "pipe",
             "length": 180.0, "diameter": 0.10, "c_factor": 130.0},
        ],
    }


def _pump_doc() -> dict:
    return {
        "nodes": [
            {"id": "n0", "demand": -0.02, "fixed_head": True, "head_value": 5.0},
            {"id": "n1", "demand": 0.0, "fixed_head": False},
            {"id": "n2", "demand": 0.02, "fixed_head": False},
        ],
        "edges": [
            {"id": "pu0", "source": "n0", "target": "n1", "kind": "pump",
             "pump_coeffs": [40.0, 0.0, -800.0], "pump_speed": 1.0},
            {"id": "p1", "source": "n1", "target": "n2", "kind": "pipe",
             "length": 120.0, "diameter": 0.10, "c_factor": 130.0},
        ],
    }


def test_load_from_dict_returns_network_with_correct_shape() -> None:
    net = load_network_from_json(_branch_doc())
    assert isinstance(net, Network)
    assert net.num_nodes == 4
    assert net.num_edges == 3
    assert net.num_fixed_heads == 1


def test_load_from_dict_preserves_node_ordering_and_demands() -> None:
    net = load_network_from_json(_branch_doc())
    assert torch.allclose(
        net.demands, torch.tensor([-0.05, 0.0, 0.03, 0.02])
    )
    assert net.fixed_head_mask.tolist() == [True, False, False, False]
    assert torch.allclose(
        net.fixed_head_values, torch.tensor([100.0, 0.0, 0.0, 0.0])
    )


def test_load_from_dict_pipe_parameters() -> None:
    net = load_network_from_json(_branch_doc())
    assert net.pipe_mask.tolist() == [True, True, True]
    assert net.pump_mask.tolist() == [False, False, False]
    assert torch.allclose(net.lengths, torch.tensor([200.0, 150.0, 180.0]))
    assert torch.allclose(net.diameters, torch.tensor([0.20, 0.10, 0.10]))
    assert torch.allclose(net.c_factors, torch.tensor([130.0, 130.0, 130.0]))


def test_load_pump_doc_classifies_pump_edge() -> None:
    net = load_network_from_json(_pump_doc())
    assert net.pump_mask.tolist() == [True, False]
    assert net.pipe_mask.tolist() == [False, True]
    # Pump row carries coefficients; pipe row carries pipe parameters.
    assert torch.allclose(
        net.pump_coeffs[0], torch.tensor([40.0, 0.0, -800.0])
    )
    assert float(net.pump_speeds[0].item()) == pytest.approx(1.0)


def test_load_from_path_reads_file(tmp_path: Path) -> None:
    doc = _branch_doc()
    p = tmp_path / "branch.json"
    p.write_text(json.dumps(doc))
    net = load_network_from_json(p)
    assert net.num_nodes == 4
    assert net.num_edges == 3


def test_load_from_path_accepts_str(tmp_path: Path) -> None:
    doc = _branch_doc()
    p = tmp_path / "branch.json"
    p.write_text(json.dumps(doc))
    net = load_network_from_json(str(p))
    assert isinstance(net, Network)


# ---------------------------------------------------------------------------
# round-trip: hand-built fixture <-> JSON-loaded fixture produce equal Networks
# ---------------------------------------------------------------------------


def test_loaded_branch_matches_hand_built_fixture() -> None:
    from aquaoptima.dphm import make_branch_network

    loaded = load_network_from_json(_branch_doc())
    fixture = make_branch_network()
    assert torch.equal(loaded.edge_index, fixture.edge_index)
    assert loaded.num_nodes == fixture.num_nodes
    assert torch.allclose(loaded.demands, fixture.demands)
    assert torch.equal(loaded.fixed_head_mask, fixture.fixed_head_mask)
    assert torch.allclose(loaded.fixed_head_values, fixture.fixed_head_values)
    assert torch.allclose(loaded.lengths, fixture.lengths)
    assert torch.allclose(loaded.diameters, fixture.diameters)
    assert torch.allclose(loaded.c_factors, fixture.c_factors)
    assert torch.equal(loaded.pipe_mask, fixture.pipe_mask)


# ---------------------------------------------------------------------------
# error paths — each invalid case must raise ValueError with a useful message
# ---------------------------------------------------------------------------


def test_missing_nodes_key_raises() -> None:
    with pytest.raises(ValueError, match="nodes"):
        load_network_from_json({"edges": []})


def test_missing_edges_key_raises() -> None:
    with pytest.raises(ValueError, match="edges"):
        load_network_from_json({"nodes": []})


def test_duplicate_node_ids_raise() -> None:
    doc = _branch_doc()
    doc["nodes"][1]["id"] = "n0"  # collide with node 0
    with pytest.raises(ValueError, match="duplicate"):
        load_network_from_json(doc)


def test_duplicate_edge_ids_raise() -> None:
    doc = _branch_doc()
    doc["edges"][1]["id"] = "p0"
    with pytest.raises(ValueError, match="duplicate"):
        load_network_from_json(doc)


def test_edge_referencing_unknown_node_raises() -> None:
    doc = _branch_doc()
    doc["edges"][0]["target"] = "ghost"
    with pytest.raises(ValueError, match="unknown"):
        load_network_from_json(doc)


def test_nonpositive_pipe_length_raises() -> None:
    doc = _branch_doc()
    doc["edges"][0]["length"] = 0.0
    with pytest.raises(ValueError, match="length"):
        load_network_from_json(doc)


def test_nonpositive_pipe_diameter_raises() -> None:
    doc = _branch_doc()
    doc["edges"][0]["diameter"] = -0.1
    with pytest.raises(ValueError, match="diameter"):
        load_network_from_json(doc)


def test_nonpositive_pipe_c_factor_raises() -> None:
    doc = _branch_doc()
    doc["edges"][0]["c_factor"] = 0.0
    with pytest.raises(ValueError, match="c_factor"):
        load_network_from_json(doc)


def test_pump_missing_coeffs_raises() -> None:
    doc = _pump_doc()
    del doc["edges"][0]["pump_coeffs"]
    with pytest.raises(ValueError, match="pump_coeffs"):
        load_network_from_json(doc)


def test_pump_coeffs_wrong_length_raises() -> None:
    doc = _pump_doc()
    doc["edges"][0]["pump_coeffs"] = [40.0, 0.0]
    with pytest.raises(ValueError, match="pump_coeffs"):
        load_network_from_json(doc)


def test_pump_zero_shutoff_head_raises() -> None:
    doc = _pump_doc()
    doc["edges"][0]["pump_coeffs"] = [0.0, 0.0, -800.0]
    with pytest.raises(ValueError, match=r"a0"):
        load_network_from_json(doc)


def test_unknown_edge_kind_raises() -> None:
    doc = _branch_doc()
    doc["edges"][0]["kind"] = "valve"
    with pytest.raises(ValueError, match="kind"):
        load_network_from_json(doc)


def test_no_fixed_head_node_raises() -> None:
    doc = _branch_doc()
    doc["nodes"][0]["fixed_head"] = False
    doc["nodes"][0]["head_value"] = 0.0
    with pytest.raises(ValueError, match="fixed"):
        load_network_from_json(doc)


def test_fixed_head_without_value_raises() -> None:
    doc = _branch_doc()
    del doc["nodes"][0]["head_value"]
    with pytest.raises(ValueError, match="head_value"):
        load_network_from_json(doc)


def test_missing_node_id_raises() -> None:
    doc = _branch_doc()
    del doc["nodes"][0]["id"]
    with pytest.raises(ValueError, match="id"):
        load_network_from_json(doc)


def test_missing_edge_endpoints_raises() -> None:
    doc = _branch_doc()
    del doc["edges"][0]["source"]
    with pytest.raises(ValueError, match="source"):
        load_network_from_json(doc)


def test_empty_edges_raises() -> None:
    doc = _branch_doc()
    doc["edges"] = []
    with pytest.raises(ValueError, match="edges"):
        load_network_from_json(doc)


# ---------------------------------------------------------------------------
# downstream compatibility: a JSON-loaded network feeds the solver
# ---------------------------------------------------------------------------


def test_loaded_network_is_solver_compatible() -> None:
    from aquaoptima.dphm import newton_solve

    net = load_network_from_json(_branch_doc())
    result = newton_solve(net, max_iterations=100, tol=1e-9)
    assert result.converged, f"solver did not converge: {result.reason}"
