"""``Network`` dataclass — topology + per-edge/per-node parameters.

A ``Network`` is the structured input the dPHM solver consumes. It carries:

* ``edge_index`` with the PyG ``[2, E]`` (source, target) convention.
* Per-edge masks (``pipe_mask`` / ``pump_mask``) that partition the edge
  set; every edge must belong to exactly one class.
* Per-edge pipe parameters (``lengths``, ``diameters``, ``c_factors``)
  required by :func:`aquaoptima.dphm.hazen_williams.hazen_williams_head_loss`.
* Per-edge pump parameters (``pump_coeffs`` shape ``[E, 3]``,
  ``pump_speeds`` shape ``[E]``) consumed by
  :func:`aquaoptima.dphm.pump_affinity.pump_head_gain`.
* Per-node ``demands`` (positive = consumption, negative = supply).
* A per-node ``fixed_head_mask`` and matching ``fixed_head_values`` that
  pin reservoir / boundary heads to known values.

Validation is strict at construction time: any shape, range, or mask
inconsistency raises :class:`ValueError`. Downstream solver code can then
assume invariants without re-checking them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import torch


@dataclass
class Network:
    """Topology + per-edge / per-node parameters for a dPHM network.

    A ``Network`` is the structured input the dPHM solver consumes.
    Construction is strict: any shape, range, or mask inconsistency
    raises :class:`ValueError`, so every downstream consumer (solver,
    residual assembly, training loop) can assume invariants without
    re-checking them. See the module-level docstring for the full
    field-by-field contract.
    """

    edge_index: torch.Tensor
    num_nodes: int
    pipe_mask: torch.Tensor
    pump_mask: torch.Tensor
    lengths: torch.Tensor
    diameters: torch.Tensor
    c_factors: torch.Tensor
    pump_coeffs: torch.Tensor
    pump_speeds: torch.Tensor
    demands: torch.Tensor
    fixed_head_mask: torch.Tensor
    fixed_head_values: torch.Tensor

    free_node_indices: torch.Tensor = field(init=False)
    pipe_edge_indices: torch.Tensor = field(init=False)
    pump_edge_indices: torch.Tensor = field(init=False)

    def __post_init__(self) -> None:
        ei = self.edge_index
        if ei.dim() != 2 or ei.shape[0] != 2:
            raise ValueError(
                f"edge_index must have shape [2, E], got {tuple(ei.shape)}"
            )
        if ei.dtype not in (torch.int32, torch.int64):
            ei = ei.long()
            self.edge_index = ei

        if self.num_nodes <= 0:
            raise ValueError(f"num_nodes must be positive, got {self.num_nodes}")

        E = ei.shape[1]
        if E and (int(ei.max().item()) >= self.num_nodes or int(ei.min().item()) < 0):
            raise ValueError(
                "edge_index references a node id outside [0, num_nodes); "
                f"min={int(ei.min().item())}, max={int(ei.max().item())}, "
                f"num_nodes={self.num_nodes}"
            )

        self._check_edge_vector("pipe_mask", self.pipe_mask, E, dtype=torch.bool)
        self._check_edge_vector("pump_mask", self.pump_mask, E, dtype=torch.bool)

        overlap = self.pipe_mask & self.pump_mask
        if bool(overlap.any().item()):
            raise ValueError(
                f"pipe_mask and pump_mask overlap on edges {torch.nonzero(overlap).flatten().tolist()}"
            )
        unclassified = ~(self.pipe_mask | self.pump_mask)
        if bool(unclassified.any().item()):
            raise ValueError(
                f"unclassified edges (neither pipe nor pump): "
                f"{torch.nonzero(unclassified).flatten().tolist()}"
            )

        self._check_edge_vector("lengths", self.lengths, E)
        self._check_edge_vector("diameters", self.diameters, E)
        self._check_edge_vector("c_factors", self.c_factors, E)
        self._check_edge_vector("pump_speeds", self.pump_speeds, E)

        # Pipe parameters must be positive on pipe edges; we cannot enforce
        # this for non-pipe rows because callers may store placeholders there.
        for name, value in (
            ("lengths", self.lengths),
            ("diameters", self.diameters),
            ("c_factors", self.c_factors),
        ):
            pipe_vals = value[self.pipe_mask]
            if pipe_vals.numel() and bool((pipe_vals <= 0).any().item()):
                raise ValueError(
                    f"{name} must be strictly positive on pipe edges, got {value.tolist()}"
                )

        if self.pump_coeffs.dim() != 2 or self.pump_coeffs.shape != (E, 3):
            raise ValueError(
                f"pump_coeffs must have shape [{E}, 3], got {tuple(self.pump_coeffs.shape)}"
            )

        if self.demands.shape != (self.num_nodes,):
            raise ValueError(
                f"demands must have shape [{self.num_nodes}], got {tuple(self.demands.shape)}"
            )

        if self.fixed_head_mask.dtype != torch.bool or self.fixed_head_mask.shape != (
            self.num_nodes,
        ):
            raise ValueError(
                f"fixed_head_mask must be bool[{self.num_nodes}], got "
                f"dtype={self.fixed_head_mask.dtype}, shape={tuple(self.fixed_head_mask.shape)}"
            )
        if self.fixed_head_values.shape != (self.num_nodes,):
            raise ValueError(
                f"fixed_head_values must have shape [{self.num_nodes}], got "
                f"{tuple(self.fixed_head_values.shape)}"
            )

        self.free_node_indices = torch.nonzero(~self.fixed_head_mask).flatten()
        self.pipe_edge_indices = torch.nonzero(self.pipe_mask).flatten()
        self.pump_edge_indices = torch.nonzero(self.pump_mask).flatten()

    # --- convenience accessors -----------------------------------------

    @property
    def num_edges(self) -> int:
        return int(self.edge_index.shape[1])

    @property
    def num_fixed_heads(self) -> int:
        return int(self.fixed_head_mask.sum().item())

    @property
    def num_free_nodes(self) -> int:
        return self.num_nodes - self.num_fixed_heads

    # --- helpers --------------------------------------------------------

    @staticmethod
    def _check_edge_vector(
        name: str, value: torch.Tensor, E: int, dtype: torch.dtype | None = None
    ) -> None:
        if value.shape != (E,):
            raise ValueError(
                f"{name} must have shape [{E}], got {tuple(value.shape)}"
            )
        if dtype is not None and value.dtype != dtype:
            raise ValueError(f"{name} must be {dtype}, got {value.dtype}")
