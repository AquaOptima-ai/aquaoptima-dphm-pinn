"""Tests for the synthetic topology fixtures.

Fixtures produce small, hand-checkable networks the solver tests can use.
They must return validated ``Network`` instances (so any topology bug
fails fast) and they must obey global mass conservation
(``sum(demands) == 0``) — otherwise no solver can converge.
"""

import torch

from aquaoptima.dphm.network import Network
from aquaoptima.dphm.fixtures import (
    make_branch_network,
    make_single_loop_network,
    make_pump_network,
)


def _is_mass_balanced(net: Network) -> bool:
    return bool(torch.isclose(net.demands.sum(), torch.tensor(0.0), atol=1e-6))


def test_branch_network_is_valid_network():
    net = make_branch_network()
    assert isinstance(net, Network)
    assert net.num_edges >= 2
    assert net.num_fixed_heads >= 1


def test_branch_network_mass_balanced():
    net = make_branch_network()
    assert _is_mass_balanced(net)


def test_branch_network_has_no_pumps():
    net = make_branch_network()
    assert bool(net.pipe_mask.all().item())
    assert not bool(net.pump_mask.any().item())


def test_single_loop_network_is_valid_network():
    net = make_single_loop_network()
    assert isinstance(net, Network)
    # A single loop needs at least three pipes around a cycle.
    assert net.num_edges >= 3


def test_single_loop_network_mass_balanced():
    net = make_single_loop_network()
    assert _is_mass_balanced(net)


def test_pump_network_has_pump_edge():
    net = make_pump_network()
    assert isinstance(net, Network)
    assert int(net.pump_mask.sum().item()) >= 1
    pump_idx = net.pump_edge_indices[0].item()
    coeffs = net.pump_coeffs[pump_idx]
    # Shut-off head (a0) must be positive for the pump to do real work.
    assert coeffs[0].item() > 0.0


def test_pump_network_mass_balanced():
    net = make_pump_network()
    assert _is_mass_balanced(net)


def test_fixture_edge_index_dtype_is_long():
    for net in (make_branch_network(), make_single_loop_network(), make_pump_network()):
        assert net.edge_index.dtype == torch.long
