"""Sprint 10 — Round-trip the JSON topology example shipped under docs/.

The example at ``docs/examples/topology_3node_branch.json`` is the
canonical demonstration of the JSON schema documented in
``docs/topology-json-schema.md``. This test guards against drift
between the documented schema and the actual ``load_network_from_json``
behaviour, and against accidental deletion / rename of the example.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import (
    Network,
    load_network_from_json,
    newton_solve,
)


_EXAMPLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "topology_3node_branch.json"
)


def test_example_topology_file_exists() -> None:
    assert _EXAMPLE_PATH.is_file(), (
        f"missing docs example {_EXAMPLE_PATH}; the JSON loader docs in "
        "docs/topology-json-schema.md reference this file."
    )


def test_example_topology_loads_into_network() -> None:
    network = load_network_from_json(_EXAMPLE_PATH)
    assert isinstance(network, Network)
    assert network.num_nodes == 3
    assert network.num_edges == 2
    # One reservoir, two free nodes.
    assert int(network.fixed_head_mask.sum().item()) == 1
    # All edges are pipes (no pump in this example).
    assert bool(network.pipe_mask.all().item())
    assert not bool(network.pump_mask.any().item())


def test_example_topology_solves_to_a_finite_steady_state() -> None:
    """The example must be a well-posed network the dPHM solver accepts.

    This is the strongest single check we can run without claiming
    field accuracy: parse the JSON, hand it to the existing Newton
    solver (both Jacobian modes), and require convergence to a finite
    residual norm with identical solutions.
    """
    network = load_network_from_json(_EXAMPLE_PATH)

    res_auto = newton_solve(
        network, max_iterations=200, tol=1e-9, jacobian_mode="autograd"
    )
    res_ana = newton_solve(
        network, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert res_auto.converged
    assert res_ana.converged
    assert torch.allclose(res_auto.heads, res_ana.heads, atol=1e-7, rtol=0.0)
    assert torch.allclose(res_auto.flows, res_ana.flows, atol=1e-7, rtol=0.0)


def test_example_topology_in_memory_dict_path_matches_file_path() -> None:
    """Loader accepts both dict and path — both must produce the same Network."""
    import json

    with _EXAMPLE_PATH.open("r", encoding="utf-8") as f:
        doc = json.load(f)
    net_path = load_network_from_json(_EXAMPLE_PATH)
    net_dict = load_network_from_json(doc)

    assert torch.equal(net_path.edge_index, net_dict.edge_index)
    assert torch.equal(net_path.demands, net_dict.demands)
    assert torch.equal(net_path.fixed_head_mask, net_dict.fixed_head_mask)
    assert torch.equal(net_path.fixed_head_values, net_dict.fixed_head_values)
    assert torch.equal(net_path.lengths, net_dict.lengths)
    assert torch.equal(net_path.diameters, net_dict.diameters)
    assert torch.equal(net_path.c_factors, net_dict.c_factors)
