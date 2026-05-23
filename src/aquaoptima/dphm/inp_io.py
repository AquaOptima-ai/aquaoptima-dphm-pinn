"""EPANET ``.inp`` topology loader for the dPHM :class:`Network`.

Sprint 11 adds optional EPANET/WNTR-style ``.inp`` topology import on
top of the Sprint 8 JSON loader, to widen the science gate's external
credibility without requiring a live EPANET engine or any field
adapter. The public surface is one function,
:func:`load_network_from_inp`, which returns the same
:class:`aquaoptima.dphm.Network` dataclass every other loader and
fixture in the project produces.

Sprint 16 extends the fallback parser to handle EPANET US-customary
flow units (``GPM``, ``CFS``, ``MGD``, ``IMGD``, ``AFD``) on top of
the SI family (``LPS``, ``LPM``, ``MLD``, ``CMH``, ``CMD``). All
conversion constants are captured in a single
:class:`EpanetUnitSystem` manifest so the parser never carries
ad-hoc per-section scaling. See :func:`resolve_unit_system` and the
shipped US fixtures under ``docs/examples/*_gpm.inp``.

Sprint 17 adds an orthogonal pressure-display unit axis through the
optional EPANET ``[OPTIONS] Pressure`` directive. The new
:class:`EpanetPressureUnit` manifest captures the conversion factor
from each supported pressure unit (``PSI``, ``KPA``, ``METERS``,
``M``, ``FEET``, ``FT``, ``BAR``) to metres of water head. When
``[OPTIONS] Pressure`` is present, the fallback parser uses the
explicit pressure-unit conversion for ``PRV`` valve settings instead
of the flow-unit family's head conversion; when absent, Sprint 16
behaviour is preserved. ``TCV`` settings (the dimensionless minor-
loss coefficient ``K``) and the ``MinorLoss`` column remain
dimensionless. See :func:`resolve_pressure_unit` and the shipped
``docs/examples/epanet_reference_prv_gpm_psi.inp`` fixture.

Sprint 18 adds fallback support for the optional EPANET
``[OPTIONS] Demand Multiplier`` directive. The directive declares a
single non-negative scalar that scales every junction's baseline
demand after the flow-unit conversion. The helper
:func:`resolve_demand_multiplier` returns the validated multiplier
(defaulting to ``1.0`` when absent). Both back-ends apply the
multiplier consistently: the fallback parser multiplies junction
demands inline; the WNTR adapter reads
``wn.options.hydraulic.demand_multiplier`` (WNTR exposes it as a
separate option and does not scale ``Junction.base_demand``) and
applies it the same way. Reservoir / tank fixed-heads, pipe / pump /
valve dimensions, pump HEAD curve points, TCV settings, and the
``MinorLoss`` column are NOT scaled by the multiplier. The POWER
pump nominal-flow anchor sees the multiplied demand because the
anchor is resolved after junction-demand normalisation. See
:func:`resolve_demand_multiplier` and the shipped
``docs/examples/epanet_reference_loop_gpm_demand_multiplier.inp``
fixture.

Sprint 20 adds fallback support for the optional EPANET
``[OPTIONS] Viscosity`` directive as a **parser-only** compatibility
feature. Viscosity is a kinematic-viscosity ratio relative to water at
20 °C; in EPANET it matters only for Darcy-Weisbach / Reynolds-based
friction models. The current dPHM core uses Hazen-Williams head loss,
which carries **no viscosity term** in its residual, so the directive
is parsed and validated but never propagated to any hydraulic output.
The helper :func:`resolve_viscosity` returns the validated value
(defaulting to ``1.0`` when absent); invalid values still raise
``ValueError`` so EPANET-produced fixtures remain fail-fast.
See :func:`resolve_viscosity` and ``docs/epanet-inp-import.md`` for
the explicit boundary.

Sprint 21 makes the fallback parser's ignored-section contract
explicit. The frozenset :data:`IGNORED_SECTIONS` is now a public
surface enumerating every EPANET section the parser deliberately
treats as a silent no-op (``[TIMES]``, ``[REPORT]``, ``[CONTROLS]``,
``[RULES]``, ``[EMITTERS]``, ``[QUALITY]``, ``[SOURCES]``,
``[REACTIONS]``, ``[MIXING]``, plus the inert layout sections
``[TITLE]``, ``[END]``, ``[PATTERNS]``, ``[COORDINATES]``,
``[VERTICES]``, ``[LABELS]``, ``[BACKDROP]``, ``[TAGS]``,
``[ENERGY]``, ``[DEMANDS]``). Adding any of these
sections to a fixture — anywhere in the file, with any
representative body, including malformed-looking rows — must leave
the loaded :class:`Network` byte-for-byte unchanged. The constant is
documentation-as-code: the parser does not branch on membership,
it simply never consumes any section other than the hydraulically-
meaningful ones. ``[CURVES]`` is **not** in the set because Sprint
12's HEAD-curve pump translation reads it. ``[CONTROLS]`` and
``[RULES]`` are documented as a *known limitation* — rows that
would close a link, change a pump speed, or modify a fixed-head
boundary are dropped, not enforced. See
``docs/epanet-inp-import.md``.

Sprint 24 extends the Sprint 23 :class:`EpanetImportDiagnostics`
container with an ``ignored_sections`` field that records which
members of :data:`IGNORED_SECTIONS` were actually present in the
imported ``.inp`` file. Each presence produces one read-only
:class:`EpanetIgnoredSectionDiagnostic` (``section``, ``row_count``,
``message``) in source order. ``[STATUS]`` is excluded by
construction because Sprint 22 already removed it from
:data:`IGNORED_SECTIONS`; accepted ``OPEN`` rows continue to surface
through ``status_rows`` only. Sprint 24 does NOT activate any of the
ignored sections — they remain dropped on the floor at parse time;
the diagnostics are visibility only. The WNTR back-end has its own
ignored-section handling and is documented as fallback-authoritative;
``ignored_sections`` is left empty when ``parser="wntr"``.

Sprint 25 extends the same container with a ``control_rule_rows``
field that records the tokenised rows declared inside ``[CONTROLS]``
and ``[RULES]``. Each row produces one read-only
:class:`EpanetControlRuleDiagnostic` (``section``, ``row_index``,
``tokens``, ``text``, ``message``) in source order. The two channels
are complementary: ``ignored_sections`` still reports the presence
of every member of :data:`IGNORED_SECTIONS` at the section level
(including ``[CONTROLS]``, ``[RULES]``, ``[PATTERNS]``, ``[ENERGY]``,
…), while ``control_rule_rows`` adds per-row content visibility for
``[CONTROLS]`` and ``[RULES]`` only. Other ignored sections do not
surface per-row content — the dPHM importer has no use for
``[PATTERNS]`` / ``[ENERGY]`` row content, so leaving them at the
section level keeps the diagnostics surface narrow. Sprint 25 does
NOT activate any control or rule logic — the rows remain dropped on
the floor at parse time, the loaded :class:`Network` is byte-for-byte
identical to one loaded from a fixture with no ``[CONTROLS]`` /
``[RULES]`` block, and the Sprint 22 ``[STATUS]`` rejection behaviour
is preserved. The WNTR back-end is documented as
fallback-authoritative; ``control_rule_rows`` is left empty when
``parser="wntr"``. Records are *tokenised parser rows*, not semantic
EPANET rule blocks — an EPANET multi-line ``RULE`` /
``IF`` / ``THEN`` … block surfaces as one record per line.

Sprint 28 extends the same container with an ``emitter_demand_rows``
field that records the tokenised rows declared inside ``[EMITTERS]``
and ``[DEMANDS]``. Each row produces one read-only
:class:`EpanetEmitterDemandDiagnostic` (``section``, ``row_index``,
``tokens``, ``text``, ``message``) in source order. The three per-row
channels are complementary: ``control_rule_rows`` carries
``[CONTROLS]`` / ``[RULES]`` content (Sprint 25, with the Sprint 27
``kind`` classification on top), ``pattern_energy_rows`` carries
``[PATTERNS]`` / ``[ENERGY]`` content (Sprint 26), and
``emitter_demand_rows`` carries ``[EMITTERS]`` / ``[DEMANDS]`` content
(Sprint 28). Every other member of :data:`IGNORED_SECTIONS` continues
to surface only at the section level through ``ignored_sections``.
Sprint 28 does NOT activate any emitter / leakage or demand-category
semantics — the rows remain dropped on the floor at parse time, the
loaded :class:`Network` is byte-for-byte identical to one loaded from
a fixture with no ``[EMITTERS]`` / ``[DEMANDS]`` block, and the
Sprint 22 ``[STATUS]`` rejection behaviour is preserved. The WNTR
back-end is documented as fallback-authoritative;
``emitter_demand_rows`` is left empty when ``parser="wntr"``. Records
are *tokenised parser rows*, not semantic EPANET emitter / demand
evaluation — an EPANET ``DEMANDS`` row with multiple optional columns
(``junction_id``, ``base_demand``, ``pattern_id``, ``category``)
surfaces as one record with the file's exact token order preserved.

Sprint 29 extends the same container with a ``water_quality_rows``
field that records the tokenised rows declared inside the four
water-quality-family ignored sections: ``[QUALITY]``, ``[SOURCES]``,
``[REACTIONS]``, and ``[MIXING]``. Each row produces one read-only
:class:`EpanetWaterQualityDiagnostic` (``section``, ``row_index``,
``tokens``, ``text``, ``message``) in source order. With Sprint 29,
the four per-row channels collectively cover every content-bearing
member of :data:`IGNORED_SECTIONS`: ``control_rule_rows`` for
``[CONTROLS]`` / ``[RULES]``, ``pattern_energy_rows`` for
``[PATTERNS]`` / ``[ENERGY]``, ``emitter_demand_rows`` for
``[EMITTERS]`` / ``[DEMANDS]``, and ``water_quality_rows`` for
``[QUALITY]`` / ``[SOURCES]`` / ``[REACTIONS]`` / ``[MIXING]``.
Sprint 29 does NOT activate any water-quality simulation, source
injection, reaction / decay, or tank-mixing semantics — the rows
remain dropped on the floor at parse time, the loaded
:class:`Network` is byte-for-byte identical to one loaded from a
fixture with no water-quality block, and the Sprint 22 ``[STATUS]``
rejection behaviour is preserved. The WNTR back-end is documented
as fallback-authoritative; ``water_quality_rows`` is left empty
when ``parser="wntr"``. Records are *tokenised parser rows*, not
semantic EPANET water-quality evaluation.

Sprint 22 narrows the Sprint 21 contract for ``[STATUS]``. Through
Sprint 21 the section was a global no-op; from Sprint 22 onwards the
fallback parser actively validates ``[STATUS]`` rows so EPANET-exported
fixtures that include explicit ``<link_id> OPEN`` declarations load
without pretending to implement closed-link or active status physics:

* ``<link_id> OPEN`` (case-insensitive, extra whitespace tolerated) is
  accepted as a redundant no-op — every link the fallback parser loads
  is already implicitly open, so accepted rows leave the loaded
  :class:`Network` byte-for-byte identical to the same fixture with
  no ``[STATUS]`` section.
* The link id is validated against the union of parsed
  ``[PIPES]``/``[PUMPS]``/``[VALVES]`` ids; references to an unknown
  id raise :class:`ValueError` with the id in the message.
* ``CLOSED`` and ``CV`` still raise — the steady-state core does not
  model closed links or check valves.
* Numeric pump speed / status declarations (e.g. ``PU1 1.0``) raise —
  the steady-state core does not consume per-link speed multipliers
  from ``[STATUS]``.
* Any other unsupported token raises with the link id and the
  offending token in the message.

The per-row ``[PIPES] ... CLOSED`` / ``CV`` status column (validated in
the pipe-row loop) is unchanged — Sprint 22 only adds standalone
``[STATUS]``-section handling. ``STATUS`` is therefore removed from
:data:`IGNORED_SECTIONS`. See :func:`_validate_status_rows` and
``docs/epanet-inp-import.md``.

Sprint 19 adds fallback support for the optional EPANET
``[OPTIONS] Specific Gravity`` directive. The directive declares a
single strictly-positive scalar describing the ratio of fluid density
to water (e.g. ``2.0`` for a brine roughly twice as dense as water).
The helper :func:`resolve_specific_gravity` returns the validated
value (defaulting to ``1.0`` when absent). The specific gravity is
propagated to the two places where fluid density appears in the
fallback importer:

* PRV ``[OPTIONS] Pressure`` conversion for true pressure units
  (``PSI``, ``KPA``, ``BAR``) — the metres of *fluid* head needed to
  produce the declared pressure is ``head_m = p * pressure_to_head_m
  / sg``. Head-length pressure aliases (``METERS``, ``M``, ``FEET``,
  ``FT``) are already length units and are NOT scaled.
* POWER pump surrogate — the effective density used by
  ``H_nom = P / (rho_eff * g * Q_nom)`` is ``rho_water * sg``. The
  helper :func:`fit_power_pump_surrogate` exposes a keyword-only
  ``specific_gravity`` argument so the fallback parser can apply it
  inline.

The directive does NOT scale junction elevations, head-curve pump
coefficients, TCV settings / minor loss, demand multiplier, or any
geometric dimension. The WNTR adapter is left structurally unchanged
because WNTR's handling of ``Specific Gravity`` across releases is
ambiguous; the fallback parser is authoritative for Sprint 19 SG
behaviour. See :func:`resolve_specific_gravity` and
``docs/epanet-inp-import.md`` for the explicit assumptions.

Sprint 12 extends the fallback parser to additionally translate
EPANET ``HEAD``-curve pumps into dPHM pump-affinity quadratic
coefficients. The translation fits the EPANET curve points to the
dPHM quadratic ``H(Q, s) = a0 s^2 + a1 s Q + a2 Q^2`` at the static
nominal speed ``s = 1`` via least squares; see
:func:`fit_pump_head_curve` for the public helper.

Sprint 13 brings the WNTR-backed parser into parity with the
fallback parser for HEAD-curve pumps. The WNTR adapter now iterates
``wn.pump_name_list`` and translates each pump via the same
:func:`fit_pump_head_curve` helper, reading WNTR's already-SI curve
points so no second unit conversion is applied.

Sprint 14 extends both the fallback and WNTR adapters to accept
EPANET ``POWER`` pumps via a deliberately conservative quadratic
surrogate. A constant-power declaration ``P = rho * g * Q * H``
carries no head-flow curve, so the surrogate is anchored on a single
nominal-flow point and forced to droop with a documented shut-off
multiplier. The translation is exposed publicly as
:func:`fit_power_pump_surrogate` and is *not* a faithful
constant-power conversion — see the helper docstring and
``docs/epanet-inp-import.md`` for the explicit assumptions and
limitations. Non-HEAD, non-POWER pump forms (``SPEED``, custom)
still raise :class:`ValueError`.

Sprint 15 adds a conservative ``[VALVES]`` translator for the two
steady-state-compatible valve forms ``PRV`` (pressure-reducing
valve) and ``TCV`` (throttle control valve). The dPHM core does not
model active valve-control state as a first-class hydraulic
constraint, so the Sprint 15 valve import is deliberately limited:

* ``PRV`` rows pin the downstream node to a fixed-head boundary
  equal to ``elev_downstream + setting`` (a *pressure-boundary*
  surrogate). The PRV edge itself becomes a short, permissive,
  pipe-like edge. This is NOT a faithful PRV — the demand /
  pressure-regulation invariant is not enforced. See
  :func:`translate_valve_to_surrogate` and
  ``docs/epanet-inp-import.md`` for the explicit assumptions.
* ``TCV`` rows become pipe-like resistance edges whose effective
  Hazen-Williams length is sized to reproduce the minor-loss head
  loss ``K * V^2 / (2 g)`` at one anchor flow. The helper
  :func:`fit_tcv_resistance_surrogate` is exposed publicly.

Unsupported valve forms (``FCV``, ``PSV``, ``PBV``, ``GPV``) still
raise :class:`ValueError`, with the valve id in the message.

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
  ``[BACKDROP]``, ``[TAGS]``, ``[ENERGY]``,
  ``[CONTROLS]``, ``[RULES]``, ``[EMITTERS]``,
  ``[DEMANDS]``, ``[QUALITY]``, ``[SOURCES]``, ``[REACTIONS]``,
  ``[MIXING]`` — silently ignored (steady-state hydraulic topology
  only).
* ``[STATUS]`` — Sprint 22: validated. Accepts ``<link_id> OPEN``
  rows as no-ops; rejects ``CLOSED``, ``CV``, numeric pump
  speed/status, and any other token. Unknown link ids also raise.
* ``[CURVES]`` — Sprint 12: parsed into per-curve ``(Q, H)`` point
  lists in the file-declared flow unit. Only consumed when a
  ``[PUMPS]`` row references the curve via ``HEAD curve_id``; unused
  curves are accepted but otherwise ignored.

Sections that intentionally **fail loudly**:

* ``[PUMPS]`` — Sprint 12 supports the ``HEAD curve_id`` form via
  least-squares quadratic curve fitting. Sprint 14 adds the
  ``POWER value`` form via the bounded surrogate
  :func:`fit_power_pump_surrogate`. Any other pump form
  (``SPEED``, custom) still raises :class:`ValueError`.
* ``[VALVES]`` — Sprint 15 supports the conservative ``PRV`` and
  ``TCV`` forms via :func:`translate_valve_to_surrogate`. Any
  other valve form (``FCV``, ``PSV``, ``PBV``, ``GPV``) raises
  :class:`ValueError`. The translation is approximate (pressure
  boundary for PRV, resistance surrogate for TCV) — see the
  helper docstrings and ``docs/epanet-inp-import.md`` for the
  documented limitations.

Unit conversion
---------------

EPANET picks per-flow-unit conventions for pipe length and diameter:

* **SI flow units** (``LPS``, ``LPM``, ``MLD``, ``CMH``, ``CMD``):
  length in metres, diameter in **millimetres**, head/elevation in
  metres.
* **US flow units** (``CFS``, ``GPM``, ``MGD``, ``IMGD``, ``AFD``):
  length in feet, diameter in inches, head/elevation in feet.

The fallback parser supports both families through
:class:`EpanetUnitSystem`. Demand is converted from the chosen flow
unit to m^3/s; diameter from mm or inches to m; length and head from
m or ft to m. PRV settings are interpreted as the head-units conversion
(feet of head for US, metres of head for SI) by default. Sprint 17:
when ``[OPTIONS] Pressure`` is set, the explicit pressure-unit
conversion (psi / kPa / bar / metres / feet) overrides that default
for PRV settings only. TCV settings (``K``) and ``MinorLoss`` are
dimensionless and never scaled.

If ``[OPTIONS]`` is absent or omits ``Units``, the parser assumes the
EPANET default of ``LPS``. If ``[OPTIONS] Pressure`` is absent, the
Sprint 16 contract applies (PRV settings follow the flow-unit
family's head conversion).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Union

import torch

from .network import Network


PathLike = Union[str, Path]


# --- unit handling ---------------------------------------------------------


# Exact NIST / EPANET-manual conversion constants. Keeping them as
# named symbols makes the unit manifest auditable in one place.
_FT_TO_M = 0.3048              # exact (international foot)
_IN_TO_M = 0.0254              # exact (international inch)
_US_GAL_TO_M3 = 0.003785411784  # exact (US liquid gallon, NIST HB-44)
_IMP_GAL_TO_M3 = 0.00454609     # exact (UK Weights & Measures Act 1985)
_ACRE_FOOT_TO_M3 = 1233.48183754752  # exact (international acre × international foot)
_DAY_S = 86_400.0
_MIN_S = 60.0
_HOUR_S = 3600.0


@dataclass(frozen=True)
class EpanetUnitSystem:
    """Per-flow-unit conversion manifest for the EPANET INP grammar.

    Captures every conversion the fallback parser needs in a single
    auditable object, so no ad-hoc constant scattering can drift.

    Attributes
    ----------
    units
        The canonical (upper-case) EPANET ``[OPTIONS] Units`` token,
        e.g. ``"LPS"`` or ``"GPM"``.
    flow_to_m3s
        Factor to multiply a file-declared flow/demand value to get
        m^3/s.
    length_to_m
        Factor to multiply a file-declared pipe length to get metres.
        Equal to ``1.0`` for SI flow units (already m) and ``0.3048``
        for US flow units (feet).
    diameter_to_m
        Factor to multiply a file-declared pipe/valve diameter to get
        metres. Equal to ``1e-3`` for SI flow units (mm) and ``0.0254``
        for US flow units (inches).
    head_to_m
        Factor to multiply a file-declared head / elevation value to
        get metres. Equal to ``1.0`` for SI flow units and ``0.3048``
        for US flow units.
    pressure_setting_to_m
        Factor to multiply a PRV/PSV/PBV setting to get metres of
        head. EPANET expresses pressure-valve settings in the head
        unit of the active flow-unit family, so this currently
        mirrors ``head_to_m``. Kept as a separate field so future
        sprints can switch to pressure-in-bar / psi if needed
        without disturbing the head-conversion path.
    """

    units: str
    flow_to_m3s: float
    length_to_m: float
    diameter_to_m: float
    head_to_m: float
    pressure_setting_to_m: float


_SI_FAMILY = ("LPS", "LPM", "MLD", "CMH", "CMD")
_US_FAMILY = ("CFS", "GPM", "MGD", "IMGD", "AFD")


_FLOW_TO_M3S: dict[str, float] = {
    "LPS": 1.0e-3,
    "LPM": 1.0 / 60_000.0,
    "MLD": 1_000.0 / _DAY_S,
    "CMH": 1.0 / _HOUR_S,
    "CMD": 1.0 / _DAY_S,
    "CFS": _FT_TO_M ** 3,
    "GPM": _US_GAL_TO_M3 / _MIN_S,
    "MGD": 1_000_000.0 * _US_GAL_TO_M3 / _DAY_S,
    "IMGD": 1_000_000.0 * _IMP_GAL_TO_M3 / _DAY_S,
    "AFD": _ACRE_FOOT_TO_M3 / _DAY_S,
}


SUPPORTED_FLOW_UNITS: tuple[str, ...] = _SI_FAMILY + _US_FAMILY


def _is_us_unit(unit: str) -> bool:
    return unit in _US_FAMILY


def resolve_unit_system(unit_name: str) -> EpanetUnitSystem:
    """Return the :class:`EpanetUnitSystem` for an EPANET unit token.

    The lookup is case-insensitive. EPANET-recognised but
    parser-unsupported tokens, and entirely unknown tokens, both
    raise :class:`ValueError` with a list of supported units.
    """
    canonical = str(unit_name).upper()
    if canonical not in _FLOW_TO_M3S:
        raise ValueError(
            f"unknown EPANET flow unit {unit_name!r}; supported units are "
            f"{SUPPORTED_FLOW_UNITS}"
        )
    is_us = _is_us_unit(canonical)
    length_to_m = _FT_TO_M if is_us else 1.0
    diameter_to_m = _IN_TO_M if is_us else 1.0e-3
    head_to_m = _FT_TO_M if is_us else 1.0
    return EpanetUnitSystem(
        units=canonical,
        flow_to_m3s=_FLOW_TO_M3S[canonical],
        length_to_m=length_to_m,
        diameter_to_m=diameter_to_m,
        head_to_m=head_to_m,
        pressure_setting_to_m=head_to_m,
    )


# --- pressure-unit handling (Sprint 17) ------------------------------------


# Standard water density and gravity used to convert any pressure
# unit to metres of water head. Mirrors the constants the Sprint 14
# POWER pump surrogate uses (``_POWER_PUMP_RHO`` and ``_POWER_PUMP_G``)
# so head conversions are arithmetically consistent across the module.
_PRESSURE_RHO = 1000.0   # kg/m^3 (water at ~20 C)
_PRESSURE_G = 9.80665    # m/s^2 (standard gravity)
_PA_PER_M_WATER = _PRESSURE_RHO * _PRESSURE_G  # 9806.65 Pa per metre

# Pressure-to-pascal factors for every supported pressure unit. The
# pascal pivot keeps the per-unit conversions auditable in one place;
# the metres-of-water-head factor is derived as ``pa / _PA_PER_M_WATER``.
_PSI_TO_PA = 6894.757293168    # exact (NIST, international foot-pound-second)
_KPA_TO_PA = 1000.0
_BAR_TO_PA = 100_000.0


@dataclass(frozen=True)
class EpanetPressureUnit:
    """EPANET ``[OPTIONS] Pressure`` pressure-unit manifest entry.

    Sprint 17 adds explicit pressure-unit support so PRV settings can
    be declared in psi / kPa / bar / metres / feet independently of
    the flow-unit family. Each manifest entry captures one factor:
    how many metres of water head one unit of the file-declared
    pressure equals.

    Attributes
    ----------
    name
        The canonical (upper-case) EPANET ``[OPTIONS] Pressure``
        token, e.g. ``"PSI"`` or ``"BAR"``.
    pressure_to_head_m
        Factor to multiply a file-declared pressure value to get
        metres of water head. Derived through a Pa pivot using
        ``rho = 1000 kg/m^3`` and ``g = 9.80665 m/s^2``:
        ``pressure_to_head_m = (Pa per unit) / (rho * g)``.
    """

    name: str
    pressure_to_head_m: float


# Pressure-unit table. ``METERS`` and ``M`` are aliases (both EPANET-
# recognised), as are ``FEET`` and ``FT``. The table is the single
# source of truth for both the manifest constants and the
# ``SUPPORTED_PRESSURE_UNITS`` tuple.
_PRESSURE_TO_HEAD_M: dict[str, float] = {
    "METERS": 1.0,
    "M": 1.0,
    "FEET": _FT_TO_M,
    "FT": _FT_TO_M,
    "KPA": _KPA_TO_PA / _PA_PER_M_WATER,
    "PSI": _PSI_TO_PA / _PA_PER_M_WATER,
    "BAR": _BAR_TO_PA / _PA_PER_M_WATER,
}


SUPPORTED_PRESSURE_UNITS: tuple[str, ...] = (
    "PSI", "KPA", "METERS", "M", "FEET", "FT", "BAR",
)


def resolve_pressure_unit(unit_name: str) -> EpanetPressureUnit:
    """Return the :class:`EpanetPressureUnit` for a pressure-unit token.

    The lookup is case-insensitive. Unknown tokens raise
    :class:`ValueError` listing the supported units.
    """
    canonical = str(unit_name).upper()
    if canonical not in _PRESSURE_TO_HEAD_M:
        raise ValueError(
            f"unknown EPANET pressure unit {unit_name!r}; supported units are "
            f"{SUPPORTED_PRESSURE_UNITS}"
        )
    return EpanetPressureUnit(
        name=canonical,
        pressure_to_head_m=_PRESSURE_TO_HEAD_M[canonical],
    )


# --- demand multiplier handling (Sprint 18) --------------------------------


# Canonical key used by the options parser to store the EPANET
# ``[OPTIONS] Demand Multiplier`` directive. The directive's key is
# unique among shipped EPANET options in carrying a space, so the
# fallback options parser stores it under the same canonical token
# the resolver consumes.
_DEMAND_MULTIPLIER_KEY = "DEMAND MULTIPLIER"

# EPANET's documented default for ``[OPTIONS] Demand Multiplier`` when
# the directive is absent. Matches the EPANET 2.2 user manual.
_DEFAULT_DEMAND_MULTIPLIER = 1.0


def resolve_demand_multiplier(opts: dict[str, str]) -> float:
    """Return the validated ``[OPTIONS] Demand Multiplier`` scalar.

    The EPANET ``[OPTIONS] Demand Multiplier`` directive declares a
    single non-negative scalar that scales every junction's baseline
    demand at load time. When the directive is absent, the EPANET
    default of ``1.0`` applies.

    Parameters
    ----------
    opts
        Normalised options map produced by the fallback parser's
        ``_parse_options``. The map stores the directive under the
        canonical key ``"DEMAND MULTIPLIER"`` (case-folded,
        whitespace-normalised) when present.

    Returns
    -------
    float
        The resolved multiplier. ``1.0`` when the directive is absent.

    Raises
    ------
    ValueError
        If the directive's value is non-numeric, non-finite (NaN or
        Inf), or strictly negative. ``0.0`` is accepted (loads a
        network with all-zero junction demand).
    """
    raw = opts.get(_DEMAND_MULTIPLIER_KEY)
    if raw is None or raw == "":
        return _DEFAULT_DEMAND_MULTIPLIER
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"[OPTIONS] Demand Multiplier value {raw!r} is not numeric"
        ) from exc
    if not math.isfinite(value):
        raise ValueError(
            f"[OPTIONS] Demand Multiplier must be finite, got {value}"
        )
    if value < 0.0:
        raise ValueError(
            f"[OPTIONS] Demand Multiplier must be non-negative, got {value}"
        )
    return value


# --- specific gravity handling (Sprint 19) ---------------------------------


# Canonical key used by the options parser to store the EPANET
# ``[OPTIONS] Specific Gravity`` directive. Like ``Demand Multiplier``,
# this is a two-word option key, so the fallback options parser stores
# it under a single canonical token.
_SPECIFIC_GRAVITY_KEY = "SPECIFIC GRAVITY"

# EPANET's documented default for ``[OPTIONS] Specific Gravity`` when
# the directive is absent. ``1.0`` corresponds to pure water at the
# standard density used elsewhere in this module.
_DEFAULT_SPECIFIC_GRAVITY = 1.0

# True pressure-unit tokens whose PRV setting depends on the fluid
# density (and therefore on the specific gravity). Head-length aliases
# (``METERS``, ``M``, ``FEET``, ``FT``) are length units already and
# are NOT scaled by specific gravity.
_TRUE_PRESSURE_UNITS = frozenset({"PSI", "KPA", "BAR"})


def resolve_specific_gravity(opts: dict[str, str]) -> float:
    """Return the validated ``[OPTIONS] Specific Gravity`` scalar.

    The EPANET ``[OPTIONS] Specific Gravity`` directive declares a
    single strictly-positive scalar describing the ratio of fluid
    density to that of water. When the directive is absent, the
    EPANET default of ``1.0`` applies (pure water).

    Parameters
    ----------
    opts
        Normalised options map produced by the fallback parser's
        ``_parse_options``. The map stores the directive under the
        canonical key ``"SPECIFIC GRAVITY"`` (case-folded,
        whitespace-normalised) when present.

    Returns
    -------
    float
        The resolved specific gravity. ``1.0`` when the directive is
        absent.

    Raises
    ------
    ValueError
        If the directive's value is non-numeric, non-finite (NaN or
        Inf), zero, or strictly negative. Specific gravity must be
        strictly positive — zero would imply zero-density fluid and
        would singularise the pressure-to-head and POWER-pump
        conversions that depend on it.
    """
    raw = opts.get(_SPECIFIC_GRAVITY_KEY)
    if raw is None or raw == "":
        return _DEFAULT_SPECIFIC_GRAVITY
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"[OPTIONS] Specific Gravity value {raw!r} is not numeric"
        ) from exc
    if not math.isfinite(value):
        raise ValueError(
            f"[OPTIONS] Specific Gravity must be finite, got {value}"
        )
    if value <= 0.0:
        raise ValueError(
            f"[OPTIONS] Specific Gravity must be strictly positive, got {value}"
        )
    return value


# --- viscosity handling (Sprint 20) ----------------------------------------


# Canonical key used by the options parser to store the EPANET
# ``[OPTIONS] Viscosity`` directive. Viscosity is a single-token option
# key, so the standard ``_parse_options`` single-token branch handles
# it without any multi-word special-casing.
_VISCOSITY_KEY = "VISCOSITY"

# EPANET's documented default for ``[OPTIONS] Viscosity`` when the
# directive is absent. ``1.0`` corresponds to pure water at ~20 °C,
# matching the kinematic-viscosity reference EPANET uses.
_DEFAULT_VISCOSITY = 1.0


def resolve_viscosity(opts: dict[str, str]) -> float:
    """Return the validated ``[OPTIONS] Viscosity`` scalar.

    The EPANET ``[OPTIONS] Viscosity`` directive declares a single
    strictly-positive scalar describing the ratio of fluid kinematic
    viscosity to that of water at 20 °C. When the directive is absent,
    the EPANET default of ``1.0`` applies.

    Sprint 20 is a **parser-only** sprint for this directive: the dPHM
    core uses Hazen-Williams head loss, which has no viscosity term in
    its residual, so the resolved value is validated but never
    propagated to any hydraulic field. The resolver still raises on
    invalid input so EPANET-produced fixtures fail fast (matching
    Sprint 18 / 19 behaviour for Demand Multiplier / Specific Gravity).

    Parameters
    ----------
    opts
        Normalised options map produced by the fallback parser's
        ``_parse_options``. The map stores the directive under the
        canonical key ``"VISCOSITY"`` (upper-cased) when present.

    Returns
    -------
    float
        The resolved viscosity ratio. ``1.0`` when the directive is
        absent.

    Raises
    ------
    ValueError
        If the directive's value is non-numeric, non-finite (NaN or
        Inf), zero, or strictly negative. Viscosity must be strictly
        positive — zero would imply an inviscid fluid (no friction in
        a Darcy-Weisbach formulation) and would singularise a Reynolds
        calculation if one were ever added.
    """
    raw = opts.get(_VISCOSITY_KEY)
    if raw is None or raw == "":
        return _DEFAULT_VISCOSITY
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"[OPTIONS] Viscosity value {raw!r} is not numeric"
        ) from exc
    if not math.isfinite(value):
        raise ValueError(
            f"[OPTIONS] Viscosity must be finite, got {value}"
        )
    if value <= 0.0:
        raise ValueError(
            f"[OPTIONS] Viscosity must be strictly positive, got {value}"
        )
    return value


# --- [STATUS] handling (Sprint 22, Sprint 23 diagnostics) ------------------


# Sprint 23: human-readable message attached to every accepted
# ``[STATUS] OPEN`` diagnostic record. Kept as a module-level constant so
# all accepted rows share the exact same message text — diffing two
# diagnostics records does not surface spurious string variation.
_STATUS_OPEN_NOOP_MESSAGE: str = (
    "OPEN accepted as a no-op; status-changing semantics are unsupported."
)


@dataclass(frozen=True)
class EpanetStatusDiagnostic:
    """Read-only record of one accepted ``[STATUS]`` row.

    Sprint 23 surfaces accepted ``[STATUS] OPEN`` declarations as
    metadata so analysts can see *what* status rows were present in
    an imported ``.inp`` file. Diagnostics are deliberately read-only
    and hydraulically inert — they do not change any field on the
    loaded :class:`Network`, and the surrogate ``[STATUS]`` rejection
    behaviour from Sprint 22 is unchanged: rejected rows raise
    :class:`ValueError` and never produce diagnostic records.

    Attributes
    ----------
    link_id
        The link identifier exactly as it appeared in the source
        ``[STATUS]`` row (no case folding — EPANET link ids are
        case-sensitive in the dPHM fallback parser).
    status
        The normalised status token. For Sprint 23 this is always the
        upper-case string ``"OPEN"``; case-insensitive ``open`` /
        ``Open`` / ``OPEN`` in the source file all normalise here.
    section
        Source section name. Always ``"STATUS"`` for the records this
        module emits. Kept as a field so a future sprint that emits
        diagnostics from other sections (e.g. ``[CONTROLS]`` if it is
        ever modelled) does not have to break the record shape.
    is_noop
        ``True`` when the row was accepted as a redundant no-op
        (Sprint 23: every accepted row sets this). The field exists so
        diagnostic consumers can filter without re-checking the
        status string.
    message
        Human-readable explanation of the read-only / no-op contract.
        Pinned to a single module-level string so the surface stays
        stable.
    """

    link_id: str
    status: str
    section: str = "STATUS"
    is_noop: bool = True
    message: str = _STATUS_OPEN_NOOP_MESSAGE


# Sprint 24: human-readable message attached to every
# ``EpanetIgnoredSectionDiagnostic`` record. Pinned to a single
# module-level string so the surface stays stable and so two diagnostic
# records do not surface spurious string variation.
_IGNORED_SECTION_NOOP_MESSAGE: str = (
    "Section present but ignored by the steady-state dPHM importer."
)


@dataclass(frozen=True)
class EpanetIgnoredSectionDiagnostic:
    """Read-only record of one ignored EPANET section present in a file.

    Sprint 24 surfaces which sections in :data:`IGNORED_SECTIONS` were
    actually declared in an imported ``.inp`` file so analysts can tell
    when a fixture carried unsupported semantics (``[CONTROLS]``,
    ``[RULES]``, ``[PATTERNS]``, ``[ENERGY]``, …) that the dPHM
    steady-state importer deliberately did not apply. The records are
    deliberately read-only and hydraulically inert — they do not change
    any field on the loaded :class:`Network`. The Sprint 21
    ignored-section no-op contract is unchanged: every section in
    :data:`IGNORED_SECTIONS` is still dropped on the floor; Sprint 24
    only makes the *presence* of those sections visible.

    Attributes
    ----------
    section
        The canonical (upper-case) EPANET section name, e.g.
        ``"CONTROLS"`` or ``"RULES"``. Matches the spelling in
        :data:`IGNORED_SECTIONS`.
    row_count
        Number of non-blank, comment-stripped rows the parser saw
        inside the section body. ``0`` for a bare header with no
        body. The parser does not validate the body — the count is
        purely informational.
    message
        Human-readable explanation of the ignored-section / no-op
        contract. Pinned to a single module-level string so the
        surface stays stable.
    """

    section: str
    row_count: int
    message: str = _IGNORED_SECTION_NOOP_MESSAGE


# Sprint 25: human-readable message attached to every
# ``EpanetControlRuleDiagnostic`` record. Pinned to a single module-level
# string so the surface stays stable and so two diagnostic records do not
# surface spurious string variation.
_CONTROL_RULE_ROW_NOOP_MESSAGE: str = (
    "Row present but ignored by the steady-state dPHM importer."
)


class EpanetControlKind(str, Enum):
    """Conservative, deterministic classification for a ``[CONTROLS]`` row.

    Sprint 27 adds a syntactic / link-type-aware tagging surface on top
    of the Sprint 25 per-row :class:`EpanetControlRuleDiagnostic`
    visibility channel. The four categories are intentionally narrow:
    they let analysts triage how many ``[CONTROLS]`` rows would target
    pumps, valves, or generic pipe links if the dPHM core ever modelled
    them, without claiming that the rows are interpreted or activated.

    Members
    -------
    LINK_SETTING
        The leading tokens are ``LINK <link_id> ...`` where ``link_id``
        resolves to a known **pipe** link in the parsed network. EPANET
        pipe ``[CONTROLS]`` rows (e.g. ``LINK P1 CLOSED IF NODE J1
        BELOW 10``) fall here.
    PUMP_SETTING
        The leading tokens are ``LINK <link_id> ...`` where ``link_id``
        resolves to a known **pump** link. Pump-targeting rows that
        would change pump speed or open/close a pump (e.g.
        ``LINK PU1 1.2 IF NODE J2 BELOW 5``) fall here.
    VALVE_SETTING
        The leading tokens are ``LINK <link_id> ...`` where ``link_id``
        resolves to a known **valve** link. Valve-targeting rows
        (e.g. ``LINK V1 OPEN IF NODE J3 BELOW 4``) fall here.
    UNKNOWN
        Anything else: ``[RULES]`` rows (always ``UNKNOWN`` because the
        importer does not interpret rule structure), ``[CONTROLS]`` rows
        whose leading token is not ``LINK``, ``[CONTROLS]`` rows whose
        link id is not declared anywhere in ``[PIPES]`` / ``[PUMPS]`` /
        ``[VALVES]``, and any short / malformed row that does not match
        the recognised syntactic shape. ``UNKNOWN`` rows are still
        accepted by the parser — the classification is diagnostic only,
        never a rejection trigger.

    The enum is a :class:`str` subclass, so ``rec.kind == "PUMP_SETTING"``
    and ``rec.kind == EpanetControlKind.PUMP_SETTING`` both succeed.
    """

    LINK_SETTING = "LINK_SETTING"
    PUMP_SETTING = "PUMP_SETTING"
    VALVE_SETTING = "VALVE_SETTING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EpanetControlRuleDiagnostic:
    """Read-only record of one ``[CONTROLS]`` or ``[RULES]`` parser row.

    Sprint 25 narrows the Sprint 24 ignored-section visibility surface
    for two ignored sections only — ``[CONTROLS]`` and ``[RULES]`` — by
    emitting one record per *tokenised parser row* inside those
    sections. Analysts can see the exact unsupported rows declared in
    an imported ``.inp`` file without changing any hydraulic field on
    the loaded :class:`Network`.

    Records are deliberately read-only and hydraulically inert. The
    Sprint 21 ignored-section no-op contract is unchanged: every
    ``[CONTROLS]`` / ``[RULES]`` row is still dropped on the floor at
    parse time. Sprint 25 only makes the *content* of those rows
    visible.

    Important: a record represents a single parser row as produced by
    :func:`_split_sections`, **not** a semantic EPANET rule block.
    EPANET rules span multiple lines (``RULE``, ``IF``, ``THEN`` …) and
    each line surfaces as its own record. This module does not
    interpret rule structure.

    Attributes
    ----------
    section
        The canonical (upper-case) section name, always one of
        ``"CONTROLS"`` or ``"RULES"``.
    row_index
        Zero-based row index within the section bucket
        :func:`_split_sections` produced. Resets per section; preserves
        source-file row order within each section.
    tokens
        The exact tokens :func:`_split_sections` extracted for the row,
        as a tuple of strings. Token order matches the source row.
        Comments (``; ...``) are stripped before tokenisation by the
        underlying tokeniser; blank rows are dropped (and therefore not
        surfaced).
    text
        Reconstructed single-space-joined row text, derived from
        ``tokens``. Comments are not preserved (the underlying
        tokeniser strips them before any record can be emitted).
    message
        Human-readable explanation of the ignored / no-op contract.
        Pinned to a single module-level string so the surface stays
        stable.
    kind
        Sprint 27 conservative classification of the row's leading
        tokens. One of the :class:`EpanetControlKind` values
        (``LINK_SETTING`` / ``PUMP_SETTING`` / ``VALVE_SETTING`` /
        ``UNKNOWN``) stored as a plain string for backwards-compatible
        ``str`` equality. Defaults to ``"UNKNOWN"`` so every Sprint
        25 / 26 caller that constructs a record without the keyword
        continues to work unchanged. The classification is diagnostic
        only — it never gates rejection and never mutates the loaded
        :class:`Network`. ``[RULES]`` rows always carry ``"UNKNOWN"``
        because the importer does not interpret rule structure.
    """

    section: str
    row_index: int
    tokens: tuple[str, ...]
    text: str
    message: str = _CONTROL_RULE_ROW_NOOP_MESSAGE
    kind: str = EpanetControlKind.UNKNOWN.value


# Sprint 26: human-readable message attached to every
# ``EpanetPatternEnergyDiagnostic`` record. Pinned to a single module-level
# string so the surface stays stable and so two diagnostic records do not
# surface spurious string variation.
_PATTERN_ENERGY_ROW_NOOP_MESSAGE: str = (
    "Row present but ignored by the steady-state dPHM importer."
)


# Sprint 28: human-readable message attached to every
# ``EpanetEmitterDemandDiagnostic`` record. Pinned to a single module-level
# string so the surface stays stable and so two diagnostic records do not
# surface spurious string variation. Identical wording to the Sprint 25 /
# Sprint 26 row-level messages so the analyst-facing visibility surface
# reads uniformly across channels.
_EMITTER_DEMAND_ROW_NOOP_MESSAGE: str = (
    "Row present but ignored by the steady-state dPHM importer."
)


# Sprint 29: human-readable message attached to every
# ``EpanetWaterQualityDiagnostic`` record. Pinned to a single module-level
# string so the surface stays stable and so two diagnostic records do not
# surface spurious string variation. Identical wording to the Sprint 25 /
# Sprint 26 / Sprint 28 row-level messages so the analyst-facing visibility
# surface reads uniformly across channels.
_WATER_QUALITY_ROW_NOOP_MESSAGE: str = (
    "Row present but ignored by the steady-state dPHM importer."
)


@dataclass(frozen=True)
class EpanetPatternEnergyDiagnostic:
    """Read-only record of one ``[PATTERNS]`` or ``[ENERGY]`` parser row.

    Sprint 26 narrows the Sprint 24 ignored-section visibility surface
    for two additional ignored sections — ``[PATTERNS]`` and
    ``[ENERGY]`` — by emitting one record per *tokenised parser row*
    inside those sections. Analysts can see the exact unsupported rows
    declared in an imported ``.inp`` file without changing any
    hydraulic field on the loaded :class:`Network`.

    Records are deliberately read-only and hydraulically inert. The
    Sprint 21 ignored-section no-op contract is unchanged: every
    ``[PATTERNS]`` / ``[ENERGY]`` row is still dropped on the floor at
    parse time. Sprint 26 only makes the *content* of those rows
    visible. ``[PATTERNS]`` time-varying demand support and ``[ENERGY]``
    energy-cost modelling remain deferred.

    Important: a record represents a single parser row as produced by
    :func:`_split_sections`, **not** a semantic EPANET pattern / energy
    evaluation. EPANET ``PATTERN``/``ENERGY`` declarations can span
    several syntactic forms (``GLOBAL PRICE``, ``PUMP <id> PRICE``,
    pattern-multiplier rows, etc.); this module does not interpret that
    structure and surfaces one record per tokenised parser row.

    Attributes
    ----------
    section
        The canonical (upper-case) section name, always one of
        ``"PATTERNS"`` or ``"ENERGY"``.
    row_index
        Zero-based row index within the section bucket
        :func:`_split_sections` produced. Resets per section; preserves
        source-file row order within each section.
    tokens
        The exact tokens :func:`_split_sections` extracted for the row,
        as a tuple of strings. Token order matches the source row.
        Comments (``; ...``) are stripped before tokenisation by the
        underlying tokeniser; blank rows are dropped (and therefore not
        surfaced).
    text
        Reconstructed single-space-joined row text, derived from
        ``tokens``. Comments are not preserved (the underlying
        tokeniser strips them before any record can be emitted).
    message
        Human-readable explanation of the ignored / no-op contract.
        Pinned to a single module-level string so the surface stays
        stable.
    """

    section: str
    row_index: int
    tokens: tuple[str, ...]
    text: str
    message: str = _PATTERN_ENERGY_ROW_NOOP_MESSAGE


@dataclass(frozen=True)
class EpanetEmitterDemandDiagnostic:
    """Read-only record of one ``[EMITTERS]`` or ``[DEMANDS]`` parser row.

    Sprint 28 narrows the Sprint 24 ignored-section visibility surface
    for two further ignored sections — ``[EMITTERS]`` and ``[DEMANDS]``
    — by emitting one record per *tokenised parser row* inside those
    sections. Analysts can see the exact unsupported emitter (pressure-
    dependent leakage coefficient) and demand-category rows declared in
    an imported ``.inp`` file without changing any hydraulic field on
    the loaded :class:`Network`.

    Records are deliberately read-only and hydraulically inert. The
    Sprint 21 ignored-section no-op contract is unchanged: every
    ``[EMITTERS]`` / ``[DEMANDS]`` row is still dropped on the floor at
    parse time. Sprint 28 only makes the *content* of those rows
    visible. Active pressure-dependent emitter / leakage modelling and
    multi-category / pattern-keyed demand parsing remain deferred.

    Important: a record represents a single parser row as produced by
    :func:`_split_sections`, **not** a semantic EPANET emitter or
    demand-category evaluation. EPANET ``EMITTERS`` rows declare a
    junction emitter coefficient (``junction_id``, ``coefficient``) and
    ``DEMANDS`` rows declare per-category demand entries
    (``junction_id``, ``base_demand``, optional ``pattern_id``,
    optional ``category``); this module does not interpret that
    structure and surfaces one record per tokenised parser row.

    Attributes
    ----------
    section
        The canonical (upper-case) section name, always one of
        ``"EMITTERS"`` or ``"DEMANDS"``.
    row_index
        Zero-based row index within the section bucket
        :func:`_split_sections` produced. Resets per section; preserves
        source-file row order within each section.
    tokens
        The exact tokens :func:`_split_sections` extracted for the row,
        as a tuple of strings. Token order matches the source row.
        Comments (``; ...``) are stripped before tokenisation by the
        underlying tokeniser; blank rows are dropped (and therefore not
        surfaced).
    text
        Reconstructed single-space-joined row text, derived from
        ``tokens``. Comments are not preserved (the underlying
        tokeniser strips them before any record can be emitted).
    message
        Human-readable explanation of the ignored / no-op contract.
        Pinned to a single module-level string so the surface stays
        stable.
    """

    section: str
    row_index: int
    tokens: tuple[str, ...]
    text: str
    message: str = _EMITTER_DEMAND_ROW_NOOP_MESSAGE


@dataclass(frozen=True)
class EpanetWaterQualityDiagnostic:
    """Read-only record of one ``[QUALITY]`` / ``[SOURCES]`` / ``[REACTIONS]`` / ``[MIXING]`` parser row.

    Sprint 29 narrows the Sprint 24 ignored-section visibility surface
    for the four remaining water-quality-family ignored sections —
    ``[QUALITY]``, ``[SOURCES]``, ``[REACTIONS]``, and ``[MIXING]`` —
    by emitting one record per *tokenised parser row* inside those
    sections. Analysts can see the exact unsupported water-quality
    initialisation, source, reaction, and tank-mixing rows declared in
    an imported ``.inp`` file without changing any hydraulic field on
    the loaded :class:`Network`.

    Records are deliberately read-only and hydraulically inert. The
    Sprint 21 ignored-section no-op contract is unchanged: every
    ``[QUALITY]`` / ``[SOURCES]`` / ``[REACTIONS]`` / ``[MIXING]`` row
    is still dropped on the floor at parse time. Sprint 29 only makes
    the *content* of those rows visible. Active water-quality
    simulation, source injection semantics, reaction / decay modelling,
    and tank-mixing modelling remain deferred.

    Important: a record represents a single parser row as produced by
    :func:`_split_sections`, **not** a semantic EPANET water-quality
    evaluation. EPANET ``QUALITY`` rows declare an initial-quality
    value per node; ``SOURCES`` rows declare a source type / strength
    per node; ``REACTIONS`` rows declare bulk and wall reaction
    coefficients (or global directives like ``ORDER BULK``, ``GLOBAL
    BULK``, ``LIMITING POTENTIAL``); ``MIXING`` rows declare a tank
    mixing model (``MIXED``, ``2COMP``, ``FIFO``, ``LIFO``) with an
    optional fraction. This module does not interpret any of that
    structure and surfaces one record per tokenised parser row.

    Attributes
    ----------
    section
        The canonical (upper-case) section name, always one of
        ``"QUALITY"``, ``"SOURCES"``, ``"REACTIONS"``, or ``"MIXING"``.
    row_index
        Zero-based row index within the section bucket
        :func:`_split_sections` produced. Resets per section; preserves
        source-file row order within each section.
    tokens
        The exact tokens :func:`_split_sections` extracted for the row,
        as a tuple of strings. Token order matches the source row.
        Comments (``; ...``) are stripped before tokenisation by the
        underlying tokeniser; blank rows are dropped (and therefore not
        surfaced).
    text
        Reconstructed single-space-joined row text, derived from
        ``tokens``. Comments are not preserved (the underlying
        tokeniser strips them before any record can be emitted).
    message
        Human-readable explanation of the ignored / no-op contract.
        Pinned to a single module-level string so the surface stays
        stable.
    """

    section: str
    row_index: int
    tokens: tuple[str, ...]
    text: str
    message: str = _WATER_QUALITY_ROW_NOOP_MESSAGE


@dataclass(frozen=True)
class EpanetImportDiagnostics:
    """Read-only container for EPANET ``.inp`` import diagnostics.

    Sprint 23 populated ``status_rows`` (one record per accepted
    ``[STATUS] OPEN`` row). Sprint 24 added ``ignored_sections`` (one
    record per :data:`IGNORED_SECTIONS` entry that was actually present
    in the file, in source order). Sprint 25 added ``control_rule_rows``
    (one record per tokenised row inside a ``[CONTROLS]`` or
    ``[RULES]`` section, in source order). Sprint 26 added
    ``pattern_energy_rows`` (one record per tokenised row inside a
    ``[PATTERNS]`` or ``[ENERGY]`` section, in source order). Sprint 28
    added ``emitter_demand_rows`` (one record per tokenised row inside
    an ``[EMITTERS]`` or ``[DEMANDS]`` section, in source order).
    Sprint 29 adds ``water_quality_rows`` (one record per tokenised row
    inside a ``[QUALITY]``, ``[SOURCES]``, ``[REACTIONS]``, or
    ``[MIXING]`` section, in source order). Future sprints may grow
    additional fields — adding a new optional field with a default
    value is backwards-compatible for keyword-only callers.

    The container is ``frozen=True`` and every tuple field is a
    :class:`tuple` rather than a list so the diagnostics surface is
    structurally read-only. Attempting to reassign a field raises
    :class:`dataclasses.FrozenInstanceError`.
    """

    status_rows: tuple[EpanetStatusDiagnostic, ...] = ()
    ignored_sections: tuple[EpanetIgnoredSectionDiagnostic, ...] = ()
    control_rule_rows: tuple[EpanetControlRuleDiagnostic, ...] = ()
    pattern_energy_rows: tuple[EpanetPatternEnergyDiagnostic, ...] = ()
    emitter_demand_rows: tuple[EpanetEmitterDemandDiagnostic, ...] = ()
    water_quality_rows: tuple[EpanetWaterQualityDiagnostic, ...] = ()


# Status tokens the Sprint 22 ``[STATUS]`` validator accepts as no-ops.
# The only accepted state is ``OPEN`` — every pipe/pump/valve loaded by
# the fallback parser is already implicitly open, so a row of the form
# ``<link_id> OPEN`` is a documented redundant declaration that
# EPANET-exported files often emit. Validating the link id is still
# meaningful: a ``[STATUS]`` row that references a link the file never
# declared is a structural error in the source fixture and would be
# silently swallowed under the Sprint 21 ignored-section contract.
_STATUS_ACCEPTED_TOKENS: frozenset[str] = frozenset({"OPEN"})

# EPANET ``[STATUS]`` tokens with closed-link / check-valve semantics.
# Both are deliberately rejected because the dPHM steady-state core
# models only OPEN links; importing either would silently change the
# network's hydraulics (a closed pipe drops out of the flow equation,
# a check valve adds a sign-restricted unilateral edge), so we fail
# loudly to keep the boundary explicit. See the Sprint 22 report and
# ``docs/epanet-inp-import.md`` for the documented limitation.
_STATUS_REJECTED_LINK_TOKENS: frozenset[str] = frozenset({"CLOSED", "CV"})


def _validate_status_rows(
    rows: list[list[str]], known_link_ids: set[str]
) -> tuple[EpanetStatusDiagnostic, ...]:
    """Validate ``[STATUS]`` rows and emit Sprint 23 diagnostics.

    Sprint 22 narrows the Sprint 21 ignored-section contract for
    ``[STATUS]``: rows of the form ``<link_id> OPEN`` (case-insensitive)
    are accepted as redundant no-ops on top of the parser's default
    "every link is open" assumption, while ``CLOSED``, ``CV``, numeric
    pump speed/status declarations, and any other unsupported token
    raise :class:`ValueError` with the link id and the offending token
    in the message. The link id itself is also validated — a ``[STATUS]``
    row that references an id the file never declared in
    ``[PIPES]``/``[PUMPS]``/``[VALVES]`` is a structural error in the
    source fixture and fails loudly.

    Sprint 23 extends the validator to return one
    :class:`EpanetStatusDiagnostic` per accepted ``OPEN`` row so the
    public :func:`load_inp_diagnostics` entry point can surface read-
    only metadata about what status rows the file declared. The
    diagnostic records preserve the source link-id spelling and
    normalise the status token to upper-case ``"OPEN"``; rejected
    rows still raise before any diagnostic can be emitted (so a
    block mixing OPEN and CLOSED rows raises with no partial
    diagnostics leaking out).

    The function is intentionally read-only: accepted rows are no-ops
    and the loaded :class:`Network` is byte-for-byte identical to the
    same fixture without ``[STATUS]``. The ``[PIPES] ... CLOSED`` /
    ``CV`` per-row status column (validated in the pipe-row loop)
    continues to raise as it did in earlier sprints; this validator
    only governs the standalone ``[STATUS]`` section.

    Parameters
    ----------
    rows
        Tokenised ``[STATUS]`` rows from :func:`_split_sections`. May be
        empty (the section is optional). Each row must have at least
        two tokens: the link id and the status token.
    known_link_ids
        Set of link ids the fallback parser has already registered
        across ``[PIPES]``, ``[PUMPS]``, and ``[VALVES]``. Status rows
        are validated *after* every link is known so the order of
        ``[STATUS]`` relative to those sections does not matter.

    Returns
    -------
    tuple of EpanetStatusDiagnostic
        Sprint 23: one record per accepted ``<link_id> OPEN`` row, in
        source order. Empty when no ``[STATUS]`` rows were declared or
        when the section is empty.

    Raises
    ------
    ValueError
        On short rows (< 2 tokens), unknown link ids, ``CLOSED`` / ``CV``
        tokens, numeric pump speed/status values, or any other
        unsupported token. The error message names ``[STATUS]``, the
        link id, and the offending token. Rejected rows abort the
        validator before any diagnostic record is appended.
    """
    diagnostics: list[EpanetStatusDiagnostic] = []
    for row in rows:
        if len(row) < 2:
            raise ValueError(
                f"[STATUS] row needs at least 2 tokens (link_id, status), "
                f"got {row!r}"
            )
        link_id = row[0]
        status_raw = row[1]
        status_word = status_raw.upper()
        if link_id not in known_link_ids:
            raise ValueError(
                f"[STATUS] row references unknown link id {link_id!r}; the "
                "link must be declared in [PIPES], [PUMPS], or [VALVES] "
                "before its status can be set"
            )
        if status_word in _STATUS_ACCEPTED_TOKENS:
            diagnostics.append(
                EpanetStatusDiagnostic(link_id=link_id, status=status_word)
            )
            continue
        if status_word in _STATUS_REJECTED_LINK_TOKENS:
            raise ValueError(
                f"[STATUS] row for link {link_id!r} uses unsupported "
                f"status token {status_raw!r}; the dPHM steady-state core "
                "models only OPEN links (CLOSED and CV are deferred)"
            )
        # Numeric pump speed / status (e.g. ``PU1 1.0`` or ``PU1 0``) is
        # an EPANET shape we explicitly do not support — the steady-state
        # core does not consume per-link speed multipliers from [STATUS].
        try:
            float(status_raw)
        except ValueError:
            pass
        else:
            raise ValueError(
                f"[STATUS] row for link {link_id!r} declares a numeric "
                f"pump speed/status {status_raw!r}; the dPHM steady-state "
                "core does not model pump speed changes from [STATUS]"
            )
        raise ValueError(
            f"[STATUS] row for link {link_id!r} uses unsupported status "
            f"token {status_raw!r}; the only accepted token is OPEN "
            "(case-insensitive)"
        )
    return tuple(diagnostics)


def _collect_ignored_section_diagnostics(
    sections: dict[str, list[list[str]]],
) -> tuple[EpanetIgnoredSectionDiagnostic, ...]:
    """Surface which :data:`IGNORED_SECTIONS` were present in the file.

    Sprint 24 — read-only visibility surface for ignored sections.

    Walks the per-section tokenised rows produced by
    :func:`_split_sections` and emits one
    :class:`EpanetIgnoredSectionDiagnostic` for every section header
    that is both:

    * declared in the source file, **and**
    * a member of :data:`IGNORED_SECTIONS`.

    Records are emitted in the order the corresponding section headers
    first appear in the source file — :func:`_split_sections` is built
    on a regular :class:`dict`, which preserves insertion order on
    Python 3.7+. A bare header with an empty body still produces a
    diagnostic with ``row_count = 0`` because the file declared the
    section. Sections that appear multiple times in the file are
    collapsed into a single diagnostic whose ``row_count`` reflects the
    total number of rows ``_split_sections`` accumulated.

    ``[STATUS]`` is **not** surfaced here even when present: Sprint 22
    removed it from :data:`IGNORED_SECTIONS` and accepted ``OPEN`` rows
    flow through the Sprint 23 ``status_rows`` channel instead. Active
    hydraulic sections (``[JUNCTIONS]``, ``[PIPES]``, ``[OPTIONS]``,
    ``[CURVES]``, …) are excluded by construction because they are not
    in :data:`IGNORED_SECTIONS`.

    The helper is read-only: it never mutates the ``sections`` mapping
    and never affects parsing outcomes.
    """
    records: list[EpanetIgnoredSectionDiagnostic] = []
    for name, rows in sections.items():
        if name not in IGNORED_SECTIONS:
            continue
        records.append(
            EpanetIgnoredSectionDiagnostic(
                section=name,
                row_count=len(rows),
            )
        )
    return tuple(records)


# Sprint 25: the only two ignored sections that surface per-row through
# :class:`EpanetControlRuleDiagnostic`. All other members of
# :data:`IGNORED_SECTIONS` (``[PATTERNS]``, ``[ENERGY]``, ``[TIMES]``,
# ``[REPORT]``, …) still surface only at the section level through
# :class:`EpanetIgnoredSectionDiagnostic`.
_CONTROL_RULE_SECTIONS: tuple[str, ...] = ("CONTROLS", "RULES")


def _classify_control_row(
    tokens: tuple[str, ...],
    *,
    pipe_ids: frozenset[str],
    pump_ids: frozenset[str],
    valve_ids: frozenset[str],
) -> EpanetControlKind:
    """Classify one ``[CONTROLS]`` row by leading tokens + link-type context.

    Sprint 27 syntactic / link-type-aware classifier. Conservative and
    deterministic: any row that does not match the recognised
    ``LINK <link_id> ...`` shape, or whose link id is not declared in
    the parsed network's pipes / pumps / valves, falls back to
    :data:`EpanetControlKind.UNKNOWN`. Classification never raises and
    never has hydraulic side effects.

    The classifier intentionally does **not** evaluate EPANET conditions
    (``IF NODE ... BELOW``, ``IF TIME``, ``AT TIME``, ``AT CLOCKTIME``)
    or interpret setting values. Two ``LINK PU1 ...`` rows that differ
    only in their condition body classify identically as
    ``PUMP_SETTING`` because they target the same pump.

    Parameters
    ----------
    tokens
        Parser tokens for the row, with comments stripped. May be empty
        — the classifier handles every malformed shape conservatively.
    pipe_ids
        Set of pipe ids declared in ``[PIPES]``.
    pump_ids
        Set of pump ids declared in ``[PUMPS]``.
    valve_ids
        Set of valve ids declared in ``[VALVES]``.

    Returns
    -------
    EpanetControlKind
        The classification.
    """
    if len(tokens) < 2:
        return EpanetControlKind.UNKNOWN
    if tokens[0].upper() != "LINK":
        return EpanetControlKind.UNKNOWN
    link_id = tokens[1]
    # Pump / valve / pipe lookups are case-sensitive: EPANET link ids
    # are case-sensitive in the dPHM fallback parser and the registered
    # id sets are built from the same source tokens.
    if link_id in pump_ids:
        return EpanetControlKind.PUMP_SETTING
    if link_id in valve_ids:
        return EpanetControlKind.VALVE_SETTING
    if link_id in pipe_ids:
        return EpanetControlKind.LINK_SETTING
    return EpanetControlKind.UNKNOWN


def _collect_control_rule_row_diagnostics(
    sections: dict[str, list[list[str]]],
    *,
    pipe_ids: frozenset[str] = frozenset(),
    pump_ids: frozenset[str] = frozenset(),
    valve_ids: frozenset[str] = frozenset(),
) -> tuple[EpanetControlRuleDiagnostic, ...]:
    """Surface every tokenised row inside ``[CONTROLS]`` / ``[RULES]``.

    Sprint 25 — read-only visibility surface for the contents of the two
    ignored sections most often carried by EPANET-exported fixtures.

    Walks the per-section tokenised rows produced by
    :func:`_split_sections` and emits one
    :class:`EpanetControlRuleDiagnostic` for every row inside a
    ``[CONTROLS]`` or ``[RULES]`` section. Records appear in source-file
    order: section ordering follows :func:`_split_sections`' dict
    iteration order (which preserves first-appearance source order),
    and within each section ``row_index`` is the 0-based index into the
    section's accumulated row list.

    Sprint 27 extends the helper with a conservative ``kind``
    classification on each emitted record. The classification is
    syntactic and link-type-aware: ``[CONTROLS]`` rows are tagged via
    :func:`_classify_control_row` against the declared pipe / pump /
    valve id sets; ``[RULES]`` rows always classify as
    :data:`EpanetControlKind.UNKNOWN` because the importer does not
    interpret rule structure beyond per-row visibility. The
    classification is diagnostic only; it never gates rejection.

    The helper deliberately excludes every other ignored section
    (``[PATTERNS]``, ``[ENERGY]``, ``[TIMES]``, ``[REPORT]``,
    ``[EMITTERS]``, ``[QUALITY]``, ``[SOURCES]``, ``[REACTIONS]``,
    ``[MIXING]``, ``[DEMANDS]``, and the inert layout sections). Those
    remain visible only through :class:`EpanetIgnoredSectionDiagnostic`.

    ``[STATUS]`` is also excluded — Sprint 22 removed it from
    :data:`IGNORED_SECTIONS` entirely, and accepted ``OPEN`` rows flow
    through the Sprint 23 ``status_rows`` channel instead.

    The helper is read-only: it never mutates the ``sections`` mapping
    and never affects parsing outcomes. Blank rows and inline ``;``
    comments are not surfaced because :func:`_split_sections` already
    strips them before any row enters the per-section bucket.

    Parameters
    ----------
    sections
        Per-section tokenised rows from :func:`_split_sections`.
    pipe_ids, pump_ids, valve_ids
        Sprint 27 link-type context. When omitted (empty
        :class:`frozenset` defaults) every ``[CONTROLS]`` row falls back
        to :data:`EpanetControlKind.UNKNOWN`, which is the conservative
        default for callers that do not have the parsed-network context
        on hand.
    """
    records: list[EpanetControlRuleDiagnostic] = []
    for name, rows in sections.items():
        if name not in _CONTROL_RULE_SECTIONS:
            continue
        for idx, row in enumerate(rows):
            tokens = tuple(row)
            if name == "CONTROLS":
                kind = _classify_control_row(
                    tokens,
                    pipe_ids=pipe_ids,
                    pump_ids=pump_ids,
                    valve_ids=valve_ids,
                )
            else:
                # [RULES] rows are never semantically classified —
                # multi-line EPANET rules carry semantics across lines
                # and the dPHM importer does not interpret that
                # structure. Stay conservative.
                kind = EpanetControlKind.UNKNOWN
            records.append(
                EpanetControlRuleDiagnostic(
                    section=name,
                    row_index=idx,
                    tokens=tokens,
                    text=" ".join(tokens),
                    kind=kind.value,
                )
            )
    return tuple(records)


# Sprint 26: the only two ignored sections that surface per-row through
# :class:`EpanetPatternEnergyDiagnostic`. All other members of
# :data:`IGNORED_SECTIONS` (``[TIMES]``, ``[REPORT]``, ``[EMITTERS]``,
# …) still surface only at the section level through
# :class:`EpanetIgnoredSectionDiagnostic`. ``[CONTROLS]`` and ``[RULES]``
# remain in their dedicated Sprint 25 channel (see
# :func:`_collect_control_rule_row_diagnostics`).
_PATTERN_ENERGY_SECTIONS: tuple[str, ...] = ("PATTERNS", "ENERGY")


def _collect_pattern_energy_row_diagnostics(
    sections: dict[str, list[list[str]]],
) -> tuple[EpanetPatternEnergyDiagnostic, ...]:
    """Surface every tokenised row inside ``[PATTERNS]`` / ``[ENERGY]``.

    Sprint 26 — read-only visibility surface for the contents of the two
    ignored sections that most often carry per-row content in EPANET-
    exported fixtures alongside ``[CONTROLS]`` / ``[RULES]``.

    Walks the per-section tokenised rows produced by
    :func:`_split_sections` and emits one
    :class:`EpanetPatternEnergyDiagnostic` for every row inside a
    ``[PATTERNS]`` or ``[ENERGY]`` section. Records appear in
    source-file order: section ordering follows :func:`_split_sections`'
    dict iteration order (which preserves first-appearance source
    order), and within each section ``row_index`` is the 0-based index
    into the section's accumulated row list.

    The helper deliberately excludes every other ignored section
    (``[CONTROLS]``, ``[RULES]``, ``[TIMES]``, ``[REPORT]``,
    ``[EMITTERS]``, ``[QUALITY]``, ``[SOURCES]``, ``[REACTIONS]``,
    ``[MIXING]``, ``[DEMANDS]``, and the inert layout sections). Those
    remain visible only through :class:`EpanetIgnoredSectionDiagnostic`,
    and ``[CONTROLS]`` / ``[RULES]`` remain visible per-row through
    :class:`EpanetControlRuleDiagnostic`.

    ``[STATUS]`` is also excluded — Sprint 22 removed it from
    :data:`IGNORED_SECTIONS` entirely, and accepted ``OPEN`` rows flow
    through the Sprint 23 ``status_rows`` channel instead.

    The helper is read-only: it never mutates the ``sections`` mapping
    and never affects parsing outcomes. Blank rows and inline ``;``
    comments are not surfaced because :func:`_split_sections` already
    strips them before any row enters the per-section bucket.
    """
    records: list[EpanetPatternEnergyDiagnostic] = []
    for name, rows in sections.items():
        if name not in _PATTERN_ENERGY_SECTIONS:
            continue
        for idx, row in enumerate(rows):
            tokens = tuple(row)
            records.append(
                EpanetPatternEnergyDiagnostic(
                    section=name,
                    row_index=idx,
                    tokens=tokens,
                    text=" ".join(tokens),
                )
            )
    return tuple(records)


# Sprint 28: the only two ignored sections that surface per-row through
# :class:`EpanetEmitterDemandDiagnostic`. All other members of
# :data:`IGNORED_SECTIONS` (``[TIMES]``, ``[REPORT]``, …) still surface
# only at the section level through
# :class:`EpanetIgnoredSectionDiagnostic`. ``[CONTROLS]`` / ``[RULES]``
# remain in their dedicated Sprint 25 channel; ``[PATTERNS]`` /
# ``[ENERGY]`` remain in their dedicated Sprint 26 channel.
_EMITTER_DEMAND_SECTIONS: tuple[str, ...] = ("EMITTERS", "DEMANDS")


def _collect_emitter_demand_row_diagnostics(
    sections: dict[str, list[list[str]]],
) -> tuple[EpanetEmitterDemandDiagnostic, ...]:
    """Surface every tokenised row inside ``[EMITTERS]`` / ``[DEMANDS]``.

    Sprint 28 — read-only visibility surface for the contents of the two
    ignored sections that most often carry per-row content alongside
    ``[CONTROLS]`` / ``[RULES]`` and ``[PATTERNS]`` / ``[ENERGY]`` in
    EPANET-exported fixtures.

    Walks the per-section tokenised rows produced by
    :func:`_split_sections` and emits one
    :class:`EpanetEmitterDemandDiagnostic` for every row inside an
    ``[EMITTERS]`` or ``[DEMANDS]`` section. Records appear in
    source-file order: section ordering follows :func:`_split_sections`'
    dict iteration order (which preserves first-appearance source
    order), and within each section ``row_index`` is the 0-based index
    into the section's accumulated row list.

    The helper deliberately excludes every other ignored section
    (``[CONTROLS]``, ``[RULES]``, ``[PATTERNS]``, ``[ENERGY]``,
    ``[TIMES]``, ``[REPORT]``, ``[QUALITY]``, ``[SOURCES]``,
    ``[REACTIONS]``, ``[MIXING]``, and the inert layout sections). Those
    remain visible only through :class:`EpanetIgnoredSectionDiagnostic`,
    ``[CONTROLS]`` / ``[RULES]`` remain visible per-row through
    :class:`EpanetControlRuleDiagnostic`, and ``[PATTERNS]`` /
    ``[ENERGY]`` remain visible per-row through
    :class:`EpanetPatternEnergyDiagnostic`.

    ``[STATUS]`` is also excluded — Sprint 22 removed it from
    :data:`IGNORED_SECTIONS` entirely, and accepted ``OPEN`` rows flow
    through the Sprint 23 ``status_rows`` channel instead.

    The helper is read-only: it never mutates the ``sections`` mapping
    and never affects parsing outcomes. Blank rows and inline ``;``
    comments are not surfaced because :func:`_split_sections` already
    strips them before any row enters the per-section bucket.
    """
    records: list[EpanetEmitterDemandDiagnostic] = []
    for name, rows in sections.items():
        if name not in _EMITTER_DEMAND_SECTIONS:
            continue
        for idx, row in enumerate(rows):
            tokens = tuple(row)
            records.append(
                EpanetEmitterDemandDiagnostic(
                    section=name,
                    row_index=idx,
                    tokens=tokens,
                    text=" ".join(tokens),
                )
            )
    return tuple(records)


# Sprint 29: the four ignored sections that surface per-row through
# :class:`EpanetWaterQualityDiagnostic`. All other members of
# :data:`IGNORED_SECTIONS` (``[TIMES]``, ``[REPORT]``, …) still surface
# only at the section level through
# :class:`EpanetIgnoredSectionDiagnostic`. ``[CONTROLS]`` / ``[RULES]``
# remain in their dedicated Sprint 25 channel; ``[PATTERNS]`` /
# ``[ENERGY]`` remain in their dedicated Sprint 26 channel;
# ``[EMITTERS]`` / ``[DEMANDS]`` remain in their dedicated Sprint 28
# channel.
_WATER_QUALITY_SECTIONS: tuple[str, ...] = (
    "QUALITY",
    "SOURCES",
    "REACTIONS",
    "MIXING",
)


def _collect_water_quality_row_diagnostics(
    sections: dict[str, list[list[str]]],
) -> tuple[EpanetWaterQualityDiagnostic, ...]:
    """Surface every tokenised row inside the water-quality-family sections.

    Sprint 29 — read-only visibility surface for the contents of the
    four water-quality-family ignored sections: ``[QUALITY]``,
    ``[SOURCES]``, ``[REACTIONS]``, and ``[MIXING]``.

    Walks the per-section tokenised rows produced by
    :func:`_split_sections` and emits one
    :class:`EpanetWaterQualityDiagnostic` for every row inside a
    ``[QUALITY]`` / ``[SOURCES]`` / ``[REACTIONS]`` / ``[MIXING]``
    section. Records appear in source-file order: section ordering
    follows :func:`_split_sections`' dict iteration order (which
    preserves first-appearance source order), and within each section
    ``row_index`` is the 0-based index into the section's accumulated
    row list.

    The helper deliberately excludes every other ignored section
    (``[CONTROLS]``, ``[RULES]``, ``[PATTERNS]``, ``[ENERGY]``,
    ``[EMITTERS]``, ``[DEMANDS]``, ``[TIMES]``, ``[REPORT]``, and the
    inert layout sections). Those remain visible only through
    :class:`EpanetIgnoredSectionDiagnostic`; ``[CONTROLS]`` / ``[RULES]``
    remain visible per-row through :class:`EpanetControlRuleDiagnostic`;
    ``[PATTERNS]`` / ``[ENERGY]`` remain visible per-row through
    :class:`EpanetPatternEnergyDiagnostic`; ``[EMITTERS]`` /
    ``[DEMANDS]`` remain visible per-row through
    :class:`EpanetEmitterDemandDiagnostic`.

    ``[STATUS]`` is also excluded — Sprint 22 removed it from
    :data:`IGNORED_SECTIONS` entirely, and accepted ``OPEN`` rows flow
    through the Sprint 23 ``status_rows`` channel instead.

    The helper is read-only: it never mutates the ``sections`` mapping
    and never affects parsing outcomes. Blank rows and inline ``;``
    comments are not surfaced because :func:`_split_sections` already
    strips them before any row enters the per-section bucket.
    """
    records: list[EpanetWaterQualityDiagnostic] = []
    for name, rows in sections.items():
        if name not in _WATER_QUALITY_SECTIONS:
            continue
        for idx, row in enumerate(rows):
            tokens = tuple(row)
            records.append(
                EpanetWaterQualityDiagnostic(
                    section=name,
                    row_index=idx,
                    tokens=tokens,
                    text=" ".join(tokens),
                )
            )
    return tuple(records)


# Sections the fallback parser tolerates as silent no-ops because they
# carry no information the steady-state Hazen-Williams core depends on.
# Promoted to a public surface in Sprint 21 so external code (and the
# test suite) can introspect the explicit no-op contract.
#
# Mechanically, this set is *documentation as code*: the parser does not
# branch on membership. ``_fallback_parse`` only ever consumes the
# hydraulically-meaningful sections (``[OPTIONS]``, ``[JUNCTIONS]``,
# ``[RESERVOIRS]``, ``[TANKS]``, ``[PIPES]``, ``[PUMPS]``, ``[VALVES]``,
# ``[CURVES]``, plus the Sprint 22 ``[STATUS]`` validator); every other
# section header is tokenised by :func:`_split_sections` and then simply
# never read. Sprint 21 ships explicit tests that this no-op behaviour
# holds — adding any section in :data:`IGNORED_SECTIONS` (or any other
# unknown section) to a fixture must leave the loaded :class:`Network`
# unchanged.
#
# ``CURVES`` is deliberately **NOT** in this set: Sprint 12 consumes
# HEAD-type curves when a ``[PUMPS]`` row references one, so the
# section is active. Unused curves are tolerated (the parser simply
# never reads them) but the section is not a global no-op.
#
# ``STATUS`` was a member through Sprint 21 but is **NOT** in this set
# from Sprint 22 onwards. Sprint 22 narrows the contract for
# ``[STATUS]``: explicit ``<link_id> OPEN`` rows are accepted as
# no-ops (and the link id is validated against the parsed
# pipes/pumps/valves), but ``CLOSED``, ``CV``, numeric pump
# speed/status, and any other token still raise :class:`ValueError`.
# See :func:`_validate_status_rows`.
#
# Sprint 21 known limitations that this set encodes:
#
# * ``[CONTROLS]`` / ``[RULES]`` rows that would close a link, change a
#   pump speed, or modify a fixed-head boundary are ignored. The dPHM
#   steady-state core does not model active controls or rule-based
#   logic; importing those rows would silently mis-represent the
#   network. They are deferred — see ``docs/epanet-inp-import.md``.
# * ``[QUALITY]``, ``[SOURCES]``, ``[REACTIONS]``, ``[MIXING]``,
#   ``[EMITTERS]`` are water-quality / pressure-driven-demand
#   extensions outside the current steady-state hydraulic scope. They
#   are ignored at parse time and will be added in dedicated future
#   sprints if and when the core grows the corresponding physics.
# * ``[TIMES]``, ``[REPORT]`` carry simulation / output settings that
#   only matter for an EPANET-runtime simulation; the dPHM importer
#   never spawns one.
IGNORED_SECTIONS: frozenset[str] = frozenset(
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
        "CONTROLS",
        "RULES",
        "EMITTERS",
        "DEMANDS",
        "QUALITY",
        "SOURCES",
        "REACTIONS",
        "MIXING",
    }
)


# Backwards-compatible private alias. The constant has always been a
# private name within this module; keeping the alias prevents any
# hypothetical downstream that imported the underscored name from
# breaking. New code should prefer :data:`IGNORED_SECTIONS`.
_IGNORED_SECTIONS = IGNORED_SECTIONS


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
    """Return a normalised ``{KEY: VALUE}`` map from [OPTIONS] rows.

    Most EPANET options are stored as single-token keys (e.g. ``Units``,
    ``Headloss``, ``Pressure``). Two shipped EPANET options have
    canonical keys spanning two whitespace-separated tokens:
    ``Demand Multiplier`` (Sprint 18) and ``Specific Gravity``
    (Sprint 19). We detect each of those specifically and store its
    value under a single canonical key (``"DEMAND MULTIPLIER"`` /
    ``"SPECIFIC GRAVITY"``), preserving the single-token storage
    convention for every other directive.
    """
    opts: dict[str, str] = {}
    for row in rows:
        if not row:
            continue
        # Multi-word ``Demand Multiplier`` key (Sprint 18). Detect the
        # two leading tokens case-insensitively and pull the third token
        # as the value. Extra whitespace between the tokens is already
        # collapsed by the line-tokeniser.
        if (
            len(row) >= 2
            and row[0].upper() == "DEMAND"
            and row[1].upper() == "MULTIPLIER"
        ):
            value = row[2] if len(row) >= 3 else ""
            opts[_DEMAND_MULTIPLIER_KEY] = value
            continue
        # Multi-word ``Specific Gravity`` key (Sprint 19). Same shape
        # as Demand Multiplier — two leading tokens then a numeric
        # value.
        if (
            len(row) >= 2
            and row[0].upper() == "SPECIFIC"
            and row[1].upper() == "GRAVITY"
        ):
            value = row[2] if len(row) >= 3 else ""
            opts[_SPECIFIC_GRAVITY_KEY] = value
            continue
        key = row[0].upper()
        val = row[1].upper() if len(row) >= 2 else ""
        opts[key] = val
    return opts


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


# --- pump-curve parsing & fitting (Sprint 12) ------------------------------


PumpCurvePoint = tuple[float, float]


def _parse_curves(
    rows: list[list[str]], *, unit_system: EpanetUnitSystem
) -> dict[str, list[PumpCurvePoint]]:
    """Group ``[CURVES]`` rows by curve id, preserving file order.

    Each accepted row has at least three tokens:
    ``curve_id``, ``X-value`` (flow, in the file's flow unit), and
    ``Y-value`` (head, in metres for SI flow units / feet for US).
    The X column is converted to m^3/s by ``unit_system.flow_to_m3s``;
    the Y column is converted to metres by ``unit_system.head_to_m``.
    The resulting (Q, H) points are in SI and directly compatible with
    :func:`aquaoptima.dphm.pump_head_gain`.

    EPANET allows curves of several types (HEAD / EFFICIENCY /
    VOLUME / HEADLOSS). The ``[CURVES]`` section itself does not
    declare the type — only the consumer (a ``[PUMPS]`` row, in
    our case) does. We therefore parse every curve uniformly here
    and let the pump-row resolver decide which curve is meaningful.
    """
    grouped: dict[str, list[PumpCurvePoint]] = {}
    for row in rows:
        if len(row) < 3:
            raise ValueError(
                f"[CURVES] row needs at least 3 tokens (id, X, Y), got {row!r}"
            )
        curve_id = row[0]
        try:
            x_val = float(row[1])
            y_val = float(row[2])
        except ValueError as exc:
            raise ValueError(
                f"[CURVES] row {row!r} has non-numeric X/Y column"
            ) from exc
        if not math.isfinite(x_val) or not math.isfinite(y_val):
            raise ValueError(f"[CURVES] row {row!r} has non-finite X/Y value")
        if x_val < 0.0:
            raise ValueError(
                f"[CURVES] curve {curve_id!r} has negative flow value {x_val}"
            )
        grouped.setdefault(curve_id, []).append(
            (x_val * unit_system.flow_to_m3s, y_val * unit_system.head_to_m)
        )
    return grouped


def fit_pump_head_curve(
    points: list[PumpCurvePoint] | tuple[PumpCurvePoint, ...],
) -> tuple[list[float], dict[str, float]]:
    """Fit ``(Q, H)`` points to the dPHM pump quadratic at ``s = 1``.

    The dPHM pump-affinity model is
    ``H(Q, s) = a0 * s^2 + a1 * s * Q + a2 * Q^2``. EPANET pump
    HEAD curves are static (no speed information), so we fit at
    ``s = 1`` against the reduced form ``H(Q) = a0 + a1*Q + a2*Q^2``.

    The fit is a 3-column ordinary least-squares solve via
    :func:`torch.linalg.lstsq` against the rows
    ``[1, Q, Q^2]``; the solver is stable for any rank-3 input.

    Parameters
    ----------
    points
        Sequence of ``(Q, H)`` pairs in **m^3/s** and **metres**.
        At least 3 points are required for a quadratic fit.

    Returns
    -------
    tuple
        ``([a0, a1, a2], diagnostics)`` where ``diagnostics`` is a
        small dict carrying ``a0``, ``a1``, ``a2``, ``rmse``,
        ``max_abs_error``, ``num_points``, ``q_min``, ``q_max``,
        and a boolean ``droop_ok`` flag (``True`` iff ``a2 <= 0``,
        i.e. head decreases with increasing flow as a physically
        sensible centrifugal-pump curve does).

    Raises
    ------
    ValueError
        If fewer than 3 points are supplied, if any Q is negative,
        if any H is non-positive or non-finite, or if the fitted
        shut-off head ``a0`` is non-positive (which would imply a
        physically nonsensical curve or pathological input data).
    """
    pts = list(points)
    if len(pts) < 3:
        raise ValueError(
            f"pump HEAD curve needs at least 3 points for a quadratic fit, "
            f"got {len(pts)}"
        )

    Q = torch.tensor([p[0] for p in pts], dtype=torch.float64)
    H = torch.tensor([p[1] for p in pts], dtype=torch.float64)

    if not torch.isfinite(Q).all() or (Q < 0).any():
        raise ValueError(
            f"pump curve flow values must be finite and non-negative, got {Q.tolist()}"
        )
    if not torch.isfinite(H).all() or (H <= 0).any():
        raise ValueError(
            f"pump curve head values must be finite and positive, got {H.tolist()}"
        )

    # Design matrix [1, Q, Q^2]; lstsq is stable for any rank-3 input.
    X = torch.stack([torch.ones_like(Q), Q, Q * Q], dim=1)  # [N, 3]
    sol = torch.linalg.lstsq(X, H.unsqueeze(1))
    coeffs = sol.solution.squeeze(1)
    a0 = float(coeffs[0].item())
    a1 = float(coeffs[1].item())
    a2 = float(coeffs[2].item())

    if not (math.isfinite(a0) and math.isfinite(a1) and math.isfinite(a2)):
        raise ValueError(
            f"pump curve fit produced non-finite coefficients: a0={a0}, a1={a1}, a2={a2}"
        )
    if a0 <= 0.0:
        raise ValueError(
            f"fitted shut-off head a0={a0} must be strictly positive; "
            "EPANET HEAD curves are expected to have positive head at Q=0"
        )

    H_pred = X @ coeffs
    residual = H_pred - H
    rmse = float(torch.sqrt((residual * residual).mean()).item())
    max_abs = float(residual.abs().max().item())

    diagnostics: dict[str, float] = {
        "a0": a0,
        "a1": a1,
        "a2": a2,
        "rmse": rmse,
        "max_abs_error": max_abs,
        "num_points": float(len(pts)),
        "q_min": float(Q.min().item()),
        "q_max": float(Q.max().item()),
        "droop_ok": 1.0 if a2 <= 0.0 else 0.0,
    }

    return [a0, a1, a2], diagnostics


# --- POWER pump surrogate (Sprint 14) --------------------------------------

# Conventional EPANET ``POWER`` value is declared in kW for SI flow
# units. Document this explicitly so downstream readers can see why
# the fallback parser multiplies by 1000 before applying
# ``P = rho * g * Q * H``.
_POWER_PUMP_KW_TO_W = 1.0e3

# EPANET ``[PUMPS] POWER`` is declared in horsepower under US-customary
# flow units; the EPANET 2.2 binary multiplies by 0.7457 to get kW. We
# mirror that constant exactly so the fallback POWER surrogate matches
# the EPANET energy calculation under either unit family.
_POWER_HP_TO_KW = 0.7457


def _convert_power_value_to_kw(
    raw_value: float, *, unit_system: EpanetUnitSystem
) -> float:
    """Convert a file-declared POWER value to kW.

    Under SI flow units the value is already in kW; under US-customary
    flow units it is in horsepower and EPANET applies a 0.7457 kW/HP
    conversion internally.
    """
    if _is_us_unit(unit_system.units):
        return raw_value * _POWER_HP_TO_KW
    return raw_value

# Water density at ~20 C and standard gravity. EPANET uses constant
# rho/g internally for its pump-energy calculations; the surrogate
# mirrors those choices so the operating point matches an EPANET run
# in the limit ``shutoff_multiplier -> 1+`` and ``Q -> Q_nom``.
_POWER_PUMP_RHO = 1000.0  # kg/m^3
_POWER_PUMP_G = 9.80665   # m/s^2

# Fallback nominal-flow anchor when the network has no positive
# downstream demand and no positive total demand (e.g. an isolated
# pump-only fixture inspected outside a real solve). 1 L/s is small
# but keeps ``a2`` finite and the surrogate Newton-stable. The
# diagnostics ``nominal_flow_source`` field flags this branch.
_POWER_PUMP_DEFAULT_NOMINAL_FLOW = 1.0e-3  # m^3/s


def fit_power_pump_surrogate(
    power_kw: float,
    nominal_flow_m3s: float,
    *,
    shutoff_multiplier: float = 1.5,
    specific_gravity: float = 1.0,
) -> tuple[list[float], dict[str, object]]:
    """Construct a conservative quadratic surrogate for a POWER pump.

    EPANET ``POWER`` pumps declare a constant shaft power
    ``P = rho_eff * g * Q * H`` (where ``rho_eff = rho_water * sg`` is
    the working fluid's density), which gives
    ``H = P / (rho_eff * g * Q)`` — hyperbolic in ``Q`` and singular
    at ``Q -> 0``. That shape is incompatible with the dPHM core's
    quadratic pump characteristic
    ``H(Q, s) = a0 * s^2 + a1 * s * Q + a2 * Q^2``.

    The Sprint 14 surrogate is therefore deliberately **conservative
    and bounded**, not a faithful constant-power conversion:

    1. Compute the operating head at the nominal flow anchor using
       the effective fluid density:
       ``H_nom = P_watts / (rho_water * sg * g * Q_nom)``.
    2. Choose a shut-off head ``a0 = shutoff_multiplier * H_nom``
       (default ``1.5 * H_nom``: shut-off head 50% above the
       operating head).
    3. Solve for ``a2`` so the surrogate passes through
       ``(Q_nom, H_nom)``:
       ``a2 = (H_nom - a0) / Q_nom**2``
       ``  = H_nom * (1 - shutoff_multiplier) / Q_nom**2``.
       With ``shutoff_multiplier > 1`` this yields ``a2 < 0`` — a
       physically sensible drooping centrifugal-pump curve.
    4. Set ``a1 = 0``. The constant-power declaration carries no
       information about a linear term.

    The result matches the EPANET POWER pump at exactly one point —
    ``(Q_nom, H_nom)`` — and is finite, bounded, and Newton-stable
    everywhere. It does **not** preserve the constant-power
    relationship away from ``Q_nom``; for credible operation far
    from the anchor flow, supply an explicit ``HEAD`` curve instead.

    Parameters
    ----------
    power_kw
        Pump shaft power in **kilowatts**, matching the EPANET
        ``[PUMPS] POWER`` convention under SI flow units. Must be
        strictly positive and finite.
    nominal_flow_m3s
        Anchor flow used to evaluate the operating head, in
        **m^3/s**. Must be strictly positive and finite. The
        fallback INP parser derives this from the network's
        downstream / total positive demand; the WNTR adapter follows
        the same rule. A trustworthy nominal flow is the single
        most important input to this surrogate.
    shutoff_multiplier
        Ratio ``a0 / H_nom``. Must be strictly greater than 1 so
        ``a2 < 0`` (the resulting curve droops). Default ``1.5``.
    specific_gravity
        Sprint 19: ratio of fluid density to water. Must be strictly
        positive and finite. Defaults to ``1.0`` (pure water), which
        preserves Sprint 14 behaviour. For a fluid twice as dense as
        water (``sg = 2.0``), ``H_nom`` halves and the surrogate's
        ``a0`` / ``a2`` magnitudes halve correspondingly; for a fluid
        half as dense (``sg = 0.5``) they double.

    Returns
    -------
    tuple
        ``([a0, a1, a2], diagnostics)`` where ``diagnostics`` is a
        dict carrying ``approximation = "constant_power_surrogate"``
        plus ``power_kw``, ``nominal_flow_m3s``,
        ``head_at_nominal_m``, ``shutoff_head_m``,
        ``shutoff_multiplier``, ``specific_gravity``, ``a0``,
        ``a1``, ``a2``. No ``rmse`` is reported because the surrogate
        is not a fit to multiple points.

    Raises
    ------
    ValueError
        If ``power_kw`` or ``nominal_flow_m3s`` is non-positive or
        non-finite, if ``shutoff_multiplier`` is not strictly greater
        than 1 (which would produce a non-drooping curve), or if
        ``specific_gravity`` is non-positive or non-finite.
    """
    if not math.isfinite(power_kw) or power_kw <= 0.0:
        raise ValueError(
            f"power_kw must be strictly positive and finite, got {power_kw}"
        )
    if not math.isfinite(nominal_flow_m3s) or nominal_flow_m3s <= 0.0:
        raise ValueError(
            "nominal_flow_m3s must be strictly positive and finite, got "
            f"{nominal_flow_m3s}"
        )
    if not math.isfinite(shutoff_multiplier) or shutoff_multiplier <= 1.0:
        raise ValueError(
            "shutoff_multiplier must be > 1 so the surrogate droops, got "
            f"{shutoff_multiplier}"
        )
    if not math.isfinite(specific_gravity) or specific_gravity <= 0.0:
        raise ValueError(
            "specific_gravity must be strictly positive and finite, got "
            f"{specific_gravity}"
        )

    power_watts = power_kw * _POWER_PUMP_KW_TO_W
    rho_eff = _POWER_PUMP_RHO * specific_gravity
    head_at_nominal = power_watts / (
        rho_eff * _POWER_PUMP_G * nominal_flow_m3s
    )
    a0 = shutoff_multiplier * head_at_nominal
    a1 = 0.0
    a2 = (head_at_nominal - a0) / (nominal_flow_m3s * nominal_flow_m3s)

    diagnostics: dict[str, object] = {
        "approximation": "constant_power_surrogate",
        "power_kw": float(power_kw),
        "nominal_flow_m3s": float(nominal_flow_m3s),
        "head_at_nominal_m": float(head_at_nominal),
        "shutoff_head_m": float(a0),
        "shutoff_multiplier": float(shutoff_multiplier),
        "specific_gravity": float(specific_gravity),
        "a0": float(a0),
        "a1": float(a1),
        "a2": float(a2),
    }
    return [a0, a1, a2], diagnostics


def _resolve_power_pump_nominal_flow(
    *,
    downstream_demand: float,
    total_positive_demand: float,
) -> tuple[float, str]:
    """Pick a nominal-flow anchor for the POWER pump surrogate.

    Preference order:

    1. The downstream node's base demand, when positive and finite.
       This is the flow the pump must supply if it is the *only*
       source for that consumer.
    2. The total positive demand across the network, when positive
       and finite. This is the flow the pump must supply if it is
       the only source for the entire network.
    3. ``_POWER_PUMP_DEFAULT_NOMINAL_FLOW`` (1 L/s). This branch is
       flagged in the returned source label so callers can detect
       it and warn.

    Returns ``(Q_nom, source_label)`` where ``source_label`` is one
    of ``"downstream_demand"``, ``"total_positive_demand"``, or
    ``"default_fallback"``.
    """
    if math.isfinite(downstream_demand) and downstream_demand > 0.0:
        return float(downstream_demand), "downstream_demand"
    if math.isfinite(total_positive_demand) and total_positive_demand > 0.0:
        return float(total_positive_demand), "total_positive_demand"
    return _POWER_PUMP_DEFAULT_NOMINAL_FLOW, "default_fallback"


# --- valve translation (Sprint 15) -----------------------------------------


# EPANET valve types the Sprint 15 translator handles conservatively.
_SUPPORTED_VALVE_TYPES = frozenset({"PRV", "TCV"})

# EPANET valve types the dPHM steady-state core *cannot* represent at
# all in Sprint 15. These raise a clear ValueError with the valve id.
# ``FCV`` (flow-control) imposes an explicit flow setpoint, ``PSV``
# (pressure-sustaining) and ``PBV`` (pressure-breaker) impose
# pressure constraints in directions that don't map cleanly onto the
# pressure-boundary surrogate, and ``GPV`` (general-purpose) requires
# a per-valve head-loss curve. Each is deferred.
_UNSUPPORTED_VALVE_TYPES = frozenset({"FCV", "PSV", "PBV", "GPV"})


# Minimum effective length floored on the TCV resistance surrogate so
# the resulting Network never violates the ``length > 0`` invariant
# enforced by :class:`Network`. 1e-6 m is well below any physically
# meaningful pipe length and corresponds to negligible head loss at
# Hazen-Williams scale.
_TCV_MIN_EFFECTIVE_LENGTH_M = 1.0e-6

# Standard gravity used by the TCV surrogate to convert ``K * V^2/(2g)``
# into a Hazen-Williams equivalent length. Mirrors the value used in
# :func:`fit_power_pump_surrogate` for consistency across surrogates.
_VALVE_G = 9.80665  # m/s^2


def fit_tcv_resistance_surrogate(
    *,
    diameter_m: float,
    setting_k: float,
    nominal_flow_m3s: float,
    minor_loss: float = 0.0,
    c_factor: float = 130.0,
) -> tuple[dict[str, float], dict[str, object]]:
    """Translate a TCV setting into an equivalent pipe-like resistance.

    A throttle-control valve (TCV) imposes a local minor-loss head
    loss ``h_K = (K_setting + K_minor) * V^2 / (2 g)``. The dPHM
    steady-state core only models distributed (Hazen-Williams) head
    loss along a pipe, so the Sprint 15 surrogate maps the minor-loss
    term onto an *equivalent* Hazen-Williams pipe edge by choosing an
    effective length ``L_eff`` that reproduces the minor-loss head
    loss at one anchor flow ``Q_nom``:

    .. math::

        h_K(Q_{nom}) = (K + K_{minor}) \\frac{Q_{nom}^2}{2 g A^2}

        h_{HW}(Q_{nom}) = \\frac{10.67\\, L_{eff}}{C^{1.852}\\,
            D^{4.87}} \\cdot Q_{nom}^{1.852}

        L_{eff} = \\frac{(K + K_{minor}) Q_{nom}^{2}\\, C^{1.852}
            D^{4.87}}{2 g A^{2}\\cdot 10.67\\, Q_{nom}^{1.852}}

    where ``A = \\pi D^{2}/4`` is the pipe cross-section. The
    resulting Hazen-Williams pipe matches the minor-loss head loss
    *exactly at* ``Q_nom`` and approximates it elsewhere; because the
    minor-loss term scales as ``Q^{2}`` and HW scales as
    ``|Q|^{1.852}``, the two diverge as ``Q`` moves away from the
    anchor. The surrogate is therefore **conservative and
    approximate**, not a faithful valve model.

    Parameters
    ----------
    diameter_m
        Valve internal diameter in **metres**. Must be strictly
        positive and finite.
    setting_k
        EPANET TCV setting — the minor-loss coefficient ``K``. Must
        be non-negative and finite. ``K = 0`` represents a fully
        open valve and produces a near-zero ``L_eff`` (floored at
        ``1e-6 m`` to satisfy the :class:`Network` ``length > 0``
        invariant).
    nominal_flow_m3s
        Anchor flow used to evaluate the head loss, in m^3/s. Must
        be strictly positive and finite. The fallback INP parser
        derives this from the network's total positive demand; if
        none is available, callers should pass an explicit anchor
        rather than letting the parser default to 1 L/s.
    minor_loss
        Additional minor-loss coefficient from the valve row's
        ``MinorLoss`` column. Must be non-negative and finite.
        Added to ``setting_k`` before computing ``L_eff``.
    c_factor
        Hazen-Williams roughness coefficient assigned to the
        surrogate pipe edge. Defaults to 130 (matches the typical
        valve-body friction class for cast iron / steel valves).

    Returns
    -------
    tuple
        ``(parameters, diagnostics)``. ``parameters`` carries the
        three keys the surrogate edge needs:

        * ``length_m`` — the effective length ``L_eff`` (or the
          floor ``1e-6 m`` if ``K + K_minor`` is zero).
        * ``diameter_m`` — the valve diameter, unchanged.
        * ``c_factor`` — the chosen roughness coefficient.

        ``diagnostics`` records the input setting, the chosen
        anchor flow, the head loss at the anchor, the resulting
        effective length, and a ``limitations`` string.

    Raises
    ------
    ValueError
        If ``diameter_m``, ``nominal_flow_m3s``, or ``c_factor`` is
        non-positive or non-finite, or if ``setting_k`` /
        ``minor_loss`` is negative or non-finite.
    """
    if not math.isfinite(diameter_m) or diameter_m <= 0.0:
        raise ValueError(
            f"diameter_m must be strictly positive and finite, got {diameter_m}"
        )
    if not math.isfinite(setting_k) or setting_k < 0.0:
        raise ValueError(
            f"setting_k must be non-negative and finite, got {setting_k}"
        )
    if not math.isfinite(minor_loss) or minor_loss < 0.0:
        raise ValueError(
            f"minor_loss must be non-negative and finite, got {minor_loss}"
        )
    if not math.isfinite(nominal_flow_m3s) or nominal_flow_m3s <= 0.0:
        raise ValueError(
            "nominal_flow_m3s must be strictly positive and finite, got "
            f"{nominal_flow_m3s}"
        )
    if not math.isfinite(c_factor) or c_factor <= 0.0:
        raise ValueError(
            f"c_factor must be strictly positive and finite, got {c_factor}"
        )

    k_total = setting_k + minor_loss
    area = math.pi * diameter_m * diameter_m / 4.0
    h_minor = k_total * (nominal_flow_m3s * nominal_flow_m3s) / (
        2.0 * _VALVE_G * area * area
    )
    hw_unit_per_metre = (
        10.67 * (nominal_flow_m3s ** 1.852)
        / ((c_factor ** 1.852) * (diameter_m ** 4.87))
    )
    if hw_unit_per_metre > 0.0:
        length_m = h_minor / hw_unit_per_metre
    else:
        length_m = 0.0
    length_m = max(length_m, _TCV_MIN_EFFECTIVE_LENGTH_M)

    parameters = {
        "length_m": float(length_m),
        "diameter_m": float(diameter_m),
        "c_factor": float(c_factor),
    }
    diagnostics: dict[str, object] = {
        "approximation": "tcv_resistance_surrogate",
        "valve_type": "TCV",
        "diameter_m": float(diameter_m),
        "setting": float(setting_k),
        "minor_loss": float(minor_loss),
        "nominal_flow_m3s": float(nominal_flow_m3s),
        "effective_length_m": float(length_m),
        "effective_c_factor": float(c_factor),
        "head_loss_at_nominal_m": float(h_minor),
        "limitations": (
            "Hazen-Williams pipe matches the minor-loss head loss only at "
            "the anchor flow; |Q|^1.852 vs K*Q^2 diverges off-design. The "
            "TCV is not modelled as an active control element."
        ),
    }
    return parameters, diagnostics


def translate_valve_to_surrogate(
    *,
    valve_id: str,
    valve_type: str,
    diameter_m: float,
    setting: float,
    minor_loss: float = 0.0,
    downstream_elev_m: float = 0.0,
    nominal_flow_m3s: float | None = None,
    c_factor: float = 130.0,
) -> dict[str, object]:
    """Translate one EPANET valve row into a dPHM-loadable description.

    Returns a dict describing the per-edge surrogate parameters plus
    optional adjustments to the downstream node (PRV pins downstream
    as a fixed-head boundary). The returned dict is consumed by the
    fallback / WNTR INP parsers, not by end users.

    Supported valve types:

    * ``PRV`` (pressure-reducing valve) — translated as a *pressure-
      boundary* surrogate. The downstream node is pinned to a
      fixed-head boundary at ``downstream_elev_m + setting``, and
      the valve edge becomes a short, permissive pipe-like
      resistance. The PRV does NOT enforce flow / pressure
      regulation as an active control element; it only pins the
      downstream boundary head.
    * ``TCV`` (throttle control valve) — translated through
      :func:`fit_tcv_resistance_surrogate` into an equivalent
      Hazen-Williams pipe edge.

    Parameters
    ----------
    valve_id
        EPANET valve identifier. Used to tag diagnostics and error
        messages.
    valve_type
        EPANET valve type token. Case-insensitive. ``PRV`` and
        ``TCV`` are supported; other recognised types
        (``FCV``, ``PSV``, ``PBV``, ``GPV``) raise
        :class:`ValueError`.
    diameter_m
        Valve internal diameter in **metres**. Must be strictly
        positive and finite.
    setting
        EPANET valve setting in the type's natural units:

        * ``PRV`` — downstream pressure head in **metres of head**.
          Must be strictly positive and finite.
        * ``TCV`` — minor-loss coefficient ``K`` (dimensionless).
          Must be non-negative and finite.
    minor_loss
        Additional minor-loss coefficient from the ``MinorLoss``
        column. Non-negative and finite.
    downstream_elev_m
        Elevation of the downstream node. Only consumed by ``PRV``
        (added to ``setting`` to compute the absolute fixed-head
        boundary value). Default 0.0 — caller must pass a real
        elevation for non-zero-datum networks.
    nominal_flow_m3s
        Anchor flow used by the ``TCV`` resistance surrogate. Must
        be positive when ``valve_type == "TCV"``; ignored for
        ``PRV``.
    c_factor
        Hazen-Williams roughness coefficient assigned to the
        surrogate pipe edge. Defaults to 130.

    Returns
    -------
    dict
        A description with keys:

        * ``valve_id`` — the EPANET id (unchanged).
        * ``valve_type`` — ``"PRV"`` or ``"TCV"``.
        * ``pipe_params`` — ``{length_m, diameter_m, c_factor}`` for
          the surrogate pipe edge.
        * ``downstream_fixed_head_m`` — ``None`` for TCV, the
          absolute head value (``elev + setting``) for PRV.
        * ``diagnostics`` — the surrogate diagnostics dict, including
          ``approximation``, ``valve_type``, ``valve_id``,
          ``diameter_m``, ``setting``, ``minor_loss``, and
          ``limitations``.

    Raises
    ------
    ValueError
        For unsupported valve types, non-positive diameter,
        non-positive PRV setting, negative TCV setting / minor
        loss, missing TCV anchor flow, or non-finite values. The
        valve id is included in every message.
    """
    vt = str(valve_type).upper()
    if not math.isfinite(diameter_m) or diameter_m <= 0.0:
        raise ValueError(
            f"valve {valve_id!r} has non-positive or non-finite diameter "
            f"{diameter_m}"
        )
    if not math.isfinite(minor_loss) or minor_loss < 0.0:
        raise ValueError(
            f"valve {valve_id!r} has negative or non-finite minor_loss {minor_loss}"
        )

    if vt == "PRV":
        if not math.isfinite(setting) or setting <= 0.0:
            raise ValueError(
                f"valve {valve_id!r} (PRV) setting must be strictly positive "
                f"and finite (downstream pressure head in metres), got {setting}"
            )
        if not math.isfinite(downstream_elev_m):
            raise ValueError(
                f"valve {valve_id!r} (PRV) downstream_elev_m must be finite, "
                f"got {downstream_elev_m}"
            )
        # Conservative pipe-like edge for the PRV body: short length
        # (2 * diameter, but at least 1 m so the HW residual is well
        # conditioned), file diameter, default C. The PRV itself
        # does not throttle here — the pressure boundary on the
        # downstream node is what enforces the regulation surrogate.
        length_m = max(2.0 * float(diameter_m), 1.0)
        params = {
            "length_m": length_m,
            "diameter_m": float(diameter_m),
            "c_factor": float(c_factor),
        }
        downstream_head = float(downstream_elev_m) + float(setting)
        diagnostics: dict[str, object] = {
            "approximation": "prv_pressure_boundary_surrogate",
            "valve_type": "PRV",
            "valve_id": valve_id,
            "diameter_m": float(diameter_m),
            "setting": float(setting),
            "minor_loss": float(minor_loss),
            "downstream_elev_m": float(downstream_elev_m),
            "downstream_fixed_head_m": downstream_head,
            "effective_length_m": float(length_m),
            "effective_c_factor": float(c_factor),
            "limitations": (
                "PRV is imported as a pressure-boundary surrogate: the "
                "downstream node is pinned to a fixed-head boundary at "
                "elev + setting, and the valve edge is a short, permissive "
                "pipe-like resistance. The PRV does NOT enforce active "
                "flow / pressure regulation; mass balance on the now-fixed "
                "downstream node is dropped from the residual."
            ),
        }
        return {
            "valve_id": valve_id,
            "valve_type": "PRV",
            "pipe_params": params,
            "downstream_fixed_head_m": downstream_head,
            "diagnostics": diagnostics,
        }

    if vt == "TCV":
        if nominal_flow_m3s is None:
            raise ValueError(
                f"valve {valve_id!r} (TCV) requires a positive nominal "
                "flow anchor (nominal_flow_m3s); none was supplied"
            )
        params, diag = fit_tcv_resistance_surrogate(
            diameter_m=float(diameter_m),
            setting_k=float(setting),
            nominal_flow_m3s=float(nominal_flow_m3s),
            minor_loss=float(minor_loss),
            c_factor=float(c_factor),
        )
        diag = dict(diag)
        diag["valve_id"] = valve_id
        return {
            "valve_id": valve_id,
            "valve_type": "TCV",
            "pipe_params": params,
            "downstream_fixed_head_m": None,
            "diagnostics": diag,
        }

    if vt in _UNSUPPORTED_VALVE_TYPES:
        raise ValueError(
            f"valve {valve_id!r} has unsupported valve type {vt!r}; the "
            f"Sprint 15 importer supports only {sorted(_SUPPORTED_VALVE_TYPES)} "
            "(active flow / pressure-sustaining / pressure-breaker / "
            "general-purpose valves are deferred)"
        )

    raise ValueError(
        f"valve {valve_id!r} has unknown valve type {vt!r}; supported "
        f"types are {sorted(_SUPPORTED_VALVE_TYPES)}"
    )


def _resolve_valve_nominal_flow(
    *, total_positive_demand: float
) -> tuple[float, str]:
    """Pick a nominal-flow anchor for the TCV surrogate.

    The TCV surrogate (unlike POWER pumps) does not have a
    downstream-demand concept — the valve is a *resistance* on a
    pipe path, not a source feeding a specific consumer. We prefer
    the network's total positive demand; failing that we fall back
    to the same 1 L/s default the POWER pump surrogate uses, with a
    diagnostic source label so callers can detect the branch.

    Returns ``(Q_nom, source_label)``.
    """
    if (
        math.isfinite(total_positive_demand)
        and total_positive_demand > 0.0
    ):
        return float(total_positive_demand), "total_positive_demand"
    return _POWER_PUMP_DEFAULT_NOMINAL_FLOW, "default_fallback"


# --- the fallback parser ----------------------------------------------------


def _fallback_parse(
    text: str,
    *,
    default_c_factor: float,
) -> tuple[Network, EpanetImportDiagnostics]:
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

    # Options
    opts = _parse_options(sections.get("OPTIONS", []))
    flow_unit = opts.get("UNITS", "LPS")
    unit_system = resolve_unit_system(flow_unit)
    demand_factor = unit_system.flow_to_m3s

    # Sprint 18: [OPTIONS] Demand Multiplier scales every junction's
    # baseline demand after the flow-unit conversion. Reservoirs, tanks,
    # pipe / pump / valve dimensions, pump HEAD curve points, TCV
    # settings, and MinorLoss columns are NOT scaled. The POWER pump
    # nominal-flow anchor sees the multiplied demand because the anchor
    # is resolved from ``demands[...]`` after junction-demand
    # normalisation.
    demand_multiplier = resolve_demand_multiplier(opts)

    # Sprint 19: [OPTIONS] Specific Gravity scales the fluid density used
    # by (1) the PRV setting conversion when an explicit pressure unit
    # is one of ``PSI``, ``KPA``, ``BAR`` — true pressure units — and
    # (2) the POWER pump surrogate's effective density. Head-length
    # pressure aliases (``METERS``, ``M``, ``FEET``, ``FT``) are length
    # units and are not scaled. Default is ``1.0`` (water).
    specific_gravity = resolve_specific_gravity(opts)

    # Sprint 20: [OPTIONS] Viscosity is parsed and validated but NOT
    # propagated to any hydraulic field. The dPHM core uses Hazen-
    # Williams head loss, which has no viscosity term, so viscosity
    # cannot scale demands, fixed heads, geometry, HEAD pump curves,
    # POWER pump surrogates, PRV/TCV settings, or solver outputs. We
    # still call the resolver so invalid directives (zero, negative,
    # NaN, Inf, non-numeric) fail fast at parse time — matching the
    # fail-fast contract EPANET-produced fixtures expect. If a future
    # sprint adds a Darcy-Weisbach branch, that branch will be the
    # first place viscosity propagates.
    resolve_viscosity(opts)

    # Sprint 17: [OPTIONS] Pressure overrides the PRV pressure-setting
    # conversion. When absent, the parser falls back to the flow-unit
    # family's pressure_setting_to_m (Sprint 16 contract). When present,
    # the explicit pressure unit converts PRV settings to metres of
    # water head regardless of the active flow-unit family.
    # Sprint 19: for true pressure units (``PSI``, ``KPA``, ``BAR``) the
    # conversion to metres of *fluid* head additionally divides by the
    # specific gravity. For head-length aliases (``METERS``, ``M``,
    # ``FEET``, ``FT``) the conversion is a pure length conversion and
    # is unaffected by specific gravity.
    pressure_directive = opts.get("PRESSURE", "")
    if pressure_directive:
        pressure_unit = resolve_pressure_unit(pressure_directive)
        prv_setting_to_m = pressure_unit.pressure_to_head_m
        if pressure_unit.name in _TRUE_PRESSURE_UNITS:
            prv_setting_to_m = prv_setting_to_m / specific_gravity
    else:
        prv_setting_to_m = unit_system.pressure_setting_to_m

    # Sprint 12: parse pump curves up-front so [PUMPS] rows can
    # resolve their curve_id against the file's declared CURVES.
    # Sprint 16: pass the full unit system so HEAD curve points are
    # converted to (m^3/s, m) for both SI and US flow-unit families.
    curves = _parse_curves(
        sections.get("CURVES", []), unit_system=unit_system
    )

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
    # Sprint 15: track per-node elevation so PRV valves can compute the
    # absolute fixed-head boundary value as ``elev + setting``. Reservoirs
    # report their elev as their declared head (their datum is implicit);
    # tanks report their elev directly. Junctions parse the elev column
    # but discard demand_pattern.
    node_elev: list[float] = []

    seen_node_ids: set[str] = set()

    def _register_node(
        node_id: str,
        demand_si: float,
        is_fixed: bool,
        head_value: float,
        elev: float,
        section: str,
    ) -> None:
        if node_id in seen_node_ids:
            raise ValueError(f"duplicate node id {node_id!r} in [{section}]")
        seen_node_ids.add(node_id)
        node_ids.append(node_id)
        demands.append(demand_si)
        fixed_mask.append(is_fixed)
        fixed_vals.append(head_value if is_fixed else 0.0)
        node_elev.append(elev)

    for row in _parse_node_rows(
        sections.get("JUNCTIONS", []), section="JUNCTIONS", expected_min_cols=1
    ):
        node_id = row[0]
        elev_raw = float(row[1]) if len(row) >= 2 else 0.0
        demand_raw = float(row[2]) if len(row) >= 3 else 0.0
        elev = elev_raw * unit_system.head_to_m
        # Sprint 18: junction demand = raw * flow_to_m3s * multiplier.
        # Multiplier defaults to 1.0 (Sprint 16/17 behaviour preserved).
        demand_si = demand_raw * demand_factor * demand_multiplier
        _register_node(
            node_id, demand_si=demand_si, is_fixed=False, head_value=0.0,
            elev=elev, section="JUNCTIONS",
        )

    for row in _parse_node_rows(
        sections.get("RESERVOIRS", []), section="RESERVOIRS", expected_min_cols=2
    ):
        node_id = row[0]
        head_value = float(row[1]) * unit_system.head_to_m
        _register_node(
            node_id, demand_si=0.0, is_fixed=True, head_value=head_value,
            elev=head_value, section="RESERVOIRS",
        )

    for row in _parse_node_rows(
        sections.get("TANKS", []), section="TANKS", expected_min_cols=3
    ):
        node_id = row[0]
        elev = float(row[1]) * unit_system.head_to_m
        init_level = float(row[2]) * unit_system.head_to_m
        # Steady-state surrogate: a tank pins its node to the current
        # water-surface elevation. Documented limitation — the dPHM core
        # does not integrate tank volumes over time in Sprint 11.
        _register_node(
            node_id,
            demand_si=0.0,
            is_fixed=True,
            head_value=elev + init_level,
            elev=elev,
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

        length_raw = float(row[3])
        # EPANET: length in metres (SI flow units) or feet (US flow units).
        length = length_raw * unit_system.length_to_m
        # EPANET: diameter in mm (SI flow units) or inches (US flow units).
        diameter_raw = float(row[4])
        diameter_m = diameter_raw * unit_system.diameter_to_m
        c_factor = float(row[5]) if len(row) >= 6 else default_c_factor

        if length <= 0.0:
            raise ValueError(
                f"pipe {edge_id!r} has non-positive length {length_raw}"
            )
        if diameter_m <= 0.0:
            raise ValueError(
                f"pipe {edge_id!r} has non-positive diameter {diameter_raw}"
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

    # Sprint 12: [PUMPS] -> dPHM pump edges via HEAD curve fitting.
    # Pump rows are appended after pipe rows so the edge ordering is
    # ``[pipes..., pumps...]`` in file order within each section.
    for row in sections.get("PUMPS", []):
        if len(row) < 5:
            raise ValueError(
                f"[PUMPS] row needs at least 5 tokens (id, node1, node2, "
                f"keyword, value), got {row!r}"
            )
        pump_id, node1, node2, keyword = row[0], row[1], row[2], row[3].upper()
        if pump_id in seen_edge_ids:
            raise ValueError(f"duplicate edge id {pump_id!r} in [PUMPS]")
        seen_edge_ids.add(pump_id)
        if node1 not in id_to_index:
            raise ValueError(
                f"pump {pump_id!r} references unknown source node {node1!r}"
            )
        if node2 not in id_to_index:
            raise ValueError(
                f"pump {pump_id!r} references unknown target node {node2!r}"
            )
        if keyword == "HEAD":
            curve_id = row[4]
            if curve_id not in curves:
                raise ValueError(
                    f"pump {pump_id!r} references undefined HEAD curve "
                    f"{curve_id!r}; available curves: {sorted(curves)}"
                )
            coeffs, _diag = fit_pump_head_curve(curves[curve_id])
        elif keyword == "POWER":
            # Sprint 14: constant-power surrogate. EPANET POWER values
            # under SI flow units are expressed in kW, and under US
            # flow units in horsepower; both are normalised to kW here
            # via :func:`_convert_power_value_to_kw` before applying
            # ``P = rho * g * Q * H``.
            try:
                power_raw = float(row[4])
            except ValueError as exc:
                raise ValueError(
                    f"pump {pump_id!r} POWER value {row[4]!r} is not numeric"
                ) from exc
            if not math.isfinite(power_raw) or power_raw <= 0.0:
                raise ValueError(
                    f"pump {pump_id!r} POWER value must be strictly positive "
                    f"and finite, got {power_raw}"
                )
            power_kw_raw = _convert_power_value_to_kw(
                power_raw, unit_system=unit_system
            )
            # Anchor nominal flow on the downstream node's demand when
            # positive (single-consumer pumps), else fall back to the
            # network's total positive demand (single-source pump for
            # the whole network), else use the documented default.
            downstream_idx = id_to_index[node2]
            downstream_demand = (
                demands[downstream_idx]
                if 0 <= downstream_idx < len(demands)
                else 0.0
            )
            total_positive_demand = sum(d for d in demands if d > 0.0)
            q_nom, _q_nom_source = _resolve_power_pump_nominal_flow(
                downstream_demand=downstream_demand,
                total_positive_demand=total_positive_demand,
            )
            # Sprint 19: scale the surrogate's effective density by
            # ``[OPTIONS] Specific Gravity``. ``H_nom = P / (rho_water
            # * sg * g * Q_nom)``; for the same P and Q, sg=2.0 halves
            # H_nom (and therefore a0, a2 magnitudes) and sg=0.5
            # doubles them.
            coeffs, _diag = fit_power_pump_surrogate(
                power_kw_raw, q_nom, specific_gravity=specific_gravity
            )
        else:
            raise ValueError(
                f"pump {pump_id!r} uses unsupported keyword {row[3]!r}; the "
                "fallback parser supports only 'HEAD curve_id' and "
                "'POWER value' pump rows"
            )

        src_idx.append(id_to_index[node1])
        dst_idx.append(id_to_index[node2])
        pipe_mask.append(False)
        pump_mask.append(True)
        # Benign positive placeholders for pipe-only fields on a pump row.
        # ``Network`` only enforces positivity on rows where ``pipe_mask``
        # is True, but using sane values keeps the dataclass inspectable
        # and matches the convention in ``make_pump_network``.
        lengths.append(1.0)
        diameters.append(0.1)
        c_factors.append(130.0)
        edge_pump_coeffs.append(coeffs)
        edge_pump_speeds.append(1.0)

    # Sprint 15: [VALVES] -> conservative valve surrogate edges.
    # Valve edges are appended after pipes and pumps so the edge ordering
    # is ``[pipes..., pumps..., valves...]`` in file order within each
    # section. PRV rows additionally pin their downstream node as a
    # fixed-head boundary, evaluated using the snapshot of total positive
    # demand BEFORE any PRV-driven fixed-head reassignment.
    valve_rows = sections.get("VALVES", [])
    if valve_rows:
        # Snapshot total positive demand BEFORE PRV-driven fixed-head
        # reassignment so the TCV nominal-flow anchor sees the network's
        # original demand distribution.
        valve_total_positive_demand = sum(d for d in demands if d > 0.0)
        for row in valve_rows:
            if len(row) < 6:
                raise ValueError(
                    f"[VALVES] row needs at least 6 tokens (id, node1, node2, "
                    f"diameter, type, setting), got {row!r}"
                )
            valve_id = row[0]
            node1, node2 = row[1], row[2]
            if valve_id in seen_edge_ids:
                raise ValueError(
                    f"duplicate edge id {valve_id!r} in [VALVES]"
                )
            seen_edge_ids.add(valve_id)
            if node1 not in id_to_index:
                raise ValueError(
                    f"valve {valve_id!r} references unknown source node "
                    f"{node1!r}"
                )
            if node2 not in id_to_index:
                raise ValueError(
                    f"valve {valve_id!r} references unknown target node "
                    f"{node2!r}"
                )

            try:
                diameter_raw = float(row[3])
            except ValueError as exc:
                raise ValueError(
                    f"valve {valve_id!r} diameter column {row[3]!r} is not "
                    "numeric"
                ) from exc
            # SI flow units: diameter in mm; US flow units: diameter in
            # inches. The unit-system diameter_to_m factor handles both.
            diameter_m = diameter_raw * unit_system.diameter_to_m

            valve_type = row[4].upper()
            try:
                setting_raw = float(row[5])
            except ValueError as exc:
                raise ValueError(
                    f"valve {valve_id!r} setting column {row[5]!r} is not "
                    "numeric"
                ) from exc
            # PRV settings carry pressure / head units; convert to
            # metres of water head. Sprint 16: in the default case
            # (no [OPTIONS] Pressure directive) the flow-unit family's
            # head_to_m factor applies — metres for SI, feet for US.
            # Sprint 17: when [OPTIONS] Pressure is present, the
            # explicit pressure unit (psi / kPa / bar / metres / feet)
            # overrides that conversion. TCV settings are the
            # dimensionless minor-loss coefficient K and are passed
            # through unchanged in either case.
            if valve_type == "PRV":
                setting_value = setting_raw * prv_setting_to_m
            else:
                setting_value = setting_raw

            if len(row) >= 7:
                try:
                    minor_loss_raw = float(row[6])
                except ValueError as exc:
                    raise ValueError(
                        f"valve {valve_id!r} minor-loss column {row[6]!r} is "
                        "not numeric"
                    ) from exc
            else:
                minor_loss_raw = 0.0

            downstream_idx = id_to_index[node2]
            downstream_elev = node_elev[downstream_idx]

            q_nom, _q_nom_source = _resolve_valve_nominal_flow(
                total_positive_demand=valve_total_positive_demand,
            )

            description = translate_valve_to_surrogate(
                valve_id=valve_id,
                valve_type=valve_type,
                diameter_m=diameter_m,
                setting=setting_value,
                minor_loss=minor_loss_raw,
                downstream_elev_m=downstream_elev,
                nominal_flow_m3s=q_nom,
                c_factor=default_c_factor,
            )

            if description["downstream_fixed_head_m"] is not None:
                # PRV: pin the downstream node as a fixed-head boundary.
                if fixed_mask[downstream_idx]:
                    raise ValueError(
                        f"valve {valve_id!r} ({description['valve_type']}): "
                        f"downstream node {node2!r} is already a fixed-head "
                        "boundary (reservoir or tank); PRV translation would "
                        "overwrite that boundary"
                    )
                fixed_mask[downstream_idx] = True
                fixed_vals[downstream_idx] = float(
                    description["downstream_fixed_head_m"]
                )

            pipe_params = description["pipe_params"]
            src_idx.append(id_to_index[node1])
            dst_idx.append(id_to_index[node2])
            pipe_mask.append(True)
            pump_mask.append(False)
            lengths.append(float(pipe_params["length_m"]))
            diameters.append(float(pipe_params["diameter_m"]))
            c_factors.append(float(pipe_params["c_factor"]))
            edge_pump_coeffs.append([0.0, 0.0, 0.0])
            edge_pump_speeds.append(0.0)

    # Sprint 22: validate any optional [STATUS] rows now that every link
    # id is known. Accept ``<link_id> OPEN`` no-ops (case-insensitive),
    # reject CLOSED / CV / numeric pump-status / unknown tokens / unknown
    # link ids with a clear ValueError. Accepted rows leave the network
    # byte-for-byte unchanged — they only buy explicit fail-fast on
    # ``CLOSED``-bearing files and on dangling link-id references.
    # Sprint 23: the validator also returns one diagnostic record per
    # accepted OPEN row so the public diagnostics surface can surface
    # the accepted rows as read-only metadata. The diagnostic records
    # are immutable and are not attached to the Network — see
    # :class:`EpanetImportDiagnostics` and
    # :func:`load_inp_diagnostics`.
    status_diagnostics = _validate_status_rows(
        sections.get("STATUS", []), seen_edge_ids
    )

    # Sprint 24: surface which ignored sections were actually present in
    # the source file. Read-only / no-op — the Sprint 21 ignored-section
    # invariance contract is preserved by construction because the
    # fallback parser never consumes any section in IGNORED_SECTIONS.
    ignored_section_diagnostics = _collect_ignored_section_diagnostics(sections)

    # Sprint 25: surface every tokenised row inside [CONTROLS] / [RULES]
    # so analysts can inspect the unsupported rows the parser dropped on
    # the floor. Read-only / no-op — the records carry the parsed tokens
    # and text only; the parser still consumes nothing from those
    # sections. Other ignored sections remain visible at the section
    # level via ``ignored_section_diagnostics``.
    # Sprint 27: classify each [CONTROLS] row by leading tokens + link
    # type using the parsed pipe / pump / valve id sets so analysts can
    # triage how many rows would target each link kind if the dPHM core
    # ever modelled them. Classification is diagnostic only; [RULES]
    # rows always classify as UNKNOWN because the importer does not
    # interpret rule structure beyond per-row visibility. The id sets
    # are sourced from the section rows themselves (token 0 is the link
    # id in each of [PIPES], [PUMPS], [VALVES]) so the classifier sees
    # every link the parser registered.
    pipe_ids_set = frozenset(row[0] for row in sections.get("PIPES", []) if row)
    pump_ids_set = frozenset(row[0] for row in sections.get("PUMPS", []) if row)
    valve_ids_set = frozenset(row[0] for row in sections.get("VALVES", []) if row)
    control_rule_row_diagnostics = _collect_control_rule_row_diagnostics(
        sections,
        pipe_ids=pipe_ids_set,
        pump_ids=pump_ids_set,
        valve_ids=valve_ids_set,
    )

    # Sprint 26: surface every tokenised row inside [PATTERNS] / [ENERGY]
    # so analysts can inspect the unsupported time-varying-demand /
    # energy-cost rows the parser dropped on the floor. Read-only /
    # no-op — the records carry the parsed tokens and text only; the
    # parser still consumes nothing from those sections. The remaining
    # ignored sections continue to surface only at the section level
    # via ``ignored_section_diagnostics``.
    pattern_energy_row_diagnostics = _collect_pattern_energy_row_diagnostics(
        sections
    )

    # Sprint 28: surface every tokenised row inside [EMITTERS] / [DEMANDS]
    # so analysts can inspect the unsupported pressure-dependent emitter /
    # demand-category rows the parser dropped on the floor. Read-only /
    # no-op — the records carry the parsed tokens and text only; the
    # parser still consumes nothing from those sections, and the loaded
    # Network's junction demand vector remains driven exclusively by the
    # [JUNCTIONS] base-demand column (with [OPTIONS] Demand Multiplier
    # applied) as in earlier sprints. The remaining ignored sections
    # continue to surface only at the section level via
    # ``ignored_section_diagnostics``.
    emitter_demand_row_diagnostics = _collect_emitter_demand_row_diagnostics(
        sections
    )

    # Sprint 29: surface every tokenised row inside the four water-quality-
    # family ignored sections [QUALITY], [SOURCES], [REACTIONS], [MIXING]
    # so analysts can inspect the unsupported initial-quality, source,
    # reaction, and tank-mixing rows the parser dropped on the floor.
    # Read-only / no-op — the records carry the parsed tokens and text
    # only; the parser still consumes nothing from those sections, and
    # the loaded Network's hydraulic fields remain unchanged. The
    # remaining ignored sections continue to surface only at the section
    # level via ``ignored_section_diagnostics``.
    water_quality_row_diagnostics = _collect_water_quality_row_diagnostics(
        sections
    )

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
    network = Network(
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
    diagnostics = EpanetImportDiagnostics(
        status_rows=status_diagnostics,
        ignored_sections=ignored_section_diagnostics,
        control_rule_rows=control_rule_row_diagnostics,
        pattern_energy_rows=pattern_energy_row_diagnostics,
        emitter_demand_rows=emitter_demand_row_diagnostics,
        water_quality_rows=water_quality_row_diagnostics,
    )
    return network, diagnostics


# --- WNTR-backed parser (optional) ------------------------------------------


def _wntr_available() -> bool:
    try:
        import wntr  # noqa: F401
    except ImportError:
        return False
    return True


def _wntr_extract_pump_curve_points(pump: object) -> list[PumpCurvePoint]:
    """Pull ``(Q, H)`` curve points from a WNTR pump-like object.

    The points returned are in SI units — m^3/s for flow, m for head —
    because WNTR normalises curve data into its internal SI
    representation regardless of the ``[OPTIONS] Units`` declared in
    the source ``.inp`` file. **No demand-factor conversion is applied
    here**; that is the fallback parser's job and would double-convert
    the WNTR-provided points.

    This helper is deliberately defensive: WNTR's public API has
    evolved across releases, and we touch only attributes that have
    been stable since WNTR 1.0 (``pump_type``, ``get_pump_curve()``,
    ``Curve.points``, ``Curve.curve_type``).

    Parameters
    ----------
    pump
        A WNTR pump-like object (real ``HeadPump`` / ``PowerPump`` or
        a duck-typed fake exposing the same surface). The helper does
        not import WNTR, so it can be unit-tested without WNTR being
        installed.

    Returns
    -------
    list of ``(Q, H)`` tuples in SI units.

    Raises
    ------
    ValueError
        If the pump does not expose a HEAD-curve form we can translate
        (e.g. POWER pumps, missing ``get_pump_curve()``, empty curve,
        or a curve declared with a non-HEAD type).
    """
    pump_type = getattr(pump, "pump_type", None)
    if pump_type is None:
        raise ValueError(
            "WNTR pump object has no 'pump_type' attribute; cannot translate"
        )
    pump_type_str = str(pump_type).upper()
    if pump_type_str != "HEAD":
        raise ValueError(
            f"WNTR pump uses unsupported pump_type {pump_type!r}; the dPHM "
            "adapter only translates HEAD-curve pumps (POWER and other forms "
            "are out of scope for Sprint 13)"
        )

    get_curve = getattr(pump, "get_pump_curve", None)
    if not callable(get_curve):
        raise ValueError(
            "WNTR pump object exposes pump_type='HEAD' but no callable "
            "get_pump_curve(); the WNTR version may be too old or the object "
            "is malformed"
        )
    try:
        curve = get_curve()
    except Exception as exc:
        raise ValueError(
            f"WNTR pump.get_pump_curve() raised {type(exc).__name__}: {exc}"
        ) from exc

    curve_type = getattr(curve, "curve_type", None)
    if curve_type is not None and str(curve_type).upper() != "HEAD":
        raise ValueError(
            f"WNTR pump curve has curve_type={curve_type!r}; expected 'HEAD'"
        )

    raw_points = getattr(curve, "points", None)
    if not raw_points:
        raise ValueError("WNTR pump curve has no points; cannot fit")

    out: list[PumpCurvePoint] = []
    for pt in raw_points:
        try:
            q_val, h_val = float(pt[0]), float(pt[1])
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError(
                f"WNTR pump curve has malformed point {pt!r}: {exc}"
            ) from exc
        out.append((q_val, h_val))
    return out


def _wntr_extract_power_pump_kw(pump: object) -> float:
    """Pull the constant-power value (in kW) from a WNTR POWER pump.

    WNTR stores ``Pump.power`` in SI **watts** after loading the
    ``.inp`` file (regardless of the file's ``[OPTIONS] Units``
    directive), so we convert to kW here so the same surrogate
    helper handles both fallback (kW already from the file column)
    and WNTR paths through a single kW-typed interface.

    The helper is deliberately defensive: WNTR's ``Pump.power``
    attribute has been stable across recent releases, but its dtype
    can be a NumPy scalar, a Python float, or (rarely) ``None`` when
    the underlying ``PowerPump`` is mid-construction. We tolerate
    each.

    Raises
    ------
    ValueError
        If the pump exposes no ``power`` attribute, the value is
        non-numeric, non-finite, or non-positive.
    """
    power_raw = getattr(pump, "power", None)
    if power_raw is None:
        raise ValueError(
            "WNTR POWER pump has no 'power' attribute; the WNTR version may "
            "be too old or the pump object is malformed"
        )
    try:
        power_w = float(power_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"WNTR POWER pump exposes non-numeric power={power_raw!r}: {exc}"
        ) from exc
    if not math.isfinite(power_w) or power_w <= 0.0:
        raise ValueError(
            f"WNTR POWER pump has non-positive or non-finite power={power_w} W"
        )
    return power_w / _POWER_PUMP_KW_TO_W


def _wntr_translate_pump(
    pump: object,
    *,
    downstream_demand: float = 0.0,
    total_positive_demand: float = 0.0,
) -> tuple[list[float], float, dict[str, object]]:
    """Translate a WNTR pump-like object into dPHM pump parameters.

    Returns ``(coeffs, base_speed, diagnostics)`` where ``coeffs`` is
    the 3-vector ``[a0, a1, a2]`` consumed by
    :func:`aquaoptima.dphm.pump_head_gain`, ``base_speed`` is the
    pump's static nominal speed (defaults to ``1.0`` if WNTR does not
    expose one), and ``diagnostics`` is the dict the underlying fit
    helper produces.

    Routing by ``pump.pump_type``:

    * ``"HEAD"`` (Sprint 13) — extract the WNTR pump curve and reuse
      :func:`fit_pump_head_curve`. WNTR and fallback paths produce
      numerically identical coefficients on the same curve points.
    * ``"POWER"`` (Sprint 14) — extract the WNTR pump power and reuse
      :func:`fit_power_pump_surrogate` with the same downstream- /
      total-positive-demand anchor rule the fallback parser uses.

    Any other ``pump_type`` raises :class:`ValueError`. POWER-pump
    callers should pass ``downstream_demand`` and
    ``total_positive_demand`` from the surrounding WNTR network so
    the surrogate is anchored on real data; HEAD-pump callers can
    leave these defaulted (HEAD translation does not consult them).
    """
    pump_type = getattr(pump, "pump_type", None)
    pump_type_str = str(pump_type).upper() if pump_type is not None else ""

    if pump_type_str == "POWER":
        power_kw = _wntr_extract_power_pump_kw(pump)
        q_nom, _q_nom_source = _resolve_power_pump_nominal_flow(
            downstream_demand=downstream_demand,
            total_positive_demand=total_positive_demand,
        )
        coeffs, diagnostics = fit_power_pump_surrogate(power_kw, q_nom)
    else:
        # HEAD path (and rejection for unknown pump_type) is handled
        # by the extract helper, which raises a clear ValueError for
        # anything other than HEAD-curve forms.
        points = _wntr_extract_pump_curve_points(pump)
        coeffs, head_diag = fit_pump_head_curve(points)
        diagnostics = dict(head_diag)

    base_speed = getattr(pump, "base_speed", None)
    try:
        base_speed_f = float(base_speed) if base_speed is not None else 1.0
    except (TypeError, ValueError):
        base_speed_f = 1.0
    if not math.isfinite(base_speed_f) or base_speed_f <= 0.0:
        base_speed_f = 1.0
    return coeffs, base_speed_f, diagnostics


# --- WNTR valve helpers (Sprint 15) ----------------------------------------


def _wntr_extract_valve_fields(valve: object) -> dict[str, object]:
    """Pull defensive valve fields from a WNTR valve-like object.

    Returns a dict with keys ``valve_type``, ``diameter_m``,
    ``setting``, ``minor_loss``, ``start_node_name``,
    ``end_node_name``. Each is extracted via ``getattr`` against the
    stable WNTR public surface (``valve_type``, ``diameter``,
    ``initial_setting`` / ``setting``, ``minor_loss``,
    ``start_node_name`` / ``end_node_name``). The helper is
    deliberately tolerant of attribute aliases so multiple WNTR
    versions work.

    Raises
    ------
    ValueError
        If the valve has no ``valve_type``, a non-finite or
        non-positive diameter, a non-numeric setting / minor_loss,
        or a missing endpoint reference.
    """
    valve_type_raw = getattr(valve, "valve_type", None)
    if valve_type_raw is None:
        raise ValueError(
            "WNTR valve object has no 'valve_type' attribute; cannot translate"
        )
    valve_type = str(valve_type_raw).upper()

    # WNTR ``Valve.diameter`` is in SI metres (engine internal).
    diameter_raw = getattr(valve, "diameter", None)
    if diameter_raw is None:
        raise ValueError(
            "WNTR valve has no 'diameter' attribute; cannot translate"
        )
    try:
        diameter_m = float(diameter_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"WNTR valve exposes non-numeric diameter={diameter_raw!r}: {exc}"
        ) from exc
    if not math.isfinite(diameter_m) or diameter_m <= 0.0:
        raise ValueError(
            f"WNTR valve has non-positive or non-finite diameter "
            f"{diameter_m} m"
        )

    # ``initial_setting`` is the EPANET-loaded numeric setting; some
    # older WNTR releases expose only ``setting`` (which can also be
    # a callable/property). Try ``initial_setting`` first.
    setting_raw = getattr(valve, "initial_setting", None)
    if setting_raw is None:
        setting_raw = getattr(valve, "setting", None)
    if setting_raw is None:
        raise ValueError(
            "WNTR valve has no 'initial_setting' / 'setting' attribute; "
            "cannot translate"
        )
    try:
        setting = float(setting_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"WNTR valve exposes non-numeric setting={setting_raw!r}: {exc}"
        ) from exc

    minor_loss_raw = getattr(valve, "minor_loss", 0.0)
    if minor_loss_raw is None:
        minor_loss_raw = 0.0
    try:
        minor_loss = float(minor_loss_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"WNTR valve exposes non-numeric minor_loss={minor_loss_raw!r}: "
            f"{exc}"
        ) from exc

    start_node_name = getattr(valve, "start_node_name", None)
    end_node_name = getattr(valve, "end_node_name", None)
    if start_node_name is None or end_node_name is None:
        raise ValueError(
            "WNTR valve missing start/end node names; cannot translate"
        )

    return {
        "valve_type": valve_type,
        "diameter_m": diameter_m,
        "setting": setting,
        "minor_loss": minor_loss,
        "start_node_name": str(start_node_name),
        "end_node_name": str(end_node_name),
    }


def _wntr_translate_valve(
    valve: object,
    *,
    valve_id: str | None = None,
    downstream_elev_m: float = 0.0,
    total_positive_demand: float = 0.0,
) -> dict[str, object]:
    """Translate a WNTR valve-like object via the dPHM surrogate.

    Returns the same dict shape :func:`translate_valve_to_surrogate`
    returns, with an additional ``start_node_name`` /
    ``end_node_name`` echo so the WNTR parser can resolve endpoint
    indices. The helper does not import WNTR — it operates on
    duck-typed objects exposing ``valve_type``, ``diameter``,
    ``initial_setting`` (or ``setting``), ``minor_loss``,
    ``start_node_name``, and ``end_node_name``.

    Parameters
    ----------
    valve
        WNTR valve-like object (real or duck-typed).
    valve_id
        Optional explicit id. If omitted the helper falls back to
        ``getattr(valve, "name", "")``, matching WNTR's link-naming
        convention.
    downstream_elev_m
        Elevation of the downstream node — needed by PRV to compute
        the absolute fixed-head boundary.
    total_positive_demand
        Total positive demand snapshot from the surrounding network,
        used as the TCV nominal-flow anchor.
    """
    fields = _wntr_extract_valve_fields(valve)
    q_nom, _q_nom_source = _resolve_valve_nominal_flow(
        total_positive_demand=total_positive_demand,
    )
    resolved_valve_id = (
        valve_id if valve_id is not None else str(getattr(valve, "name", ""))
    )
    description = translate_valve_to_surrogate(
        valve_id=resolved_valve_id,
        valve_type=str(fields["valve_type"]),
        diameter_m=float(fields["diameter_m"]),  # type: ignore[arg-type]
        setting=float(fields["setting"]),  # type: ignore[arg-type]
        minor_loss=float(fields["minor_loss"]),  # type: ignore[arg-type]
        downstream_elev_m=downstream_elev_m,
        nominal_flow_m3s=q_nom,
    )
    description = dict(description)
    description["start_node_name"] = fields["start_node_name"]
    description["end_node_name"] = fields["end_node_name"]
    return description


def _wntr_extract_demand_multiplier(wn: object) -> float:
    """Pull ``[OPTIONS] Demand Multiplier`` from a WNTR network model.

    WNTR exposes the directive at
    ``wn.options.hydraulic.demand_multiplier`` and does not pre-scale
    ``Junction.base_demand`` with it. Defaults to ``1.0`` whenever the
    attribute chain is missing or non-numeric. Validation mirrors
    :func:`resolve_demand_multiplier`.
    """
    options = getattr(wn, "options", None)
    hydraulic = getattr(options, "hydraulic", None) if options is not None else None
    raw = getattr(hydraulic, "demand_multiplier", None) if hydraulic is not None else None
    if raw is None:
        return _DEFAULT_DEMAND_MULTIPLIER
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"WNTR options.hydraulic.demand_multiplier {raw!r} is not numeric"
        ) from exc
    if not math.isfinite(value):
        raise ValueError(
            f"WNTR options.hydraulic.demand_multiplier must be finite, got {value}"
        )
    if value < 0.0:
        raise ValueError(
            f"WNTR options.hydraulic.demand_multiplier must be non-negative, "
            f"got {value}"
        )
    return value


def _wntr_parse(
    source: PathLike, *, default_c_factor: float
) -> tuple[Network, EpanetImportDiagnostics]:
    try:
        import wntr  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "parser='wntr' requires the 'wntr' package. Install with: "
            "pip install 'aquaoptima-dphm-pinn[epanet]' or pip install wntr"
        ) from exc

    wn = wntr.network.WaterNetworkModel(str(source))

    # Sprint 18: WNTR exposes ``[OPTIONS] Demand Multiplier`` as a
    # separate option (``wn.options.hydraulic.demand_multiplier``) and
    # does NOT pre-scale ``Junction.base_demand`` with it — the
    # multiplier is applied at simulation time by WNTR's internal
    # engine. Since the dPHM core never invokes that engine, we apply
    # the multiplier explicitly here so the WNTR back-end and the
    # fallback parser produce identical demand sums.
    demand_multiplier = _wntr_extract_demand_multiplier(wn)

    # Pull the same minimum subset the fallback parser supports, in a
    # WNTR-version-tolerant way. We never rely on attributes that have
    # changed across WNTR releases — only the public lookup APIs.
    node_ids: list[str] = []
    demands: list[float] = []
    fixed_mask: list[bool] = []
    fixed_vals: list[float] = []
    # Sprint 15: per-node elevation for PRV downstream-fixed-head
    # translation. Junctions expose ``elevation``; reservoirs expose
    # ``base_head`` (their datum is implicit); tanks expose
    # ``elevation``.
    node_elev: list[float] = []

    # Junctions first
    for jid in wn.junction_name_list:
        j = wn.get_node(jid)
        # WNTR stores baseline demand in m^3/s already (the engine's
        # internal SI unit), regardless of the file's [OPTIONS] Units.
        # Sprint 18: apply the [OPTIONS] Demand Multiplier here so the
        # WNTR back-end matches the fallback parser's scaled demand.
        base_demand = float(getattr(j, "base_demand", 0.0) or 0.0)
        base_demand *= demand_multiplier
        elev = float(getattr(j, "elevation", 0.0) or 0.0)
        node_ids.append(jid)
        demands.append(base_demand)
        fixed_mask.append(False)
        fixed_vals.append(0.0)
        node_elev.append(elev)

    for rid in wn.reservoir_name_list:
        r = wn.get_node(rid)
        head_value = float(getattr(r, "base_head", 0.0) or 0.0)
        node_ids.append(rid)
        demands.append(0.0)
        fixed_mask.append(True)
        fixed_vals.append(head_value)
        node_elev.append(head_value)

    for tid in wn.tank_name_list:
        t = wn.get_node(tid)
        elev = float(getattr(t, "elevation", 0.0) or 0.0)
        init_level = float(getattr(t, "init_level", 0.0) or 0.0)
        node_ids.append(tid)
        demands.append(0.0)
        fixed_mask.append(True)
        fixed_vals.append(elev + init_level)
        node_elev.append(elev)

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

    # Sprint 13/14: WNTR-side pump translation. Pumps are appended
    # after pipes so the edge ordering matches the fallback parser's
    # ``[pipes..., pumps...]`` convention. HEAD-curve pumps reuse
    # :func:`fit_pump_head_curve` against WNTR's SI curve points;
    # POWER pumps reuse :func:`fit_power_pump_surrogate` anchored on
    # the same downstream / total-positive-demand rule the fallback
    # parser uses.
    pump_names = getattr(wn, "pump_name_list", []) or []
    # Snapshot the demand list before pumps are appended so the
    # POWER surrogate sees the network's original positive demand
    # distribution (not yet rebalanced onto fixed-head nodes).
    total_positive_demand = sum(d for d in demands if d > 0.0)
    for pid in pump_names:
        p = wn.get_link(pid)
        n1 = p.start_node_name
        n2 = p.end_node_name
        if n1 not in id_to_index or n2 not in id_to_index:
            raise ValueError(
                f"WNTR pump {pid!r} references nodes outside the supported set"
            )
        downstream_idx = id_to_index[n2]
        downstream_demand = (
            demands[downstream_idx]
            if 0 <= downstream_idx < len(demands)
            else 0.0
        )
        try:
            coeffs, base_speed, _diag = _wntr_translate_pump(
                p,
                downstream_demand=downstream_demand,
                total_positive_demand=total_positive_demand,
            )
        except ValueError as exc:
            raise ValueError(
                f"WNTR pump {pid!r}: {exc}"
            ) from exc
        src_idx.append(id_to_index[n1])
        dst_idx.append(id_to_index[n2])
        pipe_mask.append(False)
        pump_mask.append(True)
        # Benign positive placeholders for pipe-only fields; the
        # solver only consumes these on rows where pipe_mask=True.
        lengths.append(1.0)
        diameters.append(0.1)
        c_factors.append(130.0)
        edge_pump_coeffs.append(coeffs)
        edge_pump_speeds.append(base_speed)

    # Sprint 15: WNTR-side valve translation. Valve edges are appended
    # after pumps so the edge ordering matches the fallback parser's
    # ``[pipes..., pumps..., valves...]`` convention. PRV valves
    # additionally pin their downstream node as a fixed-head boundary,
    # evaluated using the snapshot of total positive demand BEFORE any
    # PRV-driven fixed-head reassignment.
    valve_names = getattr(wn, "valve_name_list", []) or []
    if valve_names:
        valve_total_positive_demand = sum(d for d in demands if d > 0.0)
        seen_edge_ids = set(wn.pipe_name_list) | set(
            getattr(wn, "pump_name_list", []) or []
        )
        for vid in valve_names:
            v = wn.get_link(vid)
            if vid in seen_edge_ids - {vid}:
                # WNTR enforces uniqueness across link types, but be
                # defensive in case future versions relax that.
                raise ValueError(
                    f"WNTR valve {vid!r} duplicates a pipe/pump edge id"
                )
            n1 = getattr(v, "start_node_name", None)
            n2 = getattr(v, "end_node_name", None)
            if n1 not in id_to_index or n2 not in id_to_index:
                raise ValueError(
                    f"WNTR valve {vid!r} references nodes outside the "
                    "supported set"
                )
            downstream_idx = id_to_index[n2]
            downstream_elev = node_elev[downstream_idx]
            try:
                description = _wntr_translate_valve(
                    v,
                    valve_id=vid,
                    downstream_elev_m=downstream_elev,
                    total_positive_demand=valve_total_positive_demand,
                )
            except ValueError as exc:
                raise ValueError(
                    f"WNTR valve {vid!r}: {exc}"
                ) from exc

            if description["downstream_fixed_head_m"] is not None:
                if fixed_mask[downstream_idx]:
                    raise ValueError(
                        f"WNTR valve {vid!r} ({description['valve_type']}): "
                        f"downstream node {n2!r} is already a fixed-head "
                        "boundary (reservoir or tank); PRV translation would "
                        "overwrite that boundary"
                    )
                fixed_mask[downstream_idx] = True
                fixed_vals[downstream_idx] = float(
                    description["downstream_fixed_head_m"]
                )

            pipe_params = description["pipe_params"]
            src_idx.append(id_to_index[n1])
            dst_idx.append(id_to_index[n2])
            pipe_mask.append(True)
            pump_mask.append(False)
            lengths.append(float(pipe_params["length_m"]))
            diameters.append(float(pipe_params["diameter_m"]))
            c_factors.append(float(pipe_params["c_factor"]))
            edge_pump_coeffs.append([0.0, 0.0, 0.0])
            edge_pump_speeds.append(0.0)

    # Mirror the fallback parser's demand rebalancing so WNTR and
    # fallback networks have the same demand sum on the shipped
    # fixtures. Mass on fixed-head nodes drops out of the residual
    # anyway — this is purely cosmetic but keeps the two back-ends
    # numerically comparable.
    total_demand = sum(demands)
    fixed_idx = [i for i, f in enumerate(fixed_mask) if f]
    if fixed_idx and not math.isclose(total_demand, 0.0, abs_tol=1e-12):
        share = total_demand / len(fixed_idx)
        for i in fixed_idx:
            demands[i] -= share

    edge_index = torch.tensor([src_idx, dst_idx], dtype=torch.long)
    network = Network(
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
    # Sprint 23/24/25/26/28/29: the WNTR back-end is documented as
    # fallback-authoritative for every diagnostics channel. WNTR has its
    # own ``[STATUS]`` parser, its own per-section handling, its own
    # ``[CONTROLS]`` / ``[RULES]`` interpretation, its own
    # ``[PATTERNS]`` / ``[ENERGY]`` handling, its own
    # ``[EMITTERS]`` / ``[DEMANDS]`` handling, and its own water-quality
    # ``[QUALITY]`` / ``[SOURCES]`` / ``[REACTIONS]`` / ``[MIXING]``
    # handling; the dPHM WNTR adapter does not re-emit any of those as
    # diagnostics. The container is returned empty so the public API
    # surface is uniform across back-ends and so callers can branch on
    # parser explicitly if they need WNTR-side records (none are
    # surfaced today).
    diagnostics = EpanetImportDiagnostics()
    return network, diagnostics


# --- public entry point -----------------------------------------------------


_VALID_PARSERS = ("auto", "fallback", "wntr")


def _dispatch_inp_parse(
    source: PathLike,
    *,
    parser: str,
    units: str,
    default_c_factor: float,
) -> tuple[Network, EpanetImportDiagnostics]:
    """Validate kwargs and run the appropriate parser back-end.

    Sprint 23 internal helper. Returns the ``(Network, diagnostics)``
    pair both public entry points (:func:`load_network_from_inp` and
    :func:`load_inp_diagnostics`) need, with one single point of
    keyword validation so the two functions cannot drift.
    """
    if parser not in _VALID_PARSERS:
        raise ValueError(
            f"parser must be one of {_VALID_PARSERS}, got {parser!r}"
        )
    if units.lower() != "si":
        raise ValueError(
            f"units={units!r} is not supported; load_network_from_inp always "
            "returns an SI Network. The input fixture's flow-unit family is "
            "read from [OPTIONS] Units and may be either SI or US-customary."
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


def load_network_from_inp(
    source: PathLike,
    *,
    parser: str = "auto",
    units: str = "si",
    default_c_factor: float = 130.0,
    return_diagnostics: bool = False,
) -> Network | tuple[Network, EpanetImportDiagnostics]:
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
        Output unit family for the returned :class:`Network`.
        Currently only ``"si"`` is supported — every
        :class:`Network` produced by this loader carries SI tensors
        (m, m^3/s) regardless of the input fixture's flow-unit
        family. The actual *input* flow unit (``LPS``, ``GPM``, …)
        is read from the INP file's ``[OPTIONS] Units`` directive
        and converted to SI through
        :func:`resolve_unit_system`. The parameter exists for
        future expansion; passing anything other than ``"si"``
        raises :class:`ValueError`.
    default_c_factor
        Hazen-Williams roughness coefficient used when a pipe row
        omits its roughness column. Default ``130.0`` matches the
        Sprint 1-10 reference networks.
    return_diagnostics
        Sprint 23 read-only side channel. When ``False`` (default) the
        function returns the bare :class:`Network` — the same shape
        every Sprint 11-22 caller expects, so existing code keeps
        working without changes. When ``True`` the function returns a
        ``(Network, EpanetImportDiagnostics)`` tuple; the
        :class:`EpanetImportDiagnostics` carries one record per
        accepted ``[STATUS] OPEN`` row. The returned :class:`Network`
        is identical in either case; ``return_diagnostics=True``
        never alters hydraulic fields.

    Returns
    -------
    Network or tuple
        Default: the validated dPHM network with node ordering
        preserved as ``[junctions..., reservoirs..., tanks...]`` from
        the file's own ordering inside each section. With
        ``return_diagnostics=True``: ``(Network, EpanetImportDiagnostics)``.

    Raises
    ------
    ValueError
        For malformed input, missing fixed-head boundaries,
        non-positive pipe parameters, unsupported pump/valve forms,
        or unsupported flow-unit tokens. From Sprint 16 onwards
        the ten EPANET-recognised flow units
        ``{LPS, LPM, MLD, CMH, CMD, GPM, CFS, MGD, IMGD, AFD}`` are
        all parsed cleanly.
    ImportError
        Only when ``parser="wntr"`` and WNTR is not installed.
    """
    network, diagnostics = _dispatch_inp_parse(
        source,
        parser=parser,
        units=units,
        default_c_factor=default_c_factor,
    )
    if return_diagnostics:
        return network, diagnostics
    return network


def load_inp_diagnostics(
    source: PathLike,
    *,
    parser: str = "auto",
    units: str = "si",
    default_c_factor: float = 130.0,
) -> EpanetImportDiagnostics:
    """Return read-only diagnostics for an EPANET ``.inp`` import.

    Sprint 23 surfaces accepted ``[STATUS] OPEN`` rows as a read-only
    diagnostics container so analysts can see what status declarations
    were present in an imported file without changing any hydraulic
    field on the loaded :class:`Network`. Sprint 24 extended the same
    container with an ``ignored_sections`` field carrying one record
    per :data:`IGNORED_SECTIONS` member that was actually declared in
    the file. Sprint 25 added a ``control_rule_rows`` channel for
    per-row ``[CONTROLS]`` / ``[RULES]`` visibility; Sprint 26 added a
    ``pattern_energy_rows`` channel for per-row ``[PATTERNS]`` /
    ``[ENERGY]`` visibility; Sprint 28 added an
    ``emitter_demand_rows`` channel for per-row ``[EMITTERS]`` /
    ``[DEMANDS]`` visibility; Sprint 29 adds a ``water_quality_rows``
    channel for per-row ``[QUALITY]`` / ``[SOURCES]`` /
    ``[REACTIONS]`` / ``[MIXING]`` visibility.

    The returned :class:`EpanetImportDiagnostics` is structurally
    immutable: the container is a frozen :class:`dataclasses.dataclass`,
    and each row-list field is a :class:`tuple` of frozen record
    dataclasses.

    The fallback parser is authoritative for every diagnostic
    channel — the optional WNTR back-end has its own ``[STATUS]``
    parser and its own per-section handling, and the dPHM WNTR adapter
    does not re-emit any of those diagnostic channels. Calling this
    function with ``parser="wntr"`` returns an empty
    :class:`EpanetImportDiagnostics` even on files that declare
    ``[STATUS] OPEN`` rows, ignored sections, ``[CONTROLS]`` /
    ``[RULES]`` rows, ``[PATTERNS]`` / ``[ENERGY]`` rows,
    ``[EMITTERS]`` / ``[DEMANDS]`` rows, or ``[QUALITY]`` /
    ``[SOURCES]`` / ``[REACTIONS]`` / ``[MIXING]`` rows. See
    ``docs/epanet-inp-import.md``.

    Parameters mirror :func:`load_network_from_inp`. The same
    :class:`ValueError` / :class:`ImportError` failure surface
    applies: rejected ``[STATUS]`` rows (CLOSED / CV / numeric /
    unknown link id / short row / arbitrary token) still raise, and
    no partial diagnostics leak out of an error.
    """
    _network, diagnostics = _dispatch_inp_parse(
        source,
        parser=parser,
        units=units,
        default_c_factor=default_c_factor,
    )
    return diagnostics


__all__ = [
    "EpanetControlKind",
    "EpanetControlRuleDiagnostic",
    "EpanetEmitterDemandDiagnostic",
    "EpanetIgnoredSectionDiagnostic",
    "EpanetImportDiagnostics",
    "EpanetPatternEnergyDiagnostic",
    "EpanetPressureUnit",
    "EpanetStatusDiagnostic",
    "EpanetUnitSystem",
    "EpanetWaterQualityDiagnostic",
    "IGNORED_SECTIONS",
    "SUPPORTED_FLOW_UNITS",
    "SUPPORTED_PRESSURE_UNITS",
    "fit_power_pump_surrogate",
    "fit_pump_head_curve",
    "fit_tcv_resistance_surrogate",
    "load_inp_diagnostics",
    "load_network_from_inp",
    "resolve_demand_multiplier",
    "resolve_pressure_unit",
    "resolve_specific_gravity",
    "resolve_unit_system",
    "resolve_viscosity",
    "translate_valve_to_surrogate",
]
