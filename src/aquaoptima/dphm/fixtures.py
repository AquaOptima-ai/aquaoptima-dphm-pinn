"""Synthetic ``Network`` fixtures for unit-testing the dPHM solver.

These networks are deliberately tiny, hand-traceable, and mass-balanced
(``sum(demands) == 0``). They are the only "ground truth" the Sprint 2
solver tests rely on — real Yilan / EPANET networks are out of scope.

All flow rates are in m^3/s, lengths and diameters in metres, demands in
m^3/s (positive = consumption at the node, negative = supply).
"""

from __future__ import annotations

import torch

from .network import Network


def _pipe_only_kwargs(num_edges: int) -> dict[str, torch.Tensor]:
    return dict(
        pipe_mask=torch.ones(num_edges, dtype=torch.bool),
        pump_mask=torch.zeros(num_edges, dtype=torch.bool),
        pump_coeffs=torch.zeros((num_edges, 3)),
        pump_speeds=torch.zeros(num_edges),
    )


def make_branch_network() -> Network:
    """Reservoir feeding two demand nodes through a Y-junction.

    Topology::

        0 (reservoir, fixed head 100 m)
        |
        +-- pipe 0 --> 1 (junction)
                      |
                      +-- pipe 1 --> 2 (demand 0.03 m^3/s)
                      +-- pipe 2 --> 3 (demand 0.02 m^3/s)
    """
    edge_index = torch.tensor(
        [[0, 1, 1], [1, 2, 3]],
        dtype=torch.long,
    )
    return Network(
        edge_index=edge_index,
        num_nodes=4,
        lengths=torch.tensor([200.0, 150.0, 180.0]),
        diameters=torch.tensor([0.20, 0.10, 0.10]),
        c_factors=torch.tensor([130.0, 130.0, 130.0]),
        demands=torch.tensor([-0.05, 0.0, 0.03, 0.02]),
        fixed_head_mask=torch.tensor([True, False, False, False]),
        fixed_head_values=torch.tensor([100.0, 0.0, 0.0, 0.0]),
        **_pipe_only_kwargs(3),
    )


def make_single_loop_network() -> Network:
    """One reservoir feeds a triangular loop with a single demand at node 2.

    Topology::

        0 (reservoir, fixed head 100 m)
        |
        +-- pipe 0 --> 1
                      |
                      +-- pipe 1 --> 2 (demand 0.04 m^3/s)
                      ^
                      |
        pipe 2: 1 -> 3 -> 2 closes the loop via node 3.
    """
    edge_index = torch.tensor(
        [
            [0, 1, 1, 3],
            [1, 2, 3, 2],
        ],
        dtype=torch.long,
    )
    return Network(
        edge_index=edge_index,
        num_nodes=4,
        lengths=torch.tensor([100.0, 200.0, 150.0, 150.0]),
        diameters=torch.tensor([0.25, 0.15, 0.12, 0.12]),
        c_factors=torch.tensor([130.0, 130.0, 130.0, 130.0]),
        demands=torch.tensor([-0.04, 0.0, 0.04, 0.0]),
        fixed_head_mask=torch.tensor([True, False, False, False]),
        fixed_head_values=torch.tensor([100.0, 0.0, 0.0, 0.0]),
        **_pipe_only_kwargs(4),
    )


def make_pump_network() -> Network:
    """Suction reservoir, in-line pump, delivery pipe to a demand node.

    Topology::

        0 (suction reservoir, fixed head 5 m)
        |
        +-- pump 0 --> 1
                      |
                      +-- pipe 1 --> 2 (demand 0.02 m^3/s)

    Pump curve: ``H(Q, s) = 40 s^2 - 800 Q^2`` (a0=40 m shut-off,
    a2=-800 s^2/m^5 quadratic droop), nominal speed s=1.0.
    """
    edge_index = torch.tensor(
        [[0, 1], [1, 2]],
        dtype=torch.long,
    )
    pipe_mask = torch.tensor([False, True])
    pump_mask = torch.tensor([True, False])
    return Network(
        edge_index=edge_index,
        num_nodes=3,
        pipe_mask=pipe_mask,
        pump_mask=pump_mask,
        # The pump row stores a benign placeholder; pipe row carries real values.
        lengths=torch.tensor([1.0, 120.0]),
        diameters=torch.tensor([0.10, 0.10]),
        c_factors=torch.tensor([130.0, 130.0]),
        pump_coeffs=torch.tensor(
            [
                [40.0, 0.0, -800.0],
                [0.0, 0.0, 0.0],
            ]
        ),
        pump_speeds=torch.tensor([1.0, 0.0]),
        demands=torch.tensor([-0.02, 0.0, 0.02]),
        fixed_head_mask=torch.tensor([True, False, False]),
        fixed_head_values=torch.tensor([5.0, 0.0, 0.0]),
    )
