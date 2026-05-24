"""Source-agnostic JSON topology loader for the dPHM :class:`Network`.

This module accepts an EPANET-style topology description in JSON form
— either an in-memory ``dict`` or a path to a ``.json`` file — and
returns the existing :class:`aquaoptima.dphm.Network` dataclass. It is
deliberately decoupled from the SCADA/PLC/PAC tag-binding layer in
``aquaoptima.dataio.tag_map``: the loader carries **only** structural
hydraulic topology, never field/tag/site metadata.

Schema (canonical form)
-----------------------

::

    {
      "nodes": [
        {"id": "n0",
         "demand": -0.05,
         "fixed_head": true,
         "head_value": 100.0,
         "elevation": 0.0},
        ...
      ],
      "edges": [
        {"id": "p0",
         "source": "n0",
         "target": "n1",
         "kind": "pipe",
         "length": 200.0,
         "diameter": 0.20,
         "c_factor": 130.0},
        {"id": "pu0",
         "source": "n5",
         "target": "n6",
         "kind": "pump",
         "pump_coeffs": [40.0, 0.0, -800.0],
         "pump_speed": 1.0}
      ]
    }

Field reference
~~~~~~~~~~~~~~~

Node:
    - ``id`` (required, str): stable unique identifier.
    - ``demand`` (optional, float, default 0.0): positive = consumption
      (m^3/s), negative = supply.
    - ``fixed_head`` (optional, bool, default False): True marks a
      reservoir / tank / pressurised boundary.
    - ``head_value`` (required iff ``fixed_head=True``, float): pinned
      hydraulic head in metres.
    - ``elevation`` (optional, float, default 0.0): currently
      informational. Reserved for a future elevation-aware energy
      residual; ignored by the Sprint 2 solver.

Edge:
    - ``id`` (required, str): stable unique identifier.
    - ``source`` (required, str): id of the upstream node.
    - ``target`` (required, str): id of the downstream node.
    - ``kind`` (required, ``"pipe"`` or ``"pump"``).
    - Pipe-only: ``length``, ``diameter``, ``c_factor`` (all > 0).
    - Pump-only: ``pump_coeffs`` (length-3 list ``[a0, a1, a2]`` with
      ``a0 > 0``), ``pump_speed`` (float, default 1.0).

Validation
----------

The loader raises :class:`ValueError` with a descriptive message for:

* missing ``nodes`` or ``edges`` top-level keys, or empty ``edges``;
* duplicate node ids or duplicate edge ids;
* edges referencing unknown node ids;
* nodes missing ``id``;
* fixed-head nodes missing ``head_value``;
* topologies with zero fixed-head nodes (singular hydraulic system);
* edges with unknown ``kind``, missing ``source`` / ``target``;
* pipe edges with non-positive ``length`` / ``diameter`` / ``c_factor``;
* pump edges missing or malformed ``pump_coeffs``, or with
  non-positive shut-off head ``a0``.

The returned :class:`Network` re-runs all
:meth:`Network.__post_init__` checks, so any residual shape /
dimension issue surfaces there.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence, Union

import torch

from .network import Network

_VALID_KINDS = ("pipe", "pump")

PathLike = Union[str, Path]
DocumentLike = Union[PathLike, Mapping[str, Any]]


def _load_document(source: DocumentLike) -> Mapping[str, Any]:
    if isinstance(source, Mapping):
        return source
    if isinstance(source, (str, Path)):
        path = Path(source)
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    raise ValueError(
        f"load_network_from_json expects a path or dict, got {type(source).__name__}"
    )


def _require(doc: Mapping[str, Any], key: str) -> Any:
    if key not in doc:
        raise ValueError(f"topology document is missing required key '{key}'")
    return doc[key]


def _require_field(item: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in item:
        raise ValueError(f"{where} is missing required field '{key}'")
    return item[key]


def load_network_from_json(source: DocumentLike) -> Network:
    """Parse an EPANET-style JSON topology into a :class:`Network`.

    Parameters
    ----------
    source
        Either a path-like (``str`` or :class:`pathlib.Path`) pointing
        at a JSON file, or an already-decoded in-memory ``dict``.

    Returns
    -------
    Network
        The validated dPHM network. Node and edge ordering in the
        returned :class:`Network` matches the order of the input
        ``nodes`` / ``edges`` lists, so ``edge_index`` and the per-edge
        tensors can be lined up against the source document by index.

    Raises
    ------
    ValueError
        If the document is missing required fields, contains duplicate
        ids, references unknown nodes, or carries non-physical
        parameter values. See module docstring for the full list.
    """
    doc = _load_document(source)

    nodes_raw = _require(doc, "nodes")
    edges_raw = _require(doc, "edges")
    if not isinstance(nodes_raw, Sequence):
        raise ValueError("'nodes' must be a list")
    if not isinstance(edges_raw, Sequence):
        raise ValueError("'edges' must be a list")
    if len(edges_raw) == 0:
        raise ValueError("'edges' must contain at least one edge")

    # --- nodes ----------------------------------------------------------
    node_ids: list[str] = []
    demands: list[float] = []
    fixed_mask: list[bool] = []
    fixed_vals: list[float] = []

    seen_node_ids: set[str] = set()
    for i, node in enumerate(nodes_raw):
        if not isinstance(node, Mapping):
            raise ValueError(f"nodes[{i}] must be an object, got {type(node).__name__}")
        node_id = _require_field(node, "id", where=f"nodes[{i}]")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError(f"nodes[{i}].id must be a non-empty string")
        if node_id in seen_node_ids:
            raise ValueError(f"duplicate node id {node_id!r}")
        seen_node_ids.add(node_id)
        node_ids.append(node_id)

        demand = float(node.get("demand", 0.0))
        demands.append(demand)

        is_fixed = bool(node.get("fixed_head", False))
        fixed_mask.append(is_fixed)
        if is_fixed:
            if "head_value" not in node:
                raise ValueError(
                    f"node {node_id!r} has fixed_head=True but no 'head_value'"
                )
            fixed_vals.append(float(node["head_value"]))
        else:
            fixed_vals.append(0.0)

    if not any(fixed_mask):
        raise ValueError(
            "topology must contain at least one fixed-head node "
            "(reservoir / tank / pressurised boundary); none found"
        )

    id_to_index = {nid: idx for idx, nid in enumerate(node_ids)}
    N = len(node_ids)

    # --- edges ----------------------------------------------------------
    E = len(edges_raw)
    src_idx: list[int] = []
    dst_idx: list[int] = []
    pipe_mask: list[bool] = []
    pump_mask: list[bool] = []
    lengths: list[float] = []
    diameters: list[float] = []
    c_factors: list[float] = []
    pump_coeffs: list[list[float]] = []
    pump_speeds: list[float] = []

    seen_edge_ids: set[str] = set()
    for i, edge in enumerate(edges_raw):
        if not isinstance(edge, Mapping):
            raise ValueError(f"edges[{i}] must be an object, got {type(edge).__name__}")
        edge_id = _require_field(edge, "id", where=f"edges[{i}]")
        if not isinstance(edge_id, str) or not edge_id:
            raise ValueError(f"edges[{i}].id must be a non-empty string")
        if edge_id in seen_edge_ids:
            raise ValueError(f"duplicate edge id {edge_id!r}")
        seen_edge_ids.add(edge_id)

        src = _require_field(edge, "source", where=f"edge {edge_id!r}")
        dst = _require_field(edge, "target", where=f"edge {edge_id!r}")
        if src not in id_to_index:
            raise ValueError(
                f"edge {edge_id!r} references unknown source node {src!r}"
            )
        if dst not in id_to_index:
            raise ValueError(
                f"edge {edge_id!r} references unknown target node {dst!r}"
            )
        src_idx.append(id_to_index[src])
        dst_idx.append(id_to_index[dst])

        kind = _require_field(edge, "kind", where=f"edge {edge_id!r}")
        if kind not in _VALID_KINDS:
            raise ValueError(
                f"edge {edge_id!r} has unknown kind {kind!r}; "
                f"must be one of {_VALID_KINDS}"
            )

        if kind == "pipe":
            pipe_mask.append(True)
            pump_mask.append(False)
            length = float(_require_field(edge, "length", where=f"edge {edge_id!r}"))
            diameter = float(_require_field(edge, "diameter", where=f"edge {edge_id!r}"))
            c_factor = float(_require_field(edge, "c_factor", where=f"edge {edge_id!r}"))
            if length <= 0.0:
                raise ValueError(
                    f"edge {edge_id!r} has non-positive length {length}"
                )
            if diameter <= 0.0:
                raise ValueError(
                    f"edge {edge_id!r} has non-positive diameter {diameter}"
                )
            if c_factor <= 0.0:
                raise ValueError(
                    f"edge {edge_id!r} has non-positive c_factor {c_factor}"
                )
            lengths.append(length)
            diameters.append(diameter)
            c_factors.append(c_factor)
            pump_coeffs.append([0.0, 0.0, 0.0])
            pump_speeds.append(0.0)
        else:  # pump
            pipe_mask.append(False)
            pump_mask.append(True)
            if "pump_coeffs" not in edge:
                raise ValueError(
                    f"pump edge {edge_id!r} is missing 'pump_coeffs'"
                )
            coeffs = edge["pump_coeffs"]
            if not isinstance(coeffs, Sequence) or len(coeffs) != 3:
                raise ValueError(
                    f"pump edge {edge_id!r} pump_coeffs must be a length-3 list, "
                    f"got {coeffs!r}"
                )
            a0, a1, a2 = (float(c) for c in coeffs)
            if a0 <= 0.0:
                raise ValueError(
                    f"pump edge {edge_id!r} shut-off head a0={a0} must be > 0"
                )
            pump_coeffs.append([a0, a1, a2])
            pump_speeds.append(float(edge.get("pump_speed", 1.0)))
            # Placeholder pipe parameters on the pump row (kept positive so the
            # Network ``__post_init__`` "positive on pipe edges" check ignores
            # them — the pipe_mask is False).
            lengths.append(1.0)
            diameters.append(1.0)
            c_factors.append(1.0)

    assert len(src_idx) == E and len(dst_idx) == E

    edge_index = torch.tensor([src_idx, dst_idx], dtype=torch.long)
    network = Network(
        edge_index=edge_index,
        num_nodes=N,
        pipe_mask=torch.tensor(pipe_mask, dtype=torch.bool),
        pump_mask=torch.tensor(pump_mask, dtype=torch.bool),
        lengths=torch.tensor(lengths, dtype=torch.get_default_dtype()),
        diameters=torch.tensor(diameters, dtype=torch.get_default_dtype()),
        c_factors=torch.tensor(c_factors, dtype=torch.get_default_dtype()),
        pump_coeffs=torch.tensor(pump_coeffs, dtype=torch.get_default_dtype()),
        pump_speeds=torch.tensor(pump_speeds, dtype=torch.get_default_dtype()),
        demands=torch.tensor(demands, dtype=torch.get_default_dtype()),
        fixed_head_mask=torch.tensor(fixed_mask, dtype=torch.bool),
        fixed_head_values=torch.tensor(fixed_vals, dtype=torch.get_default_dtype()),
    )
    return network


__all__ = ["load_network_from_json"]
