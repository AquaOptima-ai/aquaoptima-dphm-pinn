"""Telemetry tag-map adapter (Sprint 34).

Sprint 34 introduces the first shadow-mode plumbing layer between
operator-facing telemetry tags (sensor IDs, SCADA / historian point
names, control-input setpoints) and the canonical dPHM
:class:`Network` topology imported by Sprints 11-33. The Sprint 33
import-quality report already names every dPHM node / edge produced
from a surrogate (PRV / TCV) or an implicitly-pinned boundary
(reservoirs / tanks); the next bottleneck is letting an operator name
those dPHM ids with the labels they actually see on the plant floor
(``PT_DISCHARGE_01``, ``FT_PUMP_01``, ``PUMP_01_SPEED``).

This module is **read-only schema / adaptation only**. It contains:

* :class:`TelemetryTagSpec` — operator-facing input. Names a single
  telemetry tag and the dPHM node / edge it ties to.
* :class:`CanonicalTelemetryTag` — validated, canonicalised output.
  Adds a canonical unit and a canonical axis token (e.g.
  ``"node_pressure"``, ``"edge_flow"``, ``"edge_pump_speed"``).
* :class:`TelemetryTagMapDiagnostics` — deterministic warnings /
  errors tuples.
* :class:`TelemetryTagMap` — frozen container holding the canonical
  tag tuple and the diagnostics.

The builder :func:`build_telemetry_tag_map` is **pure**:

* never mutates the supplied :class:`Network` or the input spec
  sequence;
* never opens a network socket, file, or process;
* never converts a measurement *value* — only canonical *metadata*
  (axis token, canonical unit string) is produced. Value conversion
  is deliberately out of scope for Sprint 34;
* in ``strict=True`` raises :class:`ValueError` if any structural
  error is detected (empty tag, duplicate tag, unknown enum, out-of-
  range dPHM id, unknown unit); in ``strict=False`` returns a map
  containing the valid tags plus a diagnostics tuple of error
  strings — invalid tags are omitted from ``tags``.

Safety boundary (reaffirmed verbatim per Sprint 23-33):

* no live SCADA / PLC / PAC / historian / OPC-UA / MQTT / REST
  adapter;
* no write / control / setpoint path;
* no value conversion at runtime;
* no replay / shadow dataset builder — Sprint 35;
* no dPL calibration;
* no advisory / control recommendation surface;
* no production savings / control claim.

The Sprint 34 boundary is intentionally narrower than the
:mod:`aquaoptima.dataio` Sprint 4.5 telemetry abstraction. Sprint 34
provides only a typed *schema* surface against an already-imported
dPHM :class:`Network`. The Sprint 4.5 ``SiteTagMap`` / ``TagDefinition``
surface is broader (per-site, sampling intervals, source-type tag,
quality flags) and lives in the data-IO layer; Sprint 34's adapter is
the dPHM-side metadata shim a future shadow-mode dataset builder
(Sprint 35) will consume alongside an offline telemetry frame.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Union

from .network import Network


PathLike = Union[str, Path]


# ---------------------------------------------------------------------------
# Canonical enum-like constants (stable string tokens — see module docstring).
# ---------------------------------------------------------------------------


TELEMETRY_TARGET_NODE: str = "NODE"
TELEMETRY_TARGET_EDGE: str = "EDGE"

TELEMETRY_TARGET_TYPES: tuple[str, ...] = (
    TELEMETRY_TARGET_NODE,
    TELEMETRY_TARGET_EDGE,
)


TELEMETRY_MEASUREMENT_PRESSURE: str = "pressure"
TELEMETRY_MEASUREMENT_FLOW: str = "flow"
TELEMETRY_MEASUREMENT_DEMAND: str = "demand"
TELEMETRY_MEASUREMENT_PUMP_SPEED: str = "pump_speed"
TELEMETRY_MEASUREMENT_LEVEL: str = "level"
TELEMETRY_MEASUREMENT_STATUS: str = "status"
TELEMETRY_MEASUREMENT_POWER: str = "power"
TELEMETRY_MEASUREMENT_VALVE_POSITION: str = "valve_position"

TELEMETRY_MEASUREMENTS: tuple[str, ...] = (
    TELEMETRY_MEASUREMENT_PRESSURE,
    TELEMETRY_MEASUREMENT_FLOW,
    TELEMETRY_MEASUREMENT_DEMAND,
    TELEMETRY_MEASUREMENT_PUMP_SPEED,
    TELEMETRY_MEASUREMENT_LEVEL,
    TELEMETRY_MEASUREMENT_STATUS,
    TELEMETRY_MEASUREMENT_POWER,
    TELEMETRY_MEASUREMENT_VALVE_POSITION,
)


TELEMETRY_ROLE_OBSERVED: str = "observed"
TELEMETRY_ROLE_CONTROL_INPUT: str = "control_input"
TELEMETRY_ROLE_DERIVED: str = "derived"
TELEMETRY_ROLE_QUALITY: str = "quality"

TELEMETRY_ROLES: tuple[str, ...] = (
    TELEMETRY_ROLE_OBSERVED,
    TELEMETRY_ROLE_CONTROL_INPUT,
    TELEMETRY_ROLE_DERIVED,
    TELEMETRY_ROLE_QUALITY,
)


TELEMETRY_AXIS_NODE_PRESSURE: str = "node_pressure"
TELEMETRY_AXIS_NODE_DEMAND: str = "node_demand"
TELEMETRY_AXIS_NODE_LEVEL: str = "node_level"
TELEMETRY_AXIS_NODE_STATUS: str = "node_status"
TELEMETRY_AXIS_EDGE_FLOW: str = "edge_flow"
TELEMETRY_AXIS_EDGE_PUMP_SPEED: str = "edge_pump_speed"
TELEMETRY_AXIS_EDGE_STATUS: str = "edge_status"
TELEMETRY_AXIS_EDGE_POWER: str = "edge_power"
TELEMETRY_AXIS_EDGE_VALVE_POSITION: str = "edge_valve_position"

TELEMETRY_AXES: tuple[str, ...] = (
    TELEMETRY_AXIS_NODE_PRESSURE,
    TELEMETRY_AXIS_NODE_DEMAND,
    TELEMETRY_AXIS_NODE_LEVEL,
    TELEMETRY_AXIS_NODE_STATUS,
    TELEMETRY_AXIS_EDGE_FLOW,
    TELEMETRY_AXIS_EDGE_PUMP_SPEED,
    TELEMETRY_AXIS_EDGE_STATUS,
    TELEMETRY_AXIS_EDGE_POWER,
    TELEMETRY_AXIS_EDGE_VALVE_POSITION,
)


# Per-measurement canonical unit + accepted unit family. The accepted
# unit set is intentionally small (Sprint 34 MVP): downstream code
# that needs more aliases can extend this table without changing the
# adapter surface. Case-insensitive comparison is performed against the
# normalised lower-case input.
_MEASUREMENT_UNIT_TABLE: Mapping[str, tuple[str, tuple[str, ...]]] = {
    TELEMETRY_MEASUREMENT_PRESSURE: ("m", ("m", "meter", "bar", "psi", "kpa")),
    TELEMETRY_MEASUREMENT_FLOW: ("m3/s", ("m3/s", "l/s", "gpm")),
    TELEMETRY_MEASUREMENT_DEMAND: ("m3/s", ("m3/s", "l/s", "gpm")),
    TELEMETRY_MEASUREMENT_PUMP_SPEED: (
        "fraction",
        ("fraction", "percent", "rpm"),
    ),
    TELEMETRY_MEASUREMENT_LEVEL: ("m", ("m", "meter", "ft")),
    TELEMETRY_MEASUREMENT_STATUS: ("boolean", ("boolean", "bool", "0/1")),
    TELEMETRY_MEASUREMENT_POWER: ("kw", ("kw", "w")),
    TELEMETRY_MEASUREMENT_VALVE_POSITION: (
        "fraction",
        ("percent", "fraction"),
    ),
}


# Valid measurement / target_type pairs. Entries that are missing are
# rejected at build time. This is the single source of truth for what
# *canonical axis* token a (target_type, measurement) pair maps to.
_AXIS_TABLE: Mapping[tuple[str, str], str] = {
    (TELEMETRY_TARGET_NODE, TELEMETRY_MEASUREMENT_PRESSURE): TELEMETRY_AXIS_NODE_PRESSURE,
    (TELEMETRY_TARGET_NODE, TELEMETRY_MEASUREMENT_DEMAND): TELEMETRY_AXIS_NODE_DEMAND,
    (TELEMETRY_TARGET_NODE, TELEMETRY_MEASUREMENT_LEVEL): TELEMETRY_AXIS_NODE_LEVEL,
    (TELEMETRY_TARGET_NODE, TELEMETRY_MEASUREMENT_STATUS): TELEMETRY_AXIS_NODE_STATUS,
    (TELEMETRY_TARGET_EDGE, TELEMETRY_MEASUREMENT_FLOW): TELEMETRY_AXIS_EDGE_FLOW,
    (TELEMETRY_TARGET_EDGE, TELEMETRY_MEASUREMENT_PUMP_SPEED): TELEMETRY_AXIS_EDGE_PUMP_SPEED,
    (TELEMETRY_TARGET_EDGE, TELEMETRY_MEASUREMENT_STATUS): TELEMETRY_AXIS_EDGE_STATUS,
    (TELEMETRY_TARGET_EDGE, TELEMETRY_MEASUREMENT_POWER): TELEMETRY_AXIS_EDGE_POWER,
    (TELEMETRY_TARGET_EDGE, TELEMETRY_MEASUREMENT_VALVE_POSITION): (
        TELEMETRY_AXIS_EDGE_VALVE_POSITION
    ),
}


# ---------------------------------------------------------------------------
# Frozen dataclass surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TelemetryTagSpec:
    """Operator-facing input: a single telemetry tag declaration.

    Specs are normalised (tag trimmed) and validated by
    :func:`build_telemetry_tag_map` against a loaded :class:`Network`.

    Attributes
    ----------
    tag
        Operator-facing tag identifier (e.g. ``"PT_DISCHARGE_01"``).
        Whitespace is trimmed before validation. Empty tags are
        rejected.
    target_type
        Either :data:`TELEMETRY_TARGET_NODE` or
        :data:`TELEMETRY_TARGET_EDGE` (case-insensitive on input).
    target_id
        Zero-based dPHM id. For ``target_type=NODE`` it must lie in
        ``[0, network.num_nodes)``; for ``target_type=EDGE`` in
        ``[0, network.edge_index.shape[1])``.
    measurement
        Canonical measurement name; must be a member of
        :data:`TELEMETRY_MEASUREMENTS`.
    unit
        Operator-supplied unit string (case-insensitive); must belong
        to the accepted unit family for ``measurement``.
    role
        Tag role (defaults to :data:`TELEMETRY_ROLE_OBSERVED`); must
        be a member of :data:`TELEMETRY_ROLES`.
    description
        Free-form description (preserved verbatim). Defaults to ``""``.
    """

    tag: str
    target_type: str
    target_id: int
    measurement: str
    unit: str
    role: str = TELEMETRY_ROLE_OBSERVED
    description: str = ""


@dataclass(frozen=True)
class CanonicalTelemetryTag:
    """Validated, canonicalised output for a single telemetry tag.

    Produced by :func:`build_telemetry_tag_map` from a
    :class:`TelemetryTagSpec`. Adds the canonical axis token and the
    canonical unit string for the measurement. No value conversion is
    performed.

    Attributes
    ----------
    tag
        Trimmed tag string.
    target_type
        Upper-case canonical token (:data:`TELEMETRY_TARGET_NODE` or
        :data:`TELEMETRY_TARGET_EDGE`).
    target_id
        Validated zero-based dPHM id.
    measurement
        Canonical measurement name (lower-case, from
        :data:`TELEMETRY_MEASUREMENTS`).
    unit
        Operator-supplied unit string (lower-case, normalised).
    canonical_unit
        Canonical unit string the measurement reports in (e.g.
        ``"m"`` for pressure, ``"m3/s"`` for flow). No conversion of
        the *value* is performed in Sprint 34.
    role
        Canonical role string (lower-case, from
        :data:`TELEMETRY_ROLES`).
    axis
        Canonical axis token from :data:`TELEMETRY_AXES`. The axis is
        what a Sprint 35 replay / shadow dataset builder will key on
        when joining telemetry frames to dPHM ids.
    description
        Free-form description, preserved verbatim from the input
        spec.
    """

    tag: str
    target_type: str
    target_id: int
    measurement: str
    unit: str
    canonical_unit: str
    role: str
    axis: str
    description: str = ""


@dataclass(frozen=True)
class TelemetryTagMapDiagnostics:
    """Deterministic warnings / errors tuples for a tag-map build.

    Both tuples are empty for a fully-valid input. In
    ``strict=False`` mode, ``errors`` carries one entry per rejected
    spec (input order is preserved); the corresponding spec is omitted
    from the map's ``tags``. In ``strict=True`` mode the builder
    raises :class:`ValueError` instead of returning a populated
    ``errors`` tuple.

    Attributes
    ----------
    warnings
        Deterministic tuple of human-readable warnings. Reserved for
        future use; Sprint 34 emits no warnings.
    errors
        Deterministic tuple of human-readable error strings, in input
        order.
    """

    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class TelemetryTagMap:
    """Read-only typed telemetry tag-map surface.

    Frozen container holding the validated, canonicalised tag tuple
    and the build diagnostics. Building the map twice on the same
    inputs returns equal maps — equal tuples in the same order, equal
    diagnostics. No timestamps, random sampling, or hidden state are
    involved.

    Attributes
    ----------
    tags
        Tuple of :class:`CanonicalTelemetryTag`, in the same order as
        the input specs (rejected specs are omitted in
        ``strict=False`` mode).
    diagnostics
        :class:`TelemetryTagMapDiagnostics` describing any warnings or
        non-fatal errors.
    """

    tags: tuple[CanonicalTelemetryTag, ...] = ()
    diagnostics: TelemetryTagMapDiagnostics = field(
        default_factory=TelemetryTagMapDiagnostics
    )


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


_SPEC_FIELDS: tuple[str, ...] = (
    "tag",
    "target_type",
    "target_id",
    "measurement",
    "unit",
    "role",
    "description",
)


def _coerce_spec(raw: object, *, index: int) -> tuple[TelemetryTagSpec | None, str | None]:
    """Coerce a dataclass-or-mapping input into a :class:`TelemetryTagSpec`.

    Returns ``(spec, error)`` where exactly one is ``None``. The
    caller is responsible for surfacing ``error`` through the
    diagnostics tuple. ``index`` is the 0-based position of the spec
    in the caller's iterable, used only for error messages.
    """
    if isinstance(raw, TelemetryTagSpec):
        return raw, None
    if isinstance(raw, Mapping):
        # Reject unknown keys early so typos surface as errors instead
        # of silently being dropped.
        unknown = sorted(k for k in raw.keys() if k not in _SPEC_FIELDS)
        if unknown:
            return (
                None,
                f"spec[{index}]: unknown field(s) {unknown!r}; allowed: {list(_SPEC_FIELDS)}",
            )
        for required in ("tag", "target_type", "target_id", "measurement", "unit"):
            if required not in raw:
                return (
                    None,
                    f"spec[{index}]: missing required field {required!r}",
                )
        try:
            spec = TelemetryTagSpec(
                tag=str(raw["tag"]),
                target_type=str(raw["target_type"]),
                target_id=int(raw["target_id"]),
                measurement=str(raw["measurement"]),
                unit=str(raw["unit"]),
                role=str(raw.get("role", TELEMETRY_ROLE_OBSERVED)),
                description=str(raw.get("description", "")),
            )
        except (TypeError, ValueError) as exc:
            return (
                None,
                f"spec[{index}]: could not coerce mapping into TelemetryTagSpec ({exc})",
            )
        return spec, None
    return (
        None,
        f"spec[{index}]: expected TelemetryTagSpec or mapping, got {type(raw).__name__}",
    )


def _validate_spec(
    spec: TelemetryTagSpec,
    *,
    index: int,
    num_nodes: int,
    num_edges: int,
) -> tuple[CanonicalTelemetryTag | None, str | None]:
    """Validate a coerced :class:`TelemetryTagSpec` against the network.

    Returns ``(canonical, error)`` — exactly one is ``None``.
    """
    tag = spec.tag.strip()
    if not tag:
        return None, f"spec[{index}]: tag is empty"

    target_type_raw = str(spec.target_type).strip().upper()
    if target_type_raw not in TELEMETRY_TARGET_TYPES:
        return (
            None,
            f"spec[{index}] (tag={tag!r}): unknown target_type "
            f"{spec.target_type!r}; expected one of {list(TELEMETRY_TARGET_TYPES)}",
        )

    target_id = int(spec.target_id)
    if target_type_raw == TELEMETRY_TARGET_NODE:
        if target_id < 0 or target_id >= num_nodes:
            return (
                None,
                f"spec[{index}] (tag={tag!r}): node target_id {target_id} "
                f"out of range [0, {num_nodes})",
            )
    else:  # EDGE
        if target_id < 0 or target_id >= num_edges:
            return (
                None,
                f"spec[{index}] (tag={tag!r}): edge target_id {target_id} "
                f"out of range [0, {num_edges})",
            )

    measurement = str(spec.measurement).strip().lower()
    if measurement not in TELEMETRY_MEASUREMENTS:
        return (
            None,
            f"spec[{index}] (tag={tag!r}): unknown measurement "
            f"{spec.measurement!r}; expected one of {list(TELEMETRY_MEASUREMENTS)}",
        )

    axis = _AXIS_TABLE.get((target_type_raw, measurement))
    if axis is None:
        return (
            None,
            f"spec[{index}] (tag={tag!r}): measurement {measurement!r} is "
            f"not valid for target_type {target_type_raw!r}",
        )

    role = str(spec.role).strip().lower()
    if role not in TELEMETRY_ROLES:
        return (
            None,
            f"spec[{index}] (tag={tag!r}): unknown role {spec.role!r}; "
            f"expected one of {list(TELEMETRY_ROLES)}",
        )

    unit_raw = str(spec.unit).strip().lower()
    if not unit_raw:
        return None, f"spec[{index}] (tag={tag!r}): unit is empty"

    canonical_unit, accepted_units = _MEASUREMENT_UNIT_TABLE[measurement]
    if unit_raw not in accepted_units:
        return (
            None,
            f"spec[{index}] (tag={tag!r}): unit {spec.unit!r} not in "
            f"accepted unit family for measurement {measurement!r}; "
            f"expected one of {list(accepted_units)}",
        )

    return (
        CanonicalTelemetryTag(
            tag=tag,
            target_type=target_type_raw,
            target_id=target_id,
            measurement=measurement,
            unit=unit_raw,
            canonical_unit=canonical_unit,
            role=role,
            axis=axis,
            description=str(spec.description),
        ),
        None,
    )


def _network_dimensions(network: Network) -> tuple[int, int]:
    """Return ``(num_nodes, num_edges)`` for the supplied network.

    The accessor stays defensive: a duck-typed test fake without the
    documented ``edge_index`` attribute raises :class:`TypeError`
    (which the caller surfaces as a build-time programmer error,
    *not* a per-spec diagnostic).
    """
    num_nodes = int(network.num_nodes)
    edge_index = network.edge_index
    num_edges = int(edge_index.shape[1])
    return num_nodes, num_edges


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_telemetry_tag_map(
    specs: Iterable[TelemetryTagSpec | Mapping[str, object]],
    network: Network,
    *,
    strict: bool = True,
) -> TelemetryTagMap:
    """Validate ``specs`` against ``network`` and return a typed map.

    The builder is **pure**:

    * never mutates ``network`` or any spec;
    * never opens a socket / file / process (the JSON loader is a
      separate function);
    * never converts a measurement value — only canonical metadata
      (axis token, canonical unit string) is produced.

    Parameters
    ----------
    specs
        Iterable of :class:`TelemetryTagSpec` or mapping objects with
        the same field names. Dict inputs are coerced via
        :class:`TelemetryTagSpec`; unknown keys raise an error.
    network
        Loaded :class:`Network` against which dPHM ids are validated.
        The network is never mutated.
    strict
        When ``True`` (default), the builder raises
        :class:`ValueError` if any structural error is detected
        (empty tag, duplicate tag, unknown enum, out-of-range id,
        unknown unit). When ``False``, invalid specs are omitted from
        the returned map and an error string is appended to
        ``diagnostics.errors`` in input order; valid specs are
        preserved.

    Returns
    -------
    TelemetryTagMap
        A frozen, immutable map. Every collection field is a freshly
        allocated tuple; subsequent mutation of the input spec
        sequence cannot affect the returned map.

    Raises
    ------
    ValueError
        In ``strict=True`` mode, if any structural error is detected.
        The error message is a single string with every detected
        error joined by ``"; "`` (input order preserved).
    """
    num_nodes, num_edges = _network_dimensions(network)

    errors: list[str] = []
    canonicals: list[CanonicalTelemetryTag] = []
    seen_tags: set[str] = set()

    for index, raw in enumerate(specs):
        spec, coerce_error = _coerce_spec(raw, index=index)
        if spec is None:
            errors.append(coerce_error)  # type: ignore[arg-type]
            continue

        canonical, validate_error = _validate_spec(
            spec,
            index=index,
            num_nodes=num_nodes,
            num_edges=num_edges,
        )
        if canonical is None:
            errors.append(validate_error)  # type: ignore[arg-type]
            continue

        if canonical.tag in seen_tags:
            errors.append(
                f"spec[{index}] (tag={canonical.tag!r}): duplicate tag; "
                f"every tag must be unique"
            )
            continue

        seen_tags.add(canonical.tag)
        canonicals.append(canonical)

    if strict and errors:
        raise ValueError(
            "build_telemetry_tag_map rejected " f"{len(errors)} spec(s): " + "; ".join(errors)
        )

    return TelemetryTagMap(
        tags=tuple(canonicals),
        diagnostics=TelemetryTagMapDiagnostics(
            warnings=(),
            errors=tuple(errors),
        ),
    )


# ---------------------------------------------------------------------------
# JSON loader
# ---------------------------------------------------------------------------


def load_telemetry_tag_map_json(
    path: PathLike,
    network: Network,
    *,
    strict: bool = True,
) -> TelemetryTagMap:
    """Load a telemetry tag-map from a JSON file and validate it.

    The JSON document may be either a list of spec objects::

        [{"tag": "PT1", "target_type": "NODE", "target_id": 2, ...}]

    or a single object with a ``"tags"`` key::

        {"tags": [{"tag": "PT1", ...}, ...]}

    Any other top-level shape (object without ``"tags"``, scalar,
    nested list, …) raises :class:`ValueError`. No YAML dependency is
    introduced.

    Parameters
    ----------
    path
        Filesystem path to a JSON file (``str`` or ``pathlib.Path``).
    network
        Loaded :class:`Network` against which dPHM ids are validated.
    strict
        Forwarded to :func:`build_telemetry_tag_map`.

    Returns
    -------
    TelemetryTagMap
        The validated map.

    Raises
    ------
    ValueError
        On malformed JSON shape, or (in ``strict=True``) on validation
        errors.
    """
    path_obj = Path(path)
    with path_obj.open("r", encoding="utf-8") as fh:
        document = json.load(fh)

    if isinstance(document, list):
        rows = document
    elif isinstance(document, Mapping):
        if "tags" not in document:
            raise ValueError(
                f"load_telemetry_tag_map_json: object document must contain "
                f"a 'tags' key; got keys {sorted(document.keys())!r}"
            )
        tags_value = document["tags"]
        if not isinstance(tags_value, list):
            raise ValueError(
                f"load_telemetry_tag_map_json: 'tags' must be a list, got "
                f"{type(tags_value).__name__}"
            )
        rows = tags_value
    else:
        raise ValueError(
            f"load_telemetry_tag_map_json: top-level JSON must be a list or "
            f"an object with a 'tags' key, got {type(document).__name__}"
        )

    for i, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(
                f"load_telemetry_tag_map_json: tags[{i}] must be an object, "
                f"got {type(row).__name__}"
            )

    return build_telemetry_tag_map(rows, network, strict=strict)


__all__ = [
    "CanonicalTelemetryTag",
    "TELEMETRY_AXES",
    "TELEMETRY_AXIS_EDGE_FLOW",
    "TELEMETRY_AXIS_EDGE_POWER",
    "TELEMETRY_AXIS_EDGE_PUMP_SPEED",
    "TELEMETRY_AXIS_EDGE_STATUS",
    "TELEMETRY_AXIS_EDGE_VALVE_POSITION",
    "TELEMETRY_AXIS_NODE_DEMAND",
    "TELEMETRY_AXIS_NODE_LEVEL",
    "TELEMETRY_AXIS_NODE_PRESSURE",
    "TELEMETRY_AXIS_NODE_STATUS",
    "TELEMETRY_MEASUREMENTS",
    "TELEMETRY_MEASUREMENT_DEMAND",
    "TELEMETRY_MEASUREMENT_FLOW",
    "TELEMETRY_MEASUREMENT_LEVEL",
    "TELEMETRY_MEASUREMENT_POWER",
    "TELEMETRY_MEASUREMENT_PRESSURE",
    "TELEMETRY_MEASUREMENT_PUMP_SPEED",
    "TELEMETRY_MEASUREMENT_STATUS",
    "TELEMETRY_MEASUREMENT_VALVE_POSITION",
    "TELEMETRY_ROLES",
    "TELEMETRY_ROLE_CONTROL_INPUT",
    "TELEMETRY_ROLE_DERIVED",
    "TELEMETRY_ROLE_OBSERVED",
    "TELEMETRY_ROLE_QUALITY",
    "TELEMETRY_TARGET_EDGE",
    "TELEMETRY_TARGET_NODE",
    "TELEMETRY_TARGET_TYPES",
    "TelemetryTagMap",
    "TelemetryTagMapDiagnostics",
    "TelemetryTagSpec",
    "build_telemetry_tag_map",
    "load_telemetry_tag_map_json",
]
