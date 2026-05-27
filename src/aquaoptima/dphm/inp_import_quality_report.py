"""EPANET ``.inp`` import-quality report (Sprint 33).

Sprint 33 composes the Sprint 23–32 read-only EPANET import diagnostics
surfaces (``status_rows``, ``ignored_sections``, ``control_rule_rows``,
``pattern_energy_rows``, ``emitter_demand_rows``, ``water_quality_rows``,
``edge_surrogates``, plus the Sprint 30/31/32 helpers) into a single
typed, immutable, machine-friendly import-quality report a UI / API /
shadow-mode caller can render verbatim.

The module is **composition / reporting only**. It does not activate any
deferred EPANET semantics (``[CONTROLS]`` / ``[RULES]`` / ``[PATTERNS]``
/ ``[ENERGY]`` / ``[EMITTERS]`` / ``[DEMANDS]`` / water-quality), does
not mutate the loaded :class:`Network`, and does not introduce new
EPANET parser behaviour. Every field on every returned report is a
frozen dataclass or an immutable tuple / mapping. Calling the builder
twice on the same diagnostics returns equal reports.

Two public entry points are exposed:

* :func:`build_import_quality_report` — pure composition from an
  existing :class:`EpanetImportDiagnostics` (and an optional
  :class:`Network` for surrogate edge-index range validation).
* :func:`load_inp_import_quality_report` — convenience loader that
  parses an INP path through :func:`load_network_from_inp` with
  ``return_diagnostics=True`` and runs the builder on the result.

The report is intentionally narrow:

* ``parser`` — which parser produced the diagnostics (the builder
  trusts the caller; it does not re-derive this).
* ``total_diagnostic_rows`` / ``ignored_section_count`` — top-line
  counts mirroring the Sprint 30 summary.
* ``row_count_by_section`` — fresh mapping mirroring the Sprint 30
  helper.
* ``ignored_sections`` — names tuple mirroring the Sprint 30 helper.
* ``sections`` — one :class:`EpanetImportQualitySectionReport` per
  section that has either row diagnostics or ignored-section
  presence (never double-counted).
* ``surrogates`` — one :class:`EpanetImportQualitySurrogateReport`
  per Sprint 32 edge surrogate.
* ``surrogate_count_by_kind`` — fresh mapping mirroring the Sprint
  32 helper.
* ``warnings`` — deterministic tuple of warnings the report
  detected (empty WNTR diagnostics, surrogate edge index out of
  range when a :class:`Network` is supplied, …).
* ``limitations`` — deterministic tuple of human-readable
  limitations to surface verbatim. Includes one entry per
  surrogate kind present (de-duplicated, first-occurrence
  preserved) plus the parser-asymmetry note for ``parser="wntr"``.

WNTR asymmetry: the Sprint 23–32 contract leaves
:class:`EpanetImportDiagnostics` empty for ``parser="wntr"``. The
Sprint 33 builder treats that as a documented asymmetry and surfaces
it through the ``limitations`` tuple rather than guessing what the
WNTR back-end would have emitted.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Union

from .inp_io import (
    EpanetImportDiagnostics,
    IGNORED_SECTIONS,
    load_network_from_inp,
)
from .network import Network


PathLike = Union[str, Path]


# Sprint 33: parser tokens the builder accepts via the ``parser`` keyword.
# The builder trusts the caller — it does not re-derive the parser from
# the diagnostics container — but the input is still validated against
# the same small set of canonical tokens the loader uses, so a typo
# fails fast instead of silently producing an asymmetry-tagged report.
_VALID_REPORT_PARSERS: tuple[str, ...] = ("fallback", "wntr")


# Sprint 33: canonical section ordering for the per-section report. We
# combine the Sprint 30 row-count canonical order (which leads with
# ``STATUS`` because the Sprint 23 channel is the only one that does not
# correspond to a member of :data:`IGNORED_SECTIONS`) with the remaining
# layout / time-control sections in :data:`IGNORED_SECTIONS` that the
# row-count helper does not enumerate. The final tail picks up any
# unknown / future section name in alphabetical order so the report
# stays deterministic across Python versions and dict insertion orders.
_REPORT_SECTION_CANONICAL_ORDER: tuple[str, ...] = (
    "STATUS",
    "CONTROLS",
    "RULES",
    "PATTERNS",
    "ENERGY",
    "EMITTERS",
    "DEMANDS",
    "QUALITY",
    "SOURCES",
    "REACTIONS",
    "MIXING",
    # Layout / time-control sections present in IGNORED_SECTIONS but
    # not enumerated by row_count_by_section. They only contribute to
    # the report through ignored-section presence.
    "TITLE",
    "END",
    "TIMES",
    "REPORT",
    "COORDINATES",
    "VERTICES",
    "LABELS",
    "BACKDROP",
    "TAGS",
)


# Sprint 33: pinned, module-level messages so two section reports for
# the same section state always carry identical text. Diffing two
# reports therefore never surfaces spurious string variation.
_SECTION_MESSAGE_ROWS_AND_IGNORED: str = (
    "Section present (row diagnostics and ignored-section marker); "
    "every row is dropped at parse time."
)
_SECTION_MESSAGE_ROWS_ONLY: str = (
    "Section present with row diagnostics; every row is read-only "
    "metadata and never activates EPANET semantics."
)
_SECTION_MESSAGE_IGNORED_ONLY: str = (
    "Section present but ignored at parse time; no row content is "
    "surfaced through this report."
)


# Sprint 33: pinned, module-level warning strings so two reports with
# the same warning trigger never surface spurious string variation.
_WARNING_WNTR_EMPTY_DIAGNOSTICS: str = (
    "Diagnostics from parser='wntr' are empty by construction; the "
    "report reflects only what the WNTR back-end surfaced (nothing) "
    "and is not a parity report against the fallback parser."
)
_WARNING_SURROGATE_INDEX_TEMPLATE: str = (
    "Edge surrogate references edge_index={edge_index} but the supplied "
    "Network has only {edge_count} edges; the diagnostic record is "
    "preserved verbatim and no edge is mutated."
)


# Sprint 33: pinned, module-level limitation strings (the report's
# limitations tuple is deterministic — see :func:`build_import_quality_report`).
_LIMITATION_WNTR_ASYMMETRY: str = (
    "parser='wntr' does not emit Sprint 23-32 diagnostics; the report "
    "is therefore empty / minimal under the WNTR back-end. Use "
    "parser='fallback' for the full diagnostics surface."
)
_LIMITATION_IGNORED_SECTIONS_DROPPED: str = (
    "Ignored sections (CONTROLS / RULES / PATTERNS / ENERGY / EMITTERS / "
    "DEMANDS / QUALITY / SOURCES / REACTIONS / MIXING and inert layout "
    "sections) are dropped at parse time; their rows surface as read-only "
    "metadata only and never activate EPANET semantics."
)
_LIMITATION_STATUS_OPEN_ONLY: str = (
    "STATUS rows accepted as no-ops are OPEN-only; CLOSED / CV / numeric "
    "pump-status declarations still raise at parse time and never reach "
    "the report."
)


@dataclass(frozen=True)
class EpanetImportQualitySectionReport:
    """Read-only per-section entry in an :class:`EpanetImportQualityReport`.

    One entry is emitted per EPANET section that either produced row
    diagnostics (``status_rows`` / ``control_rule_rows`` /
    ``pattern_energy_rows`` / ``emitter_demand_rows`` /
    ``water_quality_rows``) **or** appeared as an ignored-section
    presence record. The two surfaces are deliberately surfaced through
    the same dataclass without double-counting: a section that emits
    both row diagnostics and an ignored-section presence record
    (e.g. ``[CONTROLS]`` with two ``LINK PU1 ...`` rows) surfaces as a
    single entry with ``ignored_present=True`` and ``row_count=2``.

    Attributes
    ----------
    section
        Canonical (upper-case) EPANET section name.
    row_count
        Number of row diagnostics emitted from this section. Mirrors
        :meth:`EpanetImportDiagnostics.row_count_by_section`. ``0`` for
        sections that surface only via ignored-section presence.
    ignored_present
        ``True`` when the section appeared in the source file and is a
        member of :data:`IGNORED_SECTIONS`. Mirrors
        :meth:`EpanetImportDiagnostics.ignored_section_names`. ``False``
        for the ``[STATUS]`` section, which is never in
        :data:`IGNORED_SECTIONS` from Sprint 22 onwards.
    message
        Human-readable explanation of the section's state. Pinned to a
        small set of module-level strings so two reports for the same
        section state never surface spurious string variation.
    """

    section: str
    row_count: int
    ignored_present: bool
    message: str


@dataclass(frozen=True)
class EpanetImportQualitySurrogateReport:
    """Read-only per-edge surrogate entry in an :class:`EpanetImportQualityReport`.

    One entry is emitted per Sprint 32
    :class:`EpanetEdgeSurrogateDiagnostic` record. The fields mirror
    the Sprint 32 surface verbatim — the Sprint 33 report adds no new
    surrogate semantics and never re-derives any of the underlying
    metadata.

    Attributes
    ----------
    edge_index
        Zero-based index into the loaded :class:`Network`'s edge
        arrays, copied directly from the source diagnostic.
    link_id
        Original EPANET link id, preserved case-sensitively.
    link_type
        Canonical source link type (``"VALVE"`` for every Sprint 32
        surrogate today).
    surrogate_kind
        Stable machine-friendly code identifying the surrogate
        approximation (e.g. ``"PRV_FIXED_HEAD_SURROGATE"`` /
        ``"TCV_MINOR_LOSS_SURROGATE"``).
    severity
        Stable severity token (``"INFO"`` / ``"WARNING"`` /
        ``"LIMITATION"``).
    message
        Human-readable explanation of the surrogate, pinned per
        ``surrogate_kind`` in the underlying diagnostic.
    limitations
        Tuple of short human-readable limitations callers may surface
        verbatim.
    """

    edge_index: int
    link_id: str
    link_type: str
    surrogate_kind: str
    severity: str
    message: str
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class EpanetImportQualityReport:
    """Read-only typed import-quality report (Sprint 33).

    Composes the Sprint 23-32 :class:`EpanetImportDiagnostics` surfaces
    into a single immutable report a UI / API / shadow-mode caller can
    render verbatim. The report is structurally read-only: the
    dataclass is ``frozen=True`` and every collection field is an
    immutable tuple (for sequences) or a fresh mapping (for counts).
    No field references the source diagnostics container, so mutating
    the report (which is impossible — every field is immutable) cannot
    affect the source, and mutating the source cannot affect a
    previously-built report.

    Determinism: building the report twice on the same source
    diagnostics returns equal reports — equal tuples in the same order,
    equal mappings with the same keys and values, equal warnings,
    equal limitations. No timestamps or random sampling are involved.

    Attributes
    ----------
    parser
        Which parser produced the source diagnostics. The builder
        validates the token against :data:`_VALID_REPORT_PARSERS`
        (``"fallback"`` / ``"wntr"``) and trusts the caller — it does
        not re-derive this from the diagnostics container.
    total_diagnostic_rows
        Sum of every row count across every row diagnostics channel
        (``status_rows`` + ``control_rule_rows`` +
        ``pattern_energy_rows`` + ``emitter_demand_rows`` +
        ``water_quality_rows``). Mirrors
        :attr:`EpanetImportDiagnosticsSummary.total_diagnostic_rows`.
    ignored_section_count
        Number of ignored-section presence records. Mirrors
        :attr:`EpanetImportDiagnosticsSummary.ignored_section_count`.
    row_count_by_section
        Fresh mapping (canonical-section-ordered) from section name to
        row count. Mirrors
        :meth:`EpanetImportDiagnostics.row_count_by_section`. Sections
        with zero rows are omitted.
    ignored_sections
        Tuple of canonical (upper-case) section names that appeared in
        the source file and are members of :data:`IGNORED_SECTIONS`.
        Source-file order is preserved. Mirrors
        :meth:`EpanetImportDiagnostics.ignored_section_names`.
    sections
        Per-section entries in canonical-section-ordered order. Each
        entry merges the row-diagnostics presence and the
        ignored-section presence for one section, so a section that
        produced both kinds surfaces as a single entry with
        ``ignored_present=True`` and ``row_count > 0``.
    surrogates
        Per-edge surrogate entries, in source / edge-append order
        (the same order :attr:`EpanetImportDiagnostics.edge_surrogates`
        carries).
    surrogate_count_by_kind
        Fresh mapping from surrogate kind to count. Mirrors
        :meth:`EpanetImportDiagnostics.surrogate_count_by_kind`.
    warnings
        Deterministic tuple of human-readable warnings (e.g. empty
        WNTR diagnostics, surrogate edge index out of range when a
        :class:`Network` is supplied). Empty when the report has no
        warnings.
    limitations
        Deterministic tuple of human-readable limitations to surface
        verbatim. Always includes the ``[STATUS]`` open-only and
        ignored-sections-dropped notes; additionally includes the
        WNTR-asymmetry note for ``parser="wntr"``; additionally
        includes one entry per surrogate-kind-specific limitation
        present (de-duplicated, first-occurrence order preserved).
    """

    parser: str
    total_diagnostic_rows: int
    ignored_section_count: int
    row_count_by_section: Mapping[str, int] = field(default_factory=dict)
    ignored_sections: tuple[str, ...] = ()
    sections: tuple[EpanetImportQualitySectionReport, ...] = ()
    surrogates: tuple[EpanetImportQualitySurrogateReport, ...] = ()
    surrogate_count_by_kind: Mapping[str, int] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


def _ordered_section_names(
    row_counts: Mapping[str, int], ignored_names: tuple[str, ...]
) -> tuple[str, ...]:
    """Return the union of section names in deterministic canonical order.

    Canonical sections come first in the
    :data:`_REPORT_SECTION_CANONICAL_ORDER` order. Any unknown / future
    section name not in the canonical list is appended in alphabetical
    order so the report stays deterministic across Python versions and
    dict insertion orders.
    """
    union: set[str] = set(row_counts.keys()) | set(ignored_names)
    ordered: list[str] = []
    for name in _REPORT_SECTION_CANONICAL_ORDER:
        if name in union:
            ordered.append(name)
    unknown = sorted(n for n in union if n not in _REPORT_SECTION_CANONICAL_ORDER)
    ordered.extend(unknown)
    return tuple(ordered)


def _section_message(*, row_count: int, ignored_present: bool) -> str:
    if row_count > 0 and ignored_present:
        return _SECTION_MESSAGE_ROWS_AND_IGNORED
    if row_count > 0:
        return _SECTION_MESSAGE_ROWS_ONLY
    return _SECTION_MESSAGE_IGNORED_ONLY


def _resolve_network_edge_count(network: Network | None) -> int | None:
    """Return ``network``'s edge count, or ``None`` when no network was supplied.

    The accessor stays defensive: if a non-``None`` ``network`` is
    supplied but lacks the documented ``edge_index`` field (e.g. a
    duck-typed test fake), the helper returns ``None`` so the rest of
    the builder treats the input as a no-op rather than raising. The
    builder never mutates ``network``.
    """
    if network is None:
        return None
    edge_index = getattr(network, "edge_index", None)
    if edge_index is None:
        return None
    try:
        shape = edge_index.shape
    except AttributeError:
        return None
    try:
        return int(shape[1])
    except (IndexError, TypeError, ValueError):
        return None


def build_import_quality_report(
    diagnostics: EpanetImportDiagnostics,
    network: Network | None = None,
    *,
    parser: str = "fallback",
) -> EpanetImportQualityReport:
    """Compose an :class:`EpanetImportDiagnostics` into a typed report.

    Sprint 33 — read-only composition over the Sprint 23-32 diagnostic
    surfaces. The builder is pure: it never mutates ``diagnostics`` or
    ``network``, never activates any deferred EPANET semantics, and
    never re-parses the source ``.inp`` file. Calling the builder
    twice on the same inputs returns equal reports.

    Parameters
    ----------
    diagnostics
        A populated :class:`EpanetImportDiagnostics`, typically from
        :func:`load_inp_diagnostics` or
        :func:`load_network_from_inp(..., return_diagnostics=True)`.
        An empty container is accepted and produces an empty /
        minimal report.
    network
        Optional loaded :class:`Network`. When supplied, the builder
        validates every surrogate's ``edge_index`` against
        ``network.edge_index.shape[1]`` and surfaces a deterministic
        warning for any index that falls outside the valid range.
        The ``Network`` itself is **never** mutated. When omitted, no
        edge-range validation is performed.
    parser
        Which parser produced ``diagnostics``. Must be one of
        ``"fallback"`` or ``"wntr"``. Determines the WNTR-asymmetry
        limitation surface.

    Returns
    -------
    EpanetImportQualityReport
        A frozen, immutable report. Every collection field is a
        freshly-allocated tuple or mapping; subsequent mutation of the
        ``diagnostics`` container (which is itself frozen) cannot
        affect the returned report.

    Raises
    ------
    ValueError
        If ``parser`` is not one of :data:`_VALID_REPORT_PARSERS`.
        Every other input (empty diagnostics, ``network=None``,
        diagnostics with row diagnostics but no surrogates, …) is
        accepted as a normal report.
    """
    if parser not in _VALID_REPORT_PARSERS:
        raise ValueError(
            f"parser must be one of {_VALID_REPORT_PARSERS}, got {parser!r}"
        )

    row_counts = diagnostics.row_count_by_section()
    ignored_names = diagnostics.ignored_section_names()
    ignored_set = set(ignored_names)

    section_names = _ordered_section_names(row_counts, ignored_names)
    sections: list[EpanetImportQualitySectionReport] = []
    for name in section_names:
        row_count = int(row_counts.get(name, 0))
        ignored_present = name in ignored_set
        sections.append(
            EpanetImportQualitySectionReport(
                section=name,
                row_count=row_count,
                ignored_present=ignored_present,
                message=_section_message(
                    row_count=row_count, ignored_present=ignored_present
                ),
            )
        )

    edge_count = _resolve_network_edge_count(network)

    surrogate_reports: list[EpanetImportQualitySurrogateReport] = []
    surrogate_warnings: list[str] = []
    surrogate_limitations: list[str] = []
    seen_surrogate_limitations: set[str] = set()
    for rec in diagnostics.edge_surrogates:
        try:
            edge_idx = operator.index(rec.edge_index)
        except TypeError:
            edge_idx = int(rec.edge_index)
        surrogate_reports.append(
            EpanetImportQualitySurrogateReport(
                edge_index=edge_idx,
                link_id=rec.link_id,
                link_type=rec.link_type,
                surrogate_kind=rec.surrogate_kind,
                severity=rec.severity,
                message=rec.message,
                limitations=tuple(rec.limitations),
            )
        )
        if edge_count is not None and (edge_idx < 0 or edge_idx >= edge_count):
            surrogate_warnings.append(
                _WARNING_SURROGATE_INDEX_TEMPLATE.format(
                    edge_index=edge_idx, edge_count=edge_count
                )
            )
        for lim in rec.limitations:
            if lim in seen_surrogate_limitations:
                continue
            seen_surrogate_limitations.add(lim)
            surrogate_limitations.append(lim)

    surrogate_count_by_kind = diagnostics.surrogate_count_by_kind()
    summary = diagnostics.summary()

    warnings: list[str] = []
    if (
        parser == "wntr"
        and summary.total_diagnostic_rows == 0
        and summary.ignored_section_count == 0
        and not diagnostics.edge_surrogates
    ):
        warnings.append(_WARNING_WNTR_EMPTY_DIAGNOSTICS)
    warnings.extend(surrogate_warnings)

    limitations: list[str] = [
        _LIMITATION_STATUS_OPEN_ONLY,
        _LIMITATION_IGNORED_SECTIONS_DROPPED,
    ]
    if parser == "wntr":
        limitations.append(_LIMITATION_WNTR_ASYMMETRY)
    limitations.extend(surrogate_limitations)

    return EpanetImportQualityReport(
        parser=parser,
        total_diagnostic_rows=int(summary.total_diagnostic_rows),
        ignored_section_count=int(summary.ignored_section_count),
        row_count_by_section=dict(row_counts),
        ignored_sections=tuple(ignored_names),
        sections=tuple(sections),
        surrogates=tuple(surrogate_reports),
        surrogate_count_by_kind=dict(surrogate_count_by_kind),
        warnings=tuple(warnings),
        limitations=tuple(limitations),
    )


def load_inp_import_quality_report(
    source: PathLike,
    *,
    parser: str = "fallback",
    units: str = "si",
    default_c_factor: float = 130.0,
) -> EpanetImportQualityReport:
    """Convenience: load an INP path and build its import-quality report.

    Sprint 33 — thin convenience wrapper that pairs
    :func:`aquaoptima.dphm.load_network_from_inp` (with
    ``return_diagnostics=True``) and :func:`build_import_quality_report`.
    The function is read-only: it does not mutate the source file, the
    loaded :class:`Network`, or the returned report. Existing
    :func:`load_network_from_inp` and :func:`load_inp_diagnostics`
    callers are unaffected.

    Parameters mirror :func:`aquaoptima.dphm.load_network_from_inp`,
    except that ``parser="auto"`` is **not** accepted — the
    Sprint 23-32 diagnostics surface is fallback-authoritative and the
    Sprint 33 report's WNTR-asymmetry limitation tracks the back-end
    explicitly. Callers that want WNTR must pass ``parser="wntr"``.

    Parameters
    ----------
    source
        Path to an EPANET INP file (``str`` or ``pathlib.Path``).
    parser
        Either ``"fallback"`` or ``"wntr"``. ``"auto"`` is rejected to
        keep the WNTR-asymmetry limitation surface explicit.
    units
        Output unit family for the loader. Only ``"si"`` is supported;
        passing anything else raises :class:`ValueError` (forwarded
        from :func:`load_network_from_inp`).
    default_c_factor
        Default Hazen-Williams roughness coefficient (default
        ``130.0``). Forwarded to :func:`load_network_from_inp`.

    Returns
    -------
    EpanetImportQualityReport
        The composed report.
    """
    if parser not in _VALID_REPORT_PARSERS:
        raise ValueError(
            f"parser must be one of {_VALID_REPORT_PARSERS}, got {parser!r}"
        )
    network, diagnostics = load_network_from_inp(
        source,
        parser=parser,
        units=units,
        default_c_factor=default_c_factor,
        return_diagnostics=True,
    )
    return build_import_quality_report(diagnostics, network, parser=parser)


__all__ = [
    "EpanetImportQualityReport",
    "EpanetImportQualitySectionReport",
    "EpanetImportQualitySurrogateReport",
    "build_import_quality_report",
    "load_inp_import_quality_report",
]
