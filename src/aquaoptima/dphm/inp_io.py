"""EPANET ``.inp`` topology loader for the dPHM :class:`Network`.

Sprint 11 adds optional EPANET/WNTR-style ``.inp`` topology import on
top of the Sprint 8 JSON loader, to widen the science gate's external
credibility without requiring a live EPANET engine or any field
adapter. The public surface is one function,
:func:`load_network_from_inp`, which returns the same
:class:`aquaoptima.dphm.Network` dataclass every other loader and
fixture in the project produces.

Two parser back-ends are available:

* ``parser="fallback"`` (default of ``parser="auto"`` when ``wntr`` is
  not installed) — a small, dependency-free parser for a constrained
  subset of the EPANET INP grammar. Enough to load the reference
  fixtures shipped under ``docs/examples/`` and any similarly-shaped
  small reference network.
* ``parser="wntr"`` — uses the upstream `WNTR` package (Water Network
  Tool for Resilience) if it is installed in the active environment.
  WNTR is **optional**: the normal test suite never imports it; the
  optional integration test guards with
  :func:`pytest.importorskip`.

The loader is **topology import only**. It does not run EPANET, does
not bind PLC/PAC/SCADA tags, and does not provide a write/control
path. See ``docs/safety-boundary.md`` and ``docs/epanet-inp-import.md``
for the explicit boundary diagram.

Supported subset of the INP grammar (fallback parser)
-----------------------------------------------------

Sections honoured:

* ``[JUNCTIONS]`` — id, elevation, baseline demand, optional pattern
  (pattern is ignored — the dPHM core is steady-state).
* ``[RESERVOIRS]`` — id, head, optional pattern (ignored).
* ``[TANKS]`` — id, elevation, init-level. Mapped to a fixed-head
  boundary at ``elevation + init_level``; min/max levels and volume
  curves are ignored because the dPHM solver is steady-state.
* ``[PIPES]`` — id, node1, node2, length, diameter, roughness,
  optional minor-loss (ignored), optional status (``CLOSED`` /
  ``CV`` raise :class:`ValueError`; ``OPEN`` is the only accepted
  value — the steady-state core does not model valves).
* ``[OPTIONS]`` — ``Units`` (selects the flow-unit family) and
  ``Headloss`` (must be ``H-W``; the dPHM core is Hazen-Williams).
* ``[COORDINATES]``, ``[TITLE]``, ``[END]``, ``[TIMES]``,
  ``[REPORT]``, ``[PATTERNS]``, ``[VERTICES]``, ``[LABELS]``,
  ``[BACKDROP]``, ``[TAGS]``, ``[ENERGY]``, ``[STATUS]``,
  ``[CONTROLS]``, ``[RULES]``, ``[EMITTERS]``,
  ``[DEMANDS]``, ``[QUALITY]``, ``[SOURCES]``, ``[REACTIONS]``,
  ``[MIXING]``, ``[CURVES]`` — silently ignored (steady-state
  hydraulic topology only).

Sections that intentionally **fail loudly**:

* ``[PUMPS]`` — raises :class:`ValueError`. The Sprint 11 fallback
  parser does not implement EPANET pump curve resolution. Use the
  JSON loader for pump fixtures, or upgrade to WNTR.
* ``[VALVES]`` — raises :class:`ValueError`. The dPHM core does not
  model valves.

Unit conversion
---------------

EPANET picks per-flow-unit conventions for pipe length and diameter:

* **SI flow units** (``LPS``, ``LPM``, ``CMH``, ``CMS``, ``MLD``):
  length in metres, diameter in **millimetres**, head/elevation in
  metres.
* **US flow units** (``CFS``, ``GPM``, ``MGD``, ``IMGD``, ``AFD``):
  length in feet, diameter in inches, head/elevation in feet.

The fallback parser supports the SI family. US units raise a clear
:class:`ValueError`. Demand is converted from the chosen flow unit to
m^3/s before populating ``Network.demands``. Diameter is converted
from mm to m.

If ``[OPTIONS]`` is absent or omits ``Units``, the parser assumes the
EPANET default of ``LPS``.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Mapping, Union

import torch

from .network import Network


PathLike = Union[str, Path]


# --- unit handling ---------------------------------------------------------


_SI_FLOW_UNITS = ("LPS", "LPM", "CMH", "CMS", "MLD")
_US_FLOW_UNITS = ("CFS", "GPM", "MGD", "IMGD", "AFD")

# Conversion factor from the EPANET-declared flow unit into m^3/s.
_DEMAND_TO_CMS: dict[str, float] = {
    "LPS": 1.0e-3,
    "LPM": 1.0 / 60_000.0,
    "CMH": 1.0 / 3600.0,
    "CMS": 1.0,
    "MLD": 1_000.0 / 86_400.0,
}


# Sections we silently skip — they carry no information the
# steady-state Hazen-Williams core depends on.
_IGNORED_SECTIONS = frozenset(
    {
        "TITLE",
        "END",
        "TIMES",
        "REPORT",
        "PATTERNS",
        "COORDINATES",
        "VERTICES",
        "LABELS",
        "BACKDROP",
        "TAGS",
        "ENERGY",
        "STATUS",
        "CONTROLS",
        "RULES",
        "EMITTERS",
        "DEMANDS",
        "QUALITY",
        "SOURCES",
        "REACTIONS",
        "MIXING",
        "CURVES",
    }
)


# --- low-level tokenisation -------------------------------------------------


def _strip_comment(line: str) -> str:
    """Remove a trailing ``; ...`` EPANET comment if present."""
    semi = line.find(";")
    if semi >= 0:
        line = line[:semi]
    return line.strip()


def _read_inp_text(source: PathLike) -> str:
    if isinstance(source, (str, Path)):
        return Path(source).read_text(encoding="utf-8")
    raise ValueError(
        f"load_network_from_inp expects a path-like source, got {type(source).__name__}"
    )


def _split_sections(text: str) -> dict[str, list[list[str]]]:
    """Split the INP file into per-section tokenised rows.

    Returns a mapping ``{SECTION_NAME: [[tok, tok, ...], ...]}``.
    Section names are upper-cased. Rows are pre-stripped of comments
    and blank lines.
    """
    sections: dict[str, list[list[str]]] = {}
    current: str | None = None

    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("["):
            end = stripped.find("]")
            if end < 0:
                raise ValueError(f"malformed INP section header: {raw!r}")
            current = stripped[1:end].strip().upper()
            sections.setdefault(current, [])
            continue

        clean = _strip_comment(raw)
        if not clean:
            continue
        if current is None:
            # Tokens before any [SECTION] header are not standard EPANET;
            # we tolerate them only if they're whitespace/comments
            # (already filtered above).
            raise ValueError(
                f"INP content found before first [SECTION] header: {raw!r}"
            )
        sections[current].append(clean.split())

    return sections


# --- per-section parsers ----------------------------------------------------


def _parse_options(rows: list[list[str]]) -> dict[str, str]:
    """Return a normalised ``{KEY: VALUE}`` map from [OPTIONS] rows."""
    opts: dict[str, str] = {}
    for row in rows:
        if not row:
            continue
        key = row[0].upper()
        val = row[1].upper() if len(row) >= 2 else ""
        opts[key] = val
    return opts


def _resolve_demand_factor(flow_unit: str) -> float:
    flow_unit = flow_unit.upper()
    if flow_unit in _DEMAND_TO_CMS:
        return _DEMAND_TO_CMS[flow_unit]
    if flow_unit in _US_FLOW_UNITS:
        raise ValueError(
            f"US-customary flow unit {flow_unit!r} is not supported by the "
            "fallback INP parser; please convert your fixture to an SI "
            f"flow unit (one of {_SI_FLOW_UNITS}) or use parser='wntr'"
        )
    raise ValueError(
        f"unknown EPANET flow unit {flow_unit!r}; supported SI flow units "
        f"are {tuple(_DEMAND_TO_CMS)}"
    )


def _parse_node_rows(
    rows: list[list[str]],
    *,
    section: str,
    expected_min_cols: int,
) -> list[list[str]]:
    """Light shape check shared by JUNCTIONS / RESERVOIRS / TANKS rows."""
    out: list[list[str]] = []
    for row in rows:
        if len(row) < expected_min_cols:
            raise ValueError(
                f"[{section}] row has only {len(row)} column(s); expected "
                f"at least {expected_min_cols}: {row!r}"
            )
        out.append(row)
    return out


# --- the fallback parser ----------------------------------------------------


def _fallback_parse(
    text: str,
    *,
    default_c_factor: float,
) -> Network:
    sections = _split_sections(text)

    # Required sections
    if "JUNCTIONS" not in sections and "RESERVOIRS" not in sections and "TANKS" not in sections:
        raise ValueError(
            "INP file is missing all node-bearing sections "
            "([JUNCTIONS] / [RESERVOIRS] / [TANKS])"
        )
    if "PIPES" not in sections or not sections["PIPES"]:
        raise ValueError(
            "INP file is missing [PIPES]; the dPHM core requires at least one pipe"
        )

    # Pumps / valves: refuse rather than guess.
    if "PUMPS" in sections and sections["PUMPS"]:
        raise ValueError(
            "[PUMPS] sections are not supported by the fallback INP parser; "
            "use the JSON loader for pump fixtures or install WNTR and pass "
            "parser='wntr'"
        )
    if "VALVES" in sections and sections["VALVES"]:
        raise ValueError(
            "[VALVES] are not modelled by the dPHM steady-state core; "
            "please remove valve rows or replace them with pipe segments"
        )

    # Options
    opts = _parse_options(sections.get("OPTIONS", []))
    flow_unit = opts.get("UNITS", "LPS")
    demand_factor = _resolve_demand_factor(flow_unit)

    headloss = opts.get("HEADLOSS", "H-W").upper()
    if headloss not in ("H-W", "HW"):
        raise ValueError(
            f"INP [OPTIONS] Headloss must be H-W (Hazen-Williams); got {headloss!r}"
        )

    # Build node lists in the order they appear in the file:
    # junctions first, then reservoirs, then tanks. We preserve the
    # in-file row order within each section.
    node_ids: list[str] = []
    demands: list[float] = []
    fixed_mask: list[bool] = []
    fixed_vals: list[float] = []

    seen_node_ids: set[str] = set()

    def _register_node(
        node_id: str,
        demand_si: float,
        is_fixed: bool,
        head_value: float,
        section: str,
    ) -> None:
        if node_id in seen_node_ids:
            raise ValueError(f"duplicate node id {node_id!r} in [{section}]")
        seen_node_ids.add(node_id)
        node_ids.append(node_id)
        demands.append(demand_si)
        fixed_mask.append(is_fixed)
        fixed_vals.append(head_value if is_fixed else 0.0)

    for row in _parse_node_rows(
        sections.get("JUNCTIONS", []), section="JUNCTIONS", expected_min_cols=1
    ):
        node_id = row[0]
        demand_raw = float(row[2]) if len(row) >= 3 else 0.0
        demand_si = demand_raw * demand_factor
        _register_node(
            node_id, demand_si=demand_si, is_fixed=False, head_value=0.0,
            section="JUNCTIONS",
        )

    for row in _parse_node_rows(
        sections.get("RESERVOIRS", []), section="RESERVOIRS", expected_min_cols=2
    ):
        node_id = row[0]
        head_value = float(row[1])
        _register_node(
            node_id, demand_si=0.0, is_fixed=True, head_value=head_value,
            section="RESERVOIRS",
        )

    for row in _parse_node_rows(
        sections.get("TANKS", []), section="TANKS", expected_min_cols=3
    ):
        node_id = row[0]
        elev = float(row[1])
        init_level = float(row[2])
        # Steady-state surrogate: a tank pins its node to the current
        # water-surface elevation. Documented limitation — the dPHM core
        # does not integrate tank volumes over time in Sprint 11.
        _register_node(
            node_id,
            demand_si=0.0,
            is_fixed=True,
            head_value=elev + init_level,
            section="TANKS",
        )

    if not node_ids:
        raise ValueError("INP file declared no nodes")

    if not any(fixed_mask):
        raise ValueError(
            "INP topology has no fixed-head boundary (reservoir or tank); the "
            "dPHM solver requires at least one"
        )

    id_to_index = {nid: idx for idx, nid in enumerate(node_ids)}

    # Edges
    src_idx: list[int] = []
    dst_idx: list[int] = []
    pipe_mask: list[bool] = []
    pump_mask: list[bool] = []
    lengths: list[float] = []
    diameters: list[float] = []
    c_factors: list[float] = []
    edge_pump_coeffs: list[list[float]] = []
    edge_pump_speeds: list[float] = []

    seen_edge_ids: set[str] = set()

    for row in sections["PIPES"]:
        if len(row) < 6:
            raise ValueError(
                f"[PIPES] row has only {len(row)} column(s); expected at least "
                f"6 (id, node1, node2, length, diameter, roughness): {row!r}"
            )
        edge_id, node1, node2 = row[0], row[1], row[2]
        if edge_id in seen_edge_ids:
            raise ValueError(f"duplicate edge id {edge_id!r} in [PIPES]")
        seen_edge_ids.add(edge_id)
        if node1 not in id_to_index:
            raise ValueError(
                f"pipe {edge_id!r} references unknown source node {node1!r}"
            )
        if node2 not in id_to_index:
            raise ValueError(
                f"pipe {edge_id!r} references unknown target node {node2!r}"
            )

        length = float(row[3])
        # EPANET SI: diameter in mm -> convert to m for the Network dataclass.
        diameter_mm = float(row[4])
        diameter_m = diameter_mm * 1.0e-3
        c_factor = float(row[5]) if len(row) >= 6 else default_c_factor

        if length <= 0.0:
            raise ValueError(
                f"pipe {edge_id!r} has non-positive length {length}"
            )
        if diameter_m <= 0.0:
            raise ValueError(
                f"pipe {edge_id!r} has non-positive diameter {diameter_mm} mm"
            )
        if c_factor <= 0.0:
            raise ValueError(
                f"pipe {edge_id!r} has non-positive roughness / c_factor {c_factor}"
            )

        # Optional status column (8th): only OPEN is accepted by the steady-state core.
        if len(row) >= 8:
            status = row[7].upper()
            if status not in ("OPEN",):
                raise ValueError(
                    f"pipe {edge_id!r} has unsupported status {status!r}; the "
                    "dPHM core only models OPEN pipes (no CLOSED / CV valves)"
                )

        src_idx.append(id_to_index[node1])
        dst_idx.append(id_to_index[node2])
        pipe_mask.append(True)
        pump_mask.append(False)
        lengths.append(length)
        diameters.append(diameter_m)
        c_factors.append(c_factor)
        edge_pump_coeffs.append([0.0, 0.0, 0.0])
        edge_pump_speeds.append(0.0)

    if not src_idx:
        raise ValueError("INP file declared no pipes after parsing [PIPES]")

    # Re-balance demand so the network is mass-consistent at parse time:
    # any drift (e.g. demands declared on junctions but no matching supply
    # row) is absorbed by the fixed-head boundaries. The mass term for
    # fixed-head nodes drops out of the residual anyway, so this is a
    # purely cosmetic adjustment — but it keeps the JSON-loader contract
    # (sum-near-zero demands) and makes the network easier to inspect.
    total_demand = sum(demands)
    fixed_idx = [i for i, f in enumerate(fixed_mask) if f]
    if fixed_idx and not math.isclose(total_demand, 0.0, abs_tol=1e-12):
        share = total_demand / len(fixed_idx)
        for i in fixed_idx:
            # Supply convention: positive demand sum is balanced by
            # negative demand on the boundary node (fixed-head node
            # "supplies" the deficit).
            demands[i] -= share

    edge_index = torch.tensor([src_idx, dst_idx], dtype=torch.long)
    return Network(
        edge_index=edge_index,
        num_nodes=len(node_ids),
        pipe_mask=torch.tensor(pipe_mask, dtype=torch.bool),
        pump_mask=torch.tensor(pump_mask, dtype=torch.bool),
        lengths=torch.tensor(lengths, dtype=torch.get_default_dtype()),
        diameters=torch.tensor(diameters, dtype=torch.get_default_dtype()),
        c_factors=torch.tensor(c_factors, dtype=torch.get_default_dtype()),
        pump_coeffs=torch.tensor(edge_pump_coeffs, dtype=torch.get_default_dtype()),
        pump_speeds=torch.tensor(edge_pump_speeds, dtype=torch.get_default_dtype()),
        demands=torch.tensor(demands, dtype=torch.get_default_dtype()),
        fixed_head_mask=torch.tensor(fixed_mask, dtype=torch.bool),
        fixed_head_values=torch.tensor(fixed_vals, dtype=torch.get_default_dtype()),
    )


# --- WNTR-backed parser (optional) ------------------------------------------


def _wntr_available() -> bool:
    try:
        import wntr  # noqa: F401
    except ImportError:
        return False
    return True


def _wntr_parse(source: PathLike, *, default_c_factor: float) -> Network:
    try:
        import wntr  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "parser='wntr' requires the 'wntr' package. Install with: "
            "pip install 'aquaoptima-dphm-pinn[epanet]' or pip install wntr"
        ) from exc

    wn = wntr.network.WaterNetworkModel(str(source))

    # Pull the same minimum subset the fallback parser supports, in a
    # WNTR-version-tolerant way. We never rely on attributes that have
    # changed across WNTR releases — only the public lookup APIs.
    node_ids: list[str] = []
    demands: list[float] = []
    fixed_mask: list[bool] = []
    fixed_vals: list[float] = []

    # Junctions first
    for jid in wn.junction_name_list:
        j = wn.get_node(jid)
        # WNTR stores baseline demand in m^3/s already (the engine's
        # internal SI unit), regardless of the file's [OPTIONS] Units.
        base_demand = float(getattr(j, "base_demand", 0.0) or 0.0)
        node_ids.append(jid)
        demands.append(base_demand)
        fixed_mask.append(False)
        fixed_vals.append(0.0)

    for rid in wn.reservoir_name_list:
        r = wn.get_node(rid)
        head_value = float(getattr(r, "base_head", 0.0) or 0.0)
        node_ids.append(rid)
        demands.append(0.0)
        fixed_mask.append(True)
        fixed_vals.append(head_value)

    for tid in wn.tank_name_list:
        t = wn.get_node(tid)
        elev = float(getattr(t, "elevation", 0.0) or 0.0)
        init_level = float(getattr(t, "init_level", 0.0) or 0.0)
        node_ids.append(tid)
        demands.append(0.0)
        fixed_mask.append(True)
        fixed_vals.append(elev + init_level)

    if not node_ids:
        raise ValueError("WNTR model declared no nodes")
    if not any(fixed_mask):
        raise ValueError(
            "WNTR model has no fixed-head boundary; the dPHM solver requires "
            "at least one reservoir or tank"
        )

    id_to_index = {nid: idx for idx, nid in enumerate(node_ids)}

    src_idx: list[int] = []
    dst_idx: list[int] = []
    pipe_mask: list[bool] = []
    pump_mask: list[bool] = []
    lengths: list[float] = []
    diameters: list[float] = []
    c_factors: list[float] = []
    edge_pump_coeffs: list[list[float]] = []
    edge_pump_speeds: list[float] = []

    for pid in wn.pipe_name_list:
        p = wn.get_link(pid)
        n1 = p.start_node_name
        n2 = p.end_node_name
        if n1 not in id_to_index or n2 not in id_to_index:
            raise ValueError(
                f"WNTR pipe {pid!r} references nodes outside the supported set"
            )
        length = float(getattr(p, "length", 0.0))
        diameter_m = float(getattr(p, "diameter", 0.0))
        c_factor = float(getattr(p, "roughness", default_c_factor) or default_c_factor)
        if length <= 0.0 or diameter_m <= 0.0 or c_factor <= 0.0:
            raise ValueError(
                f"WNTR pipe {pid!r} has non-positive length/diameter/c_factor"
            )
        src_idx.append(id_to_index[n1])
        dst_idx.append(id_to_index[n2])
        pipe_mask.append(True)
        pump_mask.append(False)
        lengths.append(length)
        diameters.append(diameter_m)
        c_factors.append(c_factor)
        edge_pump_coeffs.append([0.0, 0.0, 0.0])
        edge_pump_speeds.append(0.0)

    if hasattr(wn, "pump_name_list") and wn.pump_name_list:
        raise ValueError(
            "WNTR-loaded INP file contains pumps; the Sprint 11 WNTR adapter "
            "does not yet translate pump curves into the dPHM pump-affinity "
            "representation. Please remove pumps from the fixture."
        )
    if hasattr(wn, "valve_name_list") and wn.valve_name_list:
        raise ValueError(
            "WNTR-loaded INP file contains valves; the dPHM steady-state "
            "core does not model valves"
        )

    edge_index = torch.tensor([src_idx, dst_idx], dtype=torch.long)
    return Network(
        edge_index=edge_index,
        num_nodes=len(node_ids),
        pipe_mask=torch.tensor(pipe_mask, dtype=torch.bool),
        pump_mask=torch.tensor(pump_mask, dtype=torch.bool),
        lengths=torch.tensor(lengths, dtype=torch.get_default_dtype()),
        diameters=torch.tensor(diameters, dtype=torch.get_default_dtype()),
        c_factors=torch.tensor(c_factors, dtype=torch.get_default_dtype()),
        pump_coeffs=torch.tensor(edge_pump_coeffs, dtype=torch.get_default_dtype()),
        pump_speeds=torch.tensor(edge_pump_speeds, dtype=torch.get_default_dtype()),
        demands=torch.tensor(demands, dtype=torch.get_default_dtype()),
        fixed_head_mask=torch.tensor(fixed_mask, dtype=torch.bool),
        fixed_head_values=torch.tensor(fixed_vals, dtype=torch.get_default_dtype()),
    )


# --- public entry point -----------------------------------------------------


_VALID_PARSERS = ("auto", "fallback", "wntr")


def load_network_from_inp(
    source: PathLike,
    *,
    parser: str = "auto",
    units: str = "si",
    default_c_factor: float = 130.0,
) -> Network:
    """Parse an EPANET ``.inp`` topology into a :class:`Network`.

    Parameters
    ----------
    source
        Path to an EPANET INP file. Both :class:`str` and
        :class:`pathlib.Path` are accepted. The file is opened with
        UTF-8 encoding.
    parser
        Back-end selector:

        * ``"auto"`` (default) — prefer the WNTR back-end if WNTR is
          installed, otherwise fall back to the built-in parser.
        * ``"fallback"`` — always use the built-in parser, even if
          WNTR is installed.
        * ``"wntr"`` — require the WNTR back-end. Raises
          :class:`ImportError` if WNTR is not installed.

    units
        Currently only ``"si"`` is supported. Reserved for future
        US-customary support. Any other value raises
        :class:`ValueError`. The actual flow unit (``LPS``, ``CMS``,
        …) is read from the INP file's ``[OPTIONS] Units`` directive;
        this parameter only asserts the unit family.
    default_c_factor
        Hazen-Williams roughness coefficient used when a pipe row
        omits its roughness column. Default ``130.0`` matches the
        Sprint 1-10 reference networks.

    Returns
    -------
    Network
        The validated dPHM network with node ordering preserved
        as ``[junctions..., reservoirs..., tanks...]`` from the
        file's own ordering inside each section.

    Raises
    ------
    ValueError
        For malformed input, unsupported sections (pumps in the
        fallback parser, valves anywhere), missing fixed-head
        boundaries, non-positive pipe parameters, or US-customary
        flow units.
    ImportError
        Only when ``parser="wntr"`` and WNTR is not installed.
    """
    if parser not in _VALID_PARSERS:
        raise ValueError(
            f"parser must be one of {_VALID_PARSERS}, got {parser!r}"
        )
    if units.lower() != "si":
        raise ValueError(
            f"units={units!r} is not supported; only 'si' is implemented in "
            "Sprint 11. US-customary support is deferred."
        )
    if default_c_factor <= 0.0:
        raise ValueError(
            f"default_c_factor must be > 0, got {default_c_factor}"
        )

    text = _read_inp_text(source)

    if parser == "wntr":
        return _wntr_parse(source, default_c_factor=default_c_factor)
    if parser == "fallback":
        return _fallback_parse(text, default_c_factor=default_c_factor)

    # "auto"
    if _wntr_available():
        return _wntr_parse(source, default_c_factor=default_c_factor)
    return _fallback_parse(text, default_c_factor=default_c_factor)


__all__ = ["load_network_from_inp"]
