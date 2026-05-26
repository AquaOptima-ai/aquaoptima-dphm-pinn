"""Sprint 53 — site data intake contract.

This module defines what an exported / uploaded customer site dataset
must look like for the AquaOptima dPHM / dPL / dPHM-PINN stack to be
testable *without* AMAX and *without* live OT integration. Sprint 53
ships:

* :class:`SiteDataFieldRequirement` — frozen audit row describing one
  expected telemetry field (id, display name, telemetry role,
  required / optional flag, accepted units, expected type,
  description, example tags, quality notes).
* :class:`SiteDataExportSchema` — frozen audit bundle describing the
  shape of a minimum viable export (schema id, site type, timestamp
  field, timezone policy, sampling policy, required + optional
  fields, unit normalization notes, source evidence notes).
* :class:`SiteTagMapTemplate` — frozen audit bundle mapping
  customer / site tag names to canonical AquaOptima pump-system roles
  (timestamp, pump_status, pump_speed, suction_pressure,
  discharge_pressure, flow_rate, tank_level, valve_status, power_kw,
  current_amp, alarm_state, operating_mode).
* :class:`SiteDataQualityRule` — frozen audit row describing one
  quality check the import pipeline must apply (coverage, missingness,
  unit presence, timestamp monotonicity, duplicate timestamps,
  sampling interval drift, pressure / flow plausibility, pump state
  availability, timezone clarity).
* :class:`SiteDataReadinessAssessment` — frozen audit bundle returned
  by :func:`assess_site_data_readiness` describing whether a dataset
  is ``good``, ``usable``, ``poor``, or ``blocked`` for testing
  dPHM / dPL / dPHM-PINN.
* :func:`default_pump_site_data_export_schema` /
  :func:`default_site_tag_map_template` /
  :func:`default_site_data_quality_rules` /
  :func:`assess_site_data_readiness` — canonical helpers.

Boundary (reaffirmed everywhere):

- no live OT binding;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- no live OPC UA / Modbus / CODESYS / SCADA / PLC / MQTT / HTTP /
  database / message-broker client;
- no AMAX hardware probing;
- no credentials, tokens, API keys, license keys, passwords, or
  connection secrets in docs / tests / source.

The module is stdlib-only. ``to_dict`` / ``from_dict`` round trips are
deterministic and tuple ordering is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..base.envelope import ContractError
from ..safety.vocabulary import contains_forbidden_token


# ---------------------------------------------------------------------------
# Canonical vocabularies
# ---------------------------------------------------------------------------


# Canonical pump-system roles. Adding a role is an SDK MINOR bump;
# repurposing or removing is MAJOR. These tokens are the bridge
# between customer/site tag names and the AquaOptima telemetry layer.
PUMP_SITE_CANONICAL_ROLES: tuple[str, ...] = (
    "timestamp",
    "pump_status",
    "pump_running",
    "pump_speed_rpm",
    "vfd_frequency_hz",
    "speed_percent",
    "suction_pressure",
    "discharge_pressure",
    "flow_rate",
    "tank_level",
    "valve_status",
    "pump_power_kw",
    "current_amp",
    "energy_kwh",
    "alarm_state",
    "trip_state",
    "operating_mode",
    "manual_auto_mode",
    "weather_demand_proxy",
)


# Sub-vocabularies used by the readiness assessment.
PUMP_SITE_PUMP_STATE_ROLES: tuple[str, ...] = (
    "pump_status",
    "pump_running",
)

PUMP_SITE_PUMP_SPEED_ROLES: tuple[str, ...] = (
    "pump_speed_rpm",
    "vfd_frequency_hz",
    "speed_percent",
)

PUMP_SITE_HYDRAULIC_ROLES: tuple[str, ...] = (
    "suction_pressure",
    "discharge_pressure",
    "flow_rate",
    "tank_level",
)


# Canonical telemetry-role tokens for a single field requirement. They
# describe how the field is used downstream (observed signal, derived
# series, identifier, status, quality flag). They never authorize a
# write, dispatch, actuation, setpoint, or control surface.
_FIELD_ROLE_TOKENS: frozenset[str] = frozenset(
    {"observed", "status", "derived", "identifier", "quality"}
)


# Canonical readiness grade tokens.
DPHM_READINESS_GRADE_GOOD: str = "good"
DPHM_READINESS_GRADE_USABLE: str = "usable"
DPHM_READINESS_GRADE_POOR: str = "poor"
DPHM_READINESS_GRADE_BLOCKED: str = "blocked"
DPHM_READINESS_GRADE_TOKENS: tuple[str, ...] = (
    DPHM_READINESS_GRADE_GOOD,
    DPHM_READINESS_GRADE_USABLE,
    DPHM_READINESS_GRADE_POOR,
    DPHM_READINESS_GRADE_BLOCKED,
)


# Canonical site-type tokens for the default schema. Hardware-
# independent: every token describes a pump-station class, not a
# vendor or controller.
_SITE_TYPE_TOKENS: frozenset[str] = frozenset(
    {
        "pump_station_single_pump",
        "pump_station_multi_pump",
        "booster_station",
        "wellfield",
        "wastewater_lift_station",
        "generic_pump_system",
    }
)


# Quality-rule check kinds. These describe *what* the rule checks; the
# severity tokens describe how blocking a failure is.
_QUALITY_RULE_KINDS: frozenset[str] = frozenset(
    {
        "coverage",
        "missingness",
        "unit_presence",
        "timestamp_monotonicity",
        "duplicate_timestamps",
        "sampling_interval_drift",
        "pressure_plausibility",
        "flow_plausibility",
        "pump_state_availability",
        "timezone_clarity",
    }
)
_QUALITY_RULE_SEVERITIES: frozenset[str] = frozenset(
    {"info", "warning", "blocking"}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_str(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{name} must be a string, got {type(value).__name__}")
    return value


def _ensure_non_empty_str(name: str, value: Any) -> str:
    text = _ensure_str(name, value)
    if not text:
        raise ContractError(f"{name} must be a non-empty string")
    return text


def _ensure_str_tuple(name: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ContractError(f"{name} must be a tuple")
    out: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise ContractError(
                f"{name} must contain strings, got {type(entry).__name__}"
            )
        out.append(entry)
    return tuple(out)


def _reject_forbidden_tokens(name: str, *values: str) -> None:
    for value in values:
        hits = contains_forbidden_token(value)
        if hits:
            raise ContractError(
                f"{name} carries forbidden vocabulary token(s) "
                f"{sorted(hits)}; SDK contracts must not embed write / "
                "setpoint / command / actuator / control-loop verbs"
            )


def _coerce_str_tuple(name: str, value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        raise ContractError(f"{name} must be a sequence of strings, got a string")
    if not isinstance(value, Sequence):
        raise ContractError(f"{name} must be a sequence")
    out: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise ContractError(
                f"{name} must contain strings, got {type(entry).__name__}"
            )
        out.append(entry)
    return tuple(out)


# ---------------------------------------------------------------------------
# SiteDataFieldRequirement
# ---------------------------------------------------------------------------


_FIELD_REQUIREMENT_FIELDS: tuple[str, ...] = (
    "field_id",
    "display_name",
    "role",
    "required",
    "accepted_units",
    "expected_type",
    "description",
    "example_tags",
    "quality_notes",
)


_FIELD_EXPECTED_TYPE_TOKENS: frozenset[str] = frozenset(
    {
        "datetime",
        "float",
        "int",
        "bool",
        "string",
        "enum",
        "categorical",
    }
)


@dataclass(frozen=True)
class SiteDataFieldRequirement:
    """One expected field in a site export.

    Attributes
    ----------
    field_id
        Canonical role token from :data:`PUMP_SITE_CANONICAL_ROLES`.
    display_name
        Operator-facing display label.
    role
        Telemetry role: ``observed``, ``status``, ``derived``,
        ``identifier``, or ``quality``.
    required
        Whether the field is required for a minimum viable dataset.
    accepted_units
        Tuple of unit strings the SDK accepts for this field (e.g.
        ``("bar", "kPa", "psi", "m")``). May be empty for status /
        identifier fields.
    expected_type
        Canonical expected-type token (``datetime``, ``float``, …).
    description
        Free-form human description.
    example_tags
        Example customer / SCADA tag names that often map to this
        field.
    quality_notes
        Extra notes about quality / acceptable substitutes.
    """

    field_id: str
    display_name: str
    role: str
    required: bool
    accepted_units: tuple[str, ...] = ()
    expected_type: str = "float"
    description: str = ""
    example_tags: tuple[str, ...] = ()
    quality_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_non_empty_str("SiteDataFieldRequirement.field_id", self.field_id)
        _ensure_non_empty_str(
            "SiteDataFieldRequirement.display_name", self.display_name
        )
        if self.field_id not in PUMP_SITE_CANONICAL_ROLES:
            raise ContractError(
                f"SiteDataFieldRequirement.field_id {self.field_id!r} is not a "
                f"canonical pump-site role; allowed: "
                f"{list(PUMP_SITE_CANONICAL_ROLES)}"
            )
        if self.role not in _FIELD_ROLE_TOKENS:
            raise ContractError(
                f"SiteDataFieldRequirement.role {self.role!r} is not a canonical "
                f"telemetry role; allowed: {sorted(_FIELD_ROLE_TOKENS)}"
            )
        if not isinstance(self.required, bool):
            raise ContractError(
                "SiteDataFieldRequirement.required must be a bool"
            )
        units = _ensure_str_tuple(
            "SiteDataFieldRequirement.accepted_units", self.accepted_units
        )
        for unit in units:
            if not unit:
                raise ContractError(
                    "SiteDataFieldRequirement.accepted_units must contain "
                    "non-empty strings"
                )
        if self.expected_type not in _FIELD_EXPECTED_TYPE_TOKENS:
            raise ContractError(
                f"SiteDataFieldRequirement.expected_type {self.expected_type!r} "
                f"is not a canonical expected-type token; allowed: "
                f"{sorted(_FIELD_EXPECTED_TYPE_TOKENS)}"
            )
        _ensure_str("SiteDataFieldRequirement.description", self.description)
        example_tags = _ensure_str_tuple(
            "SiteDataFieldRequirement.example_tags", self.example_tags
        )
        quality_notes = _ensure_str_tuple(
            "SiteDataFieldRequirement.quality_notes", self.quality_notes
        )
        _reject_forbidden_tokens(
            "SiteDataFieldRequirement",
            self.field_id,
            self.display_name,
            self.role,
            self.description,
            *units,
            *example_tags,
            *quality_notes,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "display_name": self.display_name,
            "role": self.role,
            "required": self.required,
            "accepted_units": list(self.accepted_units),
            "expected_type": self.expected_type,
            "description": self.description,
            "example_tags": list(self.example_tags),
            "quality_notes": list(self.quality_notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SiteDataFieldRequirement":
        if not isinstance(data, Mapping):
            raise ContractError(
                "SiteDataFieldRequirement.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        unknown = set(data.keys()) - set(_FIELD_REQUIREMENT_FIELDS)
        if unknown:
            raise ContractError(
                "SiteDataFieldRequirement received unknown fields: "
                f"{sorted(unknown)}"
            )
        missing = [
            key for key in ("field_id", "display_name", "role", "required")
            if key not in data
        ]
        if missing:
            raise ContractError(
                f"SiteDataFieldRequirement missing required fields: {missing}"
            )
        return cls(
            field_id=str(data["field_id"]),
            display_name=str(data["display_name"]),
            role=str(data["role"]),
            required=bool(data["required"]),
            accepted_units=tuple(
                str(u) for u in data.get("accepted_units", ()) or ()
            ),
            expected_type=str(data.get("expected_type", "float")),
            description=str(data.get("description", "")),
            example_tags=tuple(
                str(t) for t in data.get("example_tags", ()) or ()
            ),
            quality_notes=tuple(
                str(n) for n in data.get("quality_notes", ()) or ()
            ),
        )


# ---------------------------------------------------------------------------
# SiteDataExportSchema
# ---------------------------------------------------------------------------


_EXPORT_SCHEMA_FIELDS: tuple[str, ...] = (
    "schema_id",
    "site_type",
    "timestamp_field",
    "timezone_policy",
    "sampling_policy",
    "required_fields",
    "optional_fields",
    "unit_normalization_notes",
    "source_evidence_notes",
    "safety_notes",
)


@dataclass(frozen=True)
class SiteDataExportSchema:
    """Shape of a minimum viable pump-system site export.

    Sprint 53 is hardware-independent. The schema describes the
    expected CSV / historian / SCADA-export contents that a customer
    or operator must hand to AquaOptima so dPHM / dPL / dPHM-PINN can
    be tested without AMAX and without live OT integration.
    """

    schema_id: str
    site_type: str
    timestamp_field: str
    timezone_policy: str
    sampling_policy: str
    required_fields: tuple[SiteDataFieldRequirement, ...] = ()
    optional_fields: tuple[SiteDataFieldRequirement, ...] = ()
    unit_normalization_notes: tuple[str, ...] = ()
    source_evidence_notes: tuple[str, ...] = ()
    safety_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_non_empty_str("SiteDataExportSchema.schema_id", self.schema_id)
        if self.site_type not in _SITE_TYPE_TOKENS:
            raise ContractError(
                f"SiteDataExportSchema.site_type {self.site_type!r} is not a "
                f"canonical site type; allowed: {sorted(_SITE_TYPE_TOKENS)}"
            )
        _ensure_non_empty_str(
            "SiteDataExportSchema.timestamp_field", self.timestamp_field
        )
        _ensure_non_empty_str(
            "SiteDataExportSchema.timezone_policy", self.timezone_policy
        )
        _ensure_non_empty_str(
            "SiteDataExportSchema.sampling_policy", self.sampling_policy
        )
        for name, value in (
            ("required_fields", self.required_fields),
            ("optional_fields", self.optional_fields),
        ):
            if not isinstance(value, tuple):
                raise ContractError(
                    f"SiteDataExportSchema.{name} must be a tuple"
                )
            for entry in value:
                if not isinstance(entry, SiteDataFieldRequirement):
                    raise ContractError(
                        f"SiteDataExportSchema.{name} must contain "
                        "SiteDataFieldRequirement instances, got "
                        f"{type(entry).__name__}"
                    )
        # Required-flag consistency.
        for entry in self.required_fields:
            if not entry.required:
                raise ContractError(
                    "SiteDataExportSchema.required_fields must contain only "
                    f"required=True entries; {entry.field_id!r} has required=False"
                )
        for entry in self.optional_fields:
            if entry.required:
                raise ContractError(
                    "SiteDataExportSchema.optional_fields must contain only "
                    f"required=False entries; {entry.field_id!r} has required=True"
                )
        # Duplicate field_ids across required + optional are not allowed.
        seen: set[str] = set()
        for entry in (*self.required_fields, *self.optional_fields):
            if entry.field_id in seen:
                raise ContractError(
                    f"SiteDataExportSchema contains duplicate field_id "
                    f"{entry.field_id!r}"
                )
            seen.add(entry.field_id)
        notes_norm = _ensure_str_tuple(
            "SiteDataExportSchema.unit_normalization_notes",
            self.unit_normalization_notes,
        )
        notes_src = _ensure_str_tuple(
            "SiteDataExportSchema.source_evidence_notes",
            self.source_evidence_notes,
        )
        notes_safety = _ensure_str_tuple(
            "SiteDataExportSchema.safety_notes", self.safety_notes
        )
        _reject_forbidden_tokens(
            "SiteDataExportSchema",
            self.schema_id,
            self.site_type,
            self.timestamp_field,
            self.timezone_policy,
            self.sampling_policy,
            *notes_norm,
            *notes_src,
            *notes_safety,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "site_type": self.site_type,
            "timestamp_field": self.timestamp_field,
            "timezone_policy": self.timezone_policy,
            "sampling_policy": self.sampling_policy,
            "required_fields": [f.to_dict() for f in self.required_fields],
            "optional_fields": [f.to_dict() for f in self.optional_fields],
            "unit_normalization_notes": list(self.unit_normalization_notes),
            "source_evidence_notes": list(self.source_evidence_notes),
            "safety_notes": list(self.safety_notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SiteDataExportSchema":
        if not isinstance(data, Mapping):
            raise ContractError(
                "SiteDataExportSchema.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        unknown = set(data.keys()) - set(_EXPORT_SCHEMA_FIELDS)
        if unknown:
            raise ContractError(
                f"SiteDataExportSchema received unknown fields: {sorted(unknown)}"
            )
        missing = [
            key
            for key in (
                "schema_id",
                "site_type",
                "timestamp_field",
                "timezone_policy",
                "sampling_policy",
            )
            if key not in data
        ]
        if missing:
            raise ContractError(
                f"SiteDataExportSchema missing required fields: {missing}"
            )
        required_fields = tuple(
            SiteDataFieldRequirement.from_dict(entry)
            for entry in data.get("required_fields", ()) or ()
        )
        optional_fields = tuple(
            SiteDataFieldRequirement.from_dict(entry)
            for entry in data.get("optional_fields", ()) or ()
        )
        return cls(
            schema_id=str(data["schema_id"]),
            site_type=str(data["site_type"]),
            timestamp_field=str(data["timestamp_field"]),
            timezone_policy=str(data["timezone_policy"]),
            sampling_policy=str(data["sampling_policy"]),
            required_fields=required_fields,
            optional_fields=optional_fields,
            unit_normalization_notes=tuple(
                str(n) for n in data.get("unit_normalization_notes", ()) or ()
            ),
            source_evidence_notes=tuple(
                str(n) for n in data.get("source_evidence_notes", ()) or ()
            ),
            safety_notes=tuple(
                str(n) for n in data.get("safety_notes", ()) or ()
            ),
        )


# ---------------------------------------------------------------------------
# SiteTagMapTemplate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SiteTagMapTemplateEntry:
    """One row in a site tag map template.

    Attributes
    ----------
    canonical_role
        Canonical pump-system role token from
        :data:`PUMP_SITE_CANONICAL_ROLES`.
    example_tag
        Example customer / site tag string (a non-empty placeholder).
    notes
        Free-form notes about the customer-supplied tag (units,
        common aliases, mapping caveats).
    """

    canonical_role: str
    example_tag: str
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.canonical_role not in PUMP_SITE_CANONICAL_ROLES:
            raise ContractError(
                "SiteTagMapTemplateEntry.canonical_role "
                f"{self.canonical_role!r} is not a canonical pump-site role"
            )
        _ensure_non_empty_str(
            "SiteTagMapTemplateEntry.example_tag", self.example_tag
        )
        notes = _ensure_str_tuple("SiteTagMapTemplateEntry.notes", self.notes)
        _reject_forbidden_tokens(
            "SiteTagMapTemplateEntry",
            self.canonical_role,
            self.example_tag,
            *notes,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_role": self.canonical_role,
            "example_tag": self.example_tag,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SiteTagMapTemplateEntry":
        if not isinstance(data, Mapping):
            raise ContractError(
                "SiteTagMapTemplateEntry.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        unknown = set(data.keys()) - {"canonical_role", "example_tag", "notes"}
        if unknown:
            raise ContractError(
                "SiteTagMapTemplateEntry received unknown fields: "
                f"{sorted(unknown)}"
            )
        missing = [
            key for key in ("canonical_role", "example_tag") if key not in data
        ]
        if missing:
            raise ContractError(
                f"SiteTagMapTemplateEntry missing required fields: {missing}"
            )
        return cls(
            canonical_role=str(data["canonical_role"]),
            example_tag=str(data["example_tag"]),
            notes=tuple(str(n) for n in data.get("notes", ()) or ()),
        )


@dataclass(frozen=True)
class SiteTagMapTemplate:
    """Customer-/site-tag → canonical AquaOptima role template."""

    template_id: str
    site_type: str
    entries: tuple[SiteTagMapTemplateEntry, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_non_empty_str("SiteTagMapTemplate.template_id", self.template_id)
        if self.site_type not in _SITE_TYPE_TOKENS:
            raise ContractError(
                f"SiteTagMapTemplate.site_type {self.site_type!r} is not a "
                "canonical site type"
            )
        if not isinstance(self.entries, tuple):
            raise ContractError("SiteTagMapTemplate.entries must be a tuple")
        seen_roles: set[str] = set()
        for entry in self.entries:
            if not isinstance(entry, SiteTagMapTemplateEntry):
                raise ContractError(
                    "SiteTagMapTemplate.entries must contain "
                    "SiteTagMapTemplateEntry instances, got "
                    f"{type(entry).__name__}"
                )
            if entry.canonical_role in seen_roles:
                raise ContractError(
                    "SiteTagMapTemplate.entries contains duplicate "
                    f"canonical_role {entry.canonical_role!r}"
                )
            seen_roles.add(entry.canonical_role)
        notes = _ensure_str_tuple("SiteTagMapTemplate.notes", self.notes)
        _reject_forbidden_tokens(
            "SiteTagMapTemplate",
            self.template_id,
            self.site_type,
            *notes,
        )

    def canonical_roles(self) -> tuple[str, ...]:
        return tuple(entry.canonical_role for entry in self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "site_type": self.site_type,
            "entries": [e.to_dict() for e in self.entries],
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SiteTagMapTemplate":
        if not isinstance(data, Mapping):
            raise ContractError(
                "SiteTagMapTemplate.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        unknown = set(data.keys()) - {"template_id", "site_type", "entries", "notes"}
        if unknown:
            raise ContractError(
                f"SiteTagMapTemplate received unknown fields: {sorted(unknown)}"
            )
        missing = [
            key for key in ("template_id", "site_type") if key not in data
        ]
        if missing:
            raise ContractError(
                f"SiteTagMapTemplate missing required fields: {missing}"
            )
        entries = tuple(
            SiteTagMapTemplateEntry.from_dict(entry)
            for entry in data.get("entries", ()) or ()
        )
        return cls(
            template_id=str(data["template_id"]),
            site_type=str(data["site_type"]),
            entries=entries,
            notes=tuple(str(n) for n in data.get("notes", ()) or ()),
        )


# ---------------------------------------------------------------------------
# SiteDataQualityRule
# ---------------------------------------------------------------------------


_QUALITY_RULE_FIELDS: tuple[str, ...] = (
    "rule_id",
    "check_kind",
    "severity",
    "description",
    "applies_to_roles",
    "remediation_notes",
)


@dataclass(frozen=True)
class SiteDataQualityRule:
    """One data-quality check the import pipeline applies."""

    rule_id: str
    check_kind: str
    severity: str
    description: str
    applies_to_roles: tuple[str, ...] = ()
    remediation_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_non_empty_str("SiteDataQualityRule.rule_id", self.rule_id)
        if self.check_kind not in _QUALITY_RULE_KINDS:
            raise ContractError(
                f"SiteDataQualityRule.check_kind {self.check_kind!r} is not a "
                f"canonical check kind; allowed: {sorted(_QUALITY_RULE_KINDS)}"
            )
        if self.severity not in _QUALITY_RULE_SEVERITIES:
            raise ContractError(
                f"SiteDataQualityRule.severity {self.severity!r} is not a "
                f"canonical severity; allowed: "
                f"{sorted(_QUALITY_RULE_SEVERITIES)}"
            )
        _ensure_non_empty_str(
            "SiteDataQualityRule.description", self.description
        )
        roles = _ensure_str_tuple(
            "SiteDataQualityRule.applies_to_roles", self.applies_to_roles
        )
        for role in roles:
            if role not in PUMP_SITE_CANONICAL_ROLES:
                raise ContractError(
                    f"SiteDataQualityRule.applies_to_roles entry {role!r} is "
                    "not a canonical pump-site role"
                )
        notes = _ensure_str_tuple(
            "SiteDataQualityRule.remediation_notes", self.remediation_notes
        )
        _reject_forbidden_tokens(
            "SiteDataQualityRule",
            self.rule_id,
            self.check_kind,
            self.severity,
            self.description,
            *notes,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "check_kind": self.check_kind,
            "severity": self.severity,
            "description": self.description,
            "applies_to_roles": list(self.applies_to_roles),
            "remediation_notes": list(self.remediation_notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SiteDataQualityRule":
        if not isinstance(data, Mapping):
            raise ContractError(
                "SiteDataQualityRule.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        unknown = set(data.keys()) - set(_QUALITY_RULE_FIELDS)
        if unknown:
            raise ContractError(
                f"SiteDataQualityRule received unknown fields: {sorted(unknown)}"
            )
        missing = [
            key
            for key in ("rule_id", "check_kind", "severity", "description")
            if key not in data
        ]
        if missing:
            raise ContractError(
                f"SiteDataQualityRule missing required fields: {missing}"
            )
        return cls(
            rule_id=str(data["rule_id"]),
            check_kind=str(data["check_kind"]),
            severity=str(data["severity"]),
            description=str(data["description"]),
            applies_to_roles=tuple(
                str(r) for r in data.get("applies_to_roles", ()) or ()
            ),
            remediation_notes=tuple(
                str(n) for n in data.get("remediation_notes", ()) or ()
            ),
        )


# ---------------------------------------------------------------------------
# SiteDataReadinessAssessment
# ---------------------------------------------------------------------------


_READINESS_FIELDS: tuple[str, ...] = (
    "schema_id",
    "grade",
    "available_fields",
    "missing_required_fields",
    "optional_fields_present",
    "blocking_gaps",
    "warnings",
    "recommendation",
    "safety_notes",
)


@dataclass(frozen=True)
class SiteDataReadinessAssessment:
    """Verdict on whether a candidate dataset is ready for dPHM testing.

    Grades:

    * ``good`` — enough fields, units, timestamp coverage, and
      hydraulic measurements for dPHM testing without AMAX.
    * ``usable`` — enough for limited replay / diagnostics with
      caveats.
    * ``poor`` — can inspect the data but not confidently test dPHM
      because key optional fields are absent.
    * ``blocked`` — missing timestamp, missing pump state, or missing
      all hydraulic measurements; dPHM testing cannot proceed.
    """

    schema_id: str
    grade: str
    available_fields: tuple[str, ...] = ()
    missing_required_fields: tuple[str, ...] = ()
    optional_fields_present: tuple[str, ...] = ()
    blocking_gaps: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    recommendation: str = ""
    safety_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_non_empty_str(
            "SiteDataReadinessAssessment.schema_id", self.schema_id
        )
        if self.grade not in DPHM_READINESS_GRADE_TOKENS:
            raise ContractError(
                f"SiteDataReadinessAssessment.grade {self.grade!r} is not a "
                f"canonical readiness grade; allowed: "
                f"{list(DPHM_READINESS_GRADE_TOKENS)}"
            )
        avail = _ensure_str_tuple(
            "SiteDataReadinessAssessment.available_fields",
            self.available_fields,
        )
        missing = _ensure_str_tuple(
            "SiteDataReadinessAssessment.missing_required_fields",
            self.missing_required_fields,
        )
        optional = _ensure_str_tuple(
            "SiteDataReadinessAssessment.optional_fields_present",
            self.optional_fields_present,
        )
        gaps = _ensure_str_tuple(
            "SiteDataReadinessAssessment.blocking_gaps", self.blocking_gaps
        )
        warns = _ensure_str_tuple(
            "SiteDataReadinessAssessment.warnings", self.warnings
        )
        _ensure_str(
            "SiteDataReadinessAssessment.recommendation", self.recommendation
        )
        notes = _ensure_str_tuple(
            "SiteDataReadinessAssessment.safety_notes", self.safety_notes
        )
        _reject_forbidden_tokens(
            "SiteDataReadinessAssessment",
            self.schema_id,
            self.grade,
            self.recommendation,
            *avail,
            *missing,
            *optional,
            *gaps,
            *warns,
            *notes,
        )
        if self.grade == DPHM_READINESS_GRADE_BLOCKED and not self.blocking_gaps:
            raise ContractError(
                "SiteDataReadinessAssessment.blocking_gaps must be non-empty "
                "when grade is 'blocked'"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "grade": self.grade,
            "available_fields": list(self.available_fields),
            "missing_required_fields": list(self.missing_required_fields),
            "optional_fields_present": list(self.optional_fields_present),
            "blocking_gaps": list(self.blocking_gaps),
            "warnings": list(self.warnings),
            "recommendation": self.recommendation,
            "safety_notes": list(self.safety_notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SiteDataReadinessAssessment":
        if not isinstance(data, Mapping):
            raise ContractError(
                "SiteDataReadinessAssessment.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        unknown = set(data.keys()) - set(_READINESS_FIELDS)
        if unknown:
            raise ContractError(
                "SiteDataReadinessAssessment received unknown fields: "
                f"{sorted(unknown)}"
            )
        missing = [
            key for key in ("schema_id", "grade") if key not in data
        ]
        if missing:
            raise ContractError(
                f"SiteDataReadinessAssessment missing required fields: {missing}"
            )
        return cls(
            schema_id=str(data["schema_id"]),
            grade=str(data["grade"]),
            available_fields=tuple(
                str(f) for f in data.get("available_fields", ()) or ()
            ),
            missing_required_fields=tuple(
                str(f) for f in data.get("missing_required_fields", ()) or ()
            ),
            optional_fields_present=tuple(
                str(f) for f in data.get("optional_fields_present", ()) or ()
            ),
            blocking_gaps=tuple(
                str(g) for g in data.get("blocking_gaps", ()) or ()
            ),
            warnings=tuple(str(w) for w in data.get("warnings", ()) or ()),
            recommendation=str(data.get("recommendation", "")),
            safety_notes=tuple(
                str(n) for n in data.get("safety_notes", ()) or ()
            ),
        )


# ---------------------------------------------------------------------------
# Canonical helpers — default pump-site schema, tag map, and quality rules
# ---------------------------------------------------------------------------


_DEFAULT_SCHEMA_ID: str = "aquaoptima_pump_site_minimum_viable_v1"
_DEFAULT_TAG_MAP_ID: str = "aquaoptima_pump_site_tag_map_template_v1"


def default_pump_site_data_export_schema() -> SiteDataExportSchema:
    """Canonical Sprint 53 schema for a minimum viable pump-system export.

    The schema describes what an exported / uploaded site dataset
    must contain for dPHM / dPL / dPHM-PINN to be tested without AMAX
    and without live OT integration. It carries no live binding, no
    write surface, and no actuator semantics.
    """

    required_fields: tuple[SiteDataFieldRequirement, ...] = (
        SiteDataFieldRequirement(
            field_id="timestamp",
            display_name="Timestamp",
            role="identifier",
            required=True,
            expected_type="datetime",
            description=(
                "Monotonic timestamp for each sample. ISO-8601 strongly "
                "preferred; clarify timezone in the schema timezone policy."
            ),
            example_tags=("Timestamp", "TS", "DateTime", "scada_timestamp"),
            quality_notes=(
                "must be strictly monotonic per pump",
                "duplicate timestamps are a blocking quality issue",
            ),
        ),
        SiteDataFieldRequirement(
            field_id="pump_status",
            display_name="Pump status",
            role="status",
            required=True,
            expected_type="enum",
            description=(
                "Pump on/off status or equivalent run/stop indicator. "
                "Boolean or enum is acceptable; the pipeline normalises to "
                "an on/off semantic."
            ),
            example_tags=("PUMP_STATUS", "P1_RUN", "PUMP_ON"),
            quality_notes=(
                "pump_running boolean acceptable substitute",
                "missing pump state is a blocking gap",
            ),
        ),
        SiteDataFieldRequirement(
            field_id="discharge_pressure",
            display_name="Discharge pressure",
            role="observed",
            required=True,
            accepted_units=("bar", "kPa", "psi", "m", "mWC"),
            expected_type="float",
            description=(
                "Pressure on the pump discharge side. At least one pressure "
                "channel must be present for a minimum viable dataset."
            ),
            example_tags=("PT_DISCHARGE", "P_OUT", "DISCH_PR"),
            quality_notes=(
                "units must be reported",
                "suction_pressure acceptable substitute if discharge missing",
            ),
        ),
    )

    optional_fields: tuple[SiteDataFieldRequirement, ...] = (
        SiteDataFieldRequirement(
            field_id="pump_running",
            display_name="Pump running flag",
            role="status",
            required=False,
            expected_type="bool",
            description=(
                "Boolean run flag. Acceptable substitute for "
                "pump_status when only a boolean is exported."
            ),
            example_tags=("P1_RUNNING", "PUMP_RUN_FLAG"),
        ),
        SiteDataFieldRequirement(
            field_id="pump_speed_rpm",
            display_name="Pump speed (RPM)",
            role="observed",
            required=False,
            accepted_units=("rpm",),
            expected_type="float",
            description=(
                "Mechanical pump speed in revolutions per minute. Required "
                "for VFD-driven pumps if a frequency or percent-speed proxy "
                "is unavailable."
            ),
            example_tags=("PUMP_RPM", "P1_SPEED_RPM"),
        ),
        SiteDataFieldRequirement(
            field_id="vfd_frequency_hz",
            display_name="VFD output frequency (Hz)",
            role="observed",
            required=False,
            accepted_units=("Hz",),
            expected_type="float",
            description=(
                "Variable frequency drive output frequency in hertz. "
                "Acceptable speed proxy when RPM is unavailable."
            ),
            example_tags=("VFD_HZ", "DRIVE_FREQ"),
        ),
        SiteDataFieldRequirement(
            field_id="speed_percent",
            display_name="Pump speed (percent)",
            role="observed",
            required=False,
            accepted_units=("percent", "%"),
            expected_type="float",
            description=(
                "Pump speed as a percentage of rated. Acceptable speed "
                "proxy when neither RPM nor VFD frequency is exported."
            ),
            example_tags=("SPEED_PCT", "VFD_OUT_PCT"),
        ),
        SiteDataFieldRequirement(
            field_id="suction_pressure",
            display_name="Suction pressure",
            role="observed",
            required=False,
            accepted_units=("bar", "kPa", "psi", "m", "mWC"),
            expected_type="float",
            description="Pressure on the pump suction side.",
            example_tags=("PT_SUCTION", "P_IN", "SUCT_PR"),
        ),
        SiteDataFieldRequirement(
            field_id="flow_rate",
            display_name="Flow rate",
            role="observed",
            required=False,
            accepted_units=("m3/h", "L/s", "gpm", "m3/s"),
            expected_type="float",
            description=(
                "Volumetric flow rate. Strongly recommended for hydraulic "
                "model testing; if absent, a tank-level trend is the "
                "minimum hydraulic-output substitute."
            ),
            example_tags=("FT_DISCHARGE", "FLOW_RATE", "Q_OUT"),
        ),
        SiteDataFieldRequirement(
            field_id="tank_level",
            display_name="Tank level",
            role="observed",
            required=False,
            accepted_units=("m", "ft", "percent", "%"),
            expected_type="float",
            description=(
                "Tank or reservoir level trend. Acceptable hydraulic-output "
                "substitute when no flow meter is available."
            ),
            example_tags=("LT_TANK", "TANK_LVL"),
        ),
        SiteDataFieldRequirement(
            field_id="valve_status",
            display_name="Valve status",
            role="status",
            required=False,
            expected_type="enum",
            description="Discharge or isolation valve open / closed / position.",
            example_tags=("VALVE_OPEN", "V1_POS"),
        ),
        SiteDataFieldRequirement(
            field_id="pump_power_kw",
            display_name="Pump power (kW)",
            role="observed",
            required=False,
            accepted_units=("kW",),
            expected_type="float",
            description="Real electrical power drawn by the pump.",
            example_tags=("P1_KW", "PUMP_POWER"),
        ),
        SiteDataFieldRequirement(
            field_id="current_amp",
            display_name="Motor current (A)",
            role="observed",
            required=False,
            accepted_units=("A",),
            expected_type="float",
            description="Motor current in amps.",
            example_tags=("P1_AMP", "MOTOR_CURRENT"),
        ),
        SiteDataFieldRequirement(
            field_id="energy_kwh",
            display_name="Energy (kWh)",
            role="observed",
            required=False,
            accepted_units=("kWh",),
            expected_type="float",
            description="Cumulative energy meter or per-interval kWh.",
            example_tags=("ENERGY_KWH", "P1_ENERGY"),
        ),
        SiteDataFieldRequirement(
            field_id="alarm_state",
            display_name="Alarm state",
            role="status",
            required=False,
            expected_type="enum",
            description="Site alarm / fault state aggregator.",
            example_tags=("ALARM_STATE", "FAULT_CODE"),
        ),
        SiteDataFieldRequirement(
            field_id="trip_state",
            display_name="Trip state",
            role="status",
            required=False,
            expected_type="enum",
            description="Motor / pump trip indicator.",
            example_tags=("TRIP_STATE", "P1_TRIP"),
        ),
        SiteDataFieldRequirement(
            field_id="operating_mode",
            display_name="Operating mode",
            role="status",
            required=False,
            expected_type="enum",
            description=(
                "Operating mode label (manual / auto / cascade / "
                "remote). Useful for filtering training windows."
            ),
            example_tags=("OP_MODE", "PUMP_MODE"),
        ),
        SiteDataFieldRequirement(
            field_id="manual_auto_mode",
            display_name="Manual / auto mode",
            role="status",
            required=False,
            expected_type="bool",
            description="Boolean manual / auto switch.",
            example_tags=("MAN_AUTO", "AUTO_FLAG"),
        ),
        SiteDataFieldRequirement(
            field_id="weather_demand_proxy",
            display_name="Weather / demand proxy",
            role="observed",
            required=False,
            accepted_units=("C", "F", "mm", "m3/h"),
            expected_type="float",
            description=(
                "Optional weather, ambient, or downstream demand proxy "
                "channel that helps explain observed flow / pressure."
            ),
            example_tags=("TEMP_AMBIENT", "RAIN_MM", "DEMAND_PROXY"),
        ),
    )

    return SiteDataExportSchema(
        schema_id=_DEFAULT_SCHEMA_ID,
        site_type="generic_pump_system",
        timestamp_field="timestamp",
        timezone_policy=(
            "Timestamps must be either UTC or carry an explicit IANA "
            "timezone label. Mixed-offset or unlabeled timestamps must be "
            "clarified before import."
        ),
        sampling_policy=(
            "Target sampling interval 1 s to 60 s. The schema accepts "
            "irregular sampling; the import pipeline will measure interval "
            "drift and flag it as a quality warning."
        ),
        required_fields=required_fields,
        optional_fields=optional_fields,
        unit_normalization_notes=(
            "Pressure channels must declare units; pipeline normalises "
            "bar / kPa / psi / m / mWC to a single canonical unit before "
            "use.",
            "Flow channels must declare units; pipeline normalises "
            "m3/h / L/s / gpm / m3/s to a single canonical unit.",
            "Speed channels accept rpm, Hz, or percent; at least one is "
            "required for VFD-driven pumps.",
        ),
        source_evidence_notes=(
            "Acceptable export formats: CSV, Parquet, historian export, "
            "SCADA archive dump. Tag-mapping spreadsheets are required so "
            "customer tag names can be linked to canonical roles.",
            "No live OT binding is established; AquaOptima reads only "
            "the supplied export.",
        ),
        safety_notes=(
            "no live OT binding",
            "no PLC/PAC/SCADA write",
            "no command emission",
            "no setpoint output",
            "no control-loop closure",
            "Sprint 53 reads only an exported / uploaded dataset; the "
            "site PLC retains direct VFD / pump / actuator authority.",
        ),
    )


def default_site_tag_map_template() -> SiteTagMapTemplate:
    """Canonical Sprint 53 customer-/site-tag → canonical role template."""

    entries: tuple[SiteTagMapTemplateEntry, ...] = (
        SiteTagMapTemplateEntry(
            canonical_role="timestamp",
            example_tag="scada_timestamp",
            notes=("ISO-8601 preferred", "clarify timezone in tag map"),
        ),
        SiteTagMapTemplateEntry(
            canonical_role="pump_status",
            example_tag="PUMP_STATUS",
            notes=("on / off / running enum",),
        ),
        SiteTagMapTemplateEntry(
            canonical_role="pump_speed_rpm",
            example_tag="PUMP_SPEED_RPM",
            notes=("required for VFD pumps if Hz / percent missing",),
        ),
        SiteTagMapTemplateEntry(
            canonical_role="suction_pressure",
            example_tag="PT_SUCTION",
            notes=("declare units",),
        ),
        SiteTagMapTemplateEntry(
            canonical_role="discharge_pressure",
            example_tag="PT_DISCHARGE",
            notes=("declare units", "primary pressure channel"),
        ),
        SiteTagMapTemplateEntry(
            canonical_role="flow_rate",
            example_tag="FT_DISCHARGE",
            notes=("strongly recommended for dPHM testing",),
        ),
        SiteTagMapTemplateEntry(
            canonical_role="tank_level",
            example_tag="LT_TANK",
            notes=("acceptable hydraulic substitute when flow missing",),
        ),
        SiteTagMapTemplateEntry(
            canonical_role="valve_status",
            example_tag="V1_OPEN",
            notes=("position or open / closed enum",),
        ),
        SiteTagMapTemplateEntry(
            canonical_role="pump_power_kw",
            example_tag="P1_KW",
            notes=("real power in kW",),
        ),
        SiteTagMapTemplateEntry(
            canonical_role="current_amp",
            example_tag="P1_AMP",
            notes=("motor current in amps",),
        ),
        SiteTagMapTemplateEntry(
            canonical_role="alarm_state",
            example_tag="ALARM_STATE",
            notes=("site / pump alarm aggregator",),
        ),
        SiteTagMapTemplateEntry(
            canonical_role="operating_mode",
            example_tag="OP_MODE",
            notes=("manual / auto / cascade / remote",),
        ),
    )

    return SiteTagMapTemplate(
        template_id=_DEFAULT_TAG_MAP_ID,
        site_type="generic_pump_system",
        entries=entries,
        notes=(
            "Customer-supplied tag names map to canonical pump-system "
            "roles. The template is hardware-independent and does not "
            "assume AMAX, CODESYS, OPC UA, or any vendor controller.",
            "no live OT binding",
            "no PLC/PAC/SCADA write",
        ),
    )


def default_site_data_quality_rules() -> tuple[SiteDataQualityRule, ...]:
    """Canonical Sprint 53 data-quality rule set."""

    return (
        SiteDataQualityRule(
            rule_id="coverage_min_window",
            check_kind="coverage",
            severity="blocking",
            description=(
                "Dataset must cover a minimum continuous window so dPHM "
                "training has enough data; pipeline reports the actual "
                "covered duration."
            ),
            applies_to_roles=("timestamp",),
            remediation_notes=(
                "Request a longer export window if coverage is below the "
                "minimum.",
            ),
        ),
        SiteDataQualityRule(
            rule_id="missingness_per_channel",
            check_kind="missingness",
            severity="warning",
            description=(
                "Per-channel missing-fraction must be below the configured "
                "threshold; otherwise the channel is flagged."
            ),
            applies_to_roles=(
                "discharge_pressure",
                "suction_pressure",
                "flow_rate",
                "tank_level",
                "pump_power_kw",
            ),
            remediation_notes=(
                "Confirm tag presence in historian or request alternative "
                "channel.",
            ),
        ),
        SiteDataQualityRule(
            rule_id="unit_presence_required",
            check_kind="unit_presence",
            severity="blocking",
            description=(
                "Pressure and flow / tank-level channels must report units "
                "either in tag metadata or in the supplied tag-map "
                "spreadsheet."
            ),
            applies_to_roles=(
                "discharge_pressure",
                "suction_pressure",
                "flow_rate",
                "tank_level",
            ),
            remediation_notes=(
                "Ask the customer for the engineering unit for each "
                "channel.",
            ),
        ),
        SiteDataQualityRule(
            rule_id="timestamp_monotonicity",
            check_kind="timestamp_monotonicity",
            severity="blocking",
            description=(
                "Timestamps must be strictly monotonic per pump after "
                "timezone normalisation."
            ),
            applies_to_roles=("timestamp",),
            remediation_notes=(
                "Sort by timestamp during import; flag and reject "
                "duplicate or out-of-order rows.",
            ),
        ),
        SiteDataQualityRule(
            rule_id="duplicate_timestamps",
            check_kind="duplicate_timestamps",
            severity="blocking",
            description=(
                "Duplicate timestamps per pump break the time series and "
                "must be resolved before training."
            ),
            applies_to_roles=("timestamp",),
            remediation_notes=(
                "Confirm the historian export resolution and re-export.",
            ),
        ),
        SiteDataQualityRule(
            rule_id="sampling_interval_drift",
            check_kind="sampling_interval_drift",
            severity="warning",
            description=(
                "Sampling interval drift outside the configured tolerance "
                "is flagged as a quality warning."
            ),
            applies_to_roles=("timestamp",),
            remediation_notes=(
                "Pipeline resamples to a regular grid; large drift may "
                "degrade physics residual accuracy.",
            ),
        ),
        SiteDataQualityRule(
            rule_id="pressure_plausibility",
            check_kind="pressure_plausibility",
            severity="warning",
            description=(
                "Pressure values must be physically plausible (non-"
                "negative gauge; below sensor saturation) after unit "
                "normalisation."
            ),
            applies_to_roles=("discharge_pressure", "suction_pressure"),
            remediation_notes=(
                "Confirm sensor calibration and saturation range with the "
                "site operator.",
            ),
        ),
        SiteDataQualityRule(
            rule_id="flow_plausibility",
            check_kind="flow_plausibility",
            severity="warning",
            description=(
                "Flow values must be physically plausible (non-negative "
                "for unidirectional sites; within meter range)."
            ),
            applies_to_roles=("flow_rate",),
            remediation_notes=(
                "Confirm meter direction and full-scale range with the "
                "site operator.",
            ),
        ),
        SiteDataQualityRule(
            rule_id="pump_state_availability",
            check_kind="pump_state_availability",
            severity="blocking",
            description=(
                "At least one pump-state channel (pump_status or "
                "pump_running) must be present so on / off windows are "
                "well defined."
            ),
            applies_to_roles=("pump_status", "pump_running"),
            remediation_notes=(
                "Request a run/stop indicator if the SCADA export "
                "omitted it.",
            ),
        ),
        SiteDataQualityRule(
            rule_id="timezone_clarity",
            check_kind="timezone_clarity",
            severity="blocking",
            description=(
                "Timezone of every timestamp series must be clearly "
                "documented (UTC or IANA label)."
            ),
            applies_to_roles=("timestamp",),
            remediation_notes=(
                "Ask the customer to confirm the historian timezone "
                "policy.",
            ),
        ),
    )


# ---------------------------------------------------------------------------
# assess_site_data_readiness
# ---------------------------------------------------------------------------


def assess_site_data_readiness(
    available_fields: Sequence[str],
    *,
    schema: SiteDataExportSchema | None = None,
    units_declared: bool = False,
    timezone_declared: bool = False,
) -> SiteDataReadinessAssessment:
    """Grade a candidate dataset against the Sprint 53 site-data schema.

    Parameters
    ----------
    available_fields
        Canonical role tokens (from :data:`PUMP_SITE_CANONICAL_ROLES`)
        that the candidate dataset actually exports. Unknown tokens are
        ignored with a warning.
    schema
        The :class:`SiteDataExportSchema` to grade against. Defaults to
        :func:`default_pump_site_data_export_schema`.
    units_declared
        Whether the customer / site has declared units for the
        pressure and flow / tank-level channels.
    timezone_declared
        Whether the customer / site has declared a clear timezone for
        the timestamp series.

    Returns
    -------
    SiteDataReadinessAssessment
        Deterministic readiness assessment carrying the grade, gaps,
        warnings, recommendation, and safety notes.
    """

    if isinstance(available_fields, (str, bytes)):
        raise ContractError(
            "assess_site_data_readiness.available_fields must be a sequence of "
            "strings"
        )
    if schema is None:
        schema = default_pump_site_data_export_schema()
    if not isinstance(schema, SiteDataExportSchema):
        raise ContractError(
            "assess_site_data_readiness.schema must be a SiteDataExportSchema"
        )
    if not isinstance(units_declared, bool) or not isinstance(
        timezone_declared, bool
    ):
        raise ContractError(
            "assess_site_data_readiness.units_declared and timezone_declared "
            "must be bools"
        )

    available_normalised: list[str] = []
    unknown_tokens: list[str] = []
    seen: set[str] = set()
    for entry in available_fields:
        if not isinstance(entry, str):
            raise ContractError(
                "assess_site_data_readiness.available_fields must contain "
                f"strings, got {type(entry).__name__}"
            )
        if entry in seen:
            continue
        seen.add(entry)
        if entry in PUMP_SITE_CANONICAL_ROLES:
            available_normalised.append(entry)
        else:
            unknown_tokens.append(entry)

    available_set = set(available_normalised)
    required_ids = tuple(f.field_id for f in schema.required_fields)
    optional_ids = tuple(f.field_id for f in schema.optional_fields)

    pump_state_present = bool(
        set(PUMP_SITE_PUMP_STATE_ROLES) & available_set
    )
    pump_speed_present = bool(
        set(PUMP_SITE_PUMP_SPEED_ROLES) & available_set
    )
    hydraulic_present = sorted(
        role for role in PUMP_SITE_HYDRAULIC_ROLES if role in available_set
    )
    has_flow_or_tank = any(
        role in available_set for role in ("flow_rate", "tank_level")
    )
    has_pressure = any(
        role in available_set
        for role in ("discharge_pressure", "suction_pressure")
    )

    # Build deterministic field tuples.
    available_fields_out = tuple(sorted(available_set))
    optional_present = tuple(
        sorted(role for role in optional_ids if role in available_set)
    )

    # Treat pump_state as a soft-required: any of pump_status or pump_running
    # satisfies the requirement.
    missing_required: list[str] = []
    for role in required_ids:
        if role in available_set:
            continue
        if role == "pump_status" and "pump_running" in available_set:
            continue
        missing_required.append(role)
    missing_required.sort()

    blocking_gaps: list[str] = []
    warnings: list[str] = []

    if "timestamp" not in available_set:
        blocking_gaps.append("timestamp series is missing")
    if not pump_state_present:
        blocking_gaps.append(
            "pump state channel is missing (pump_status or pump_running)"
        )
    if not hydraulic_present:
        blocking_gaps.append(
            "all hydraulic channels are missing (no pressure, flow, or "
            "tank-level data)"
        )
    if not timezone_declared:
        warnings.append(
            "timezone policy not declared; timezone_clarity check will "
            "block import until resolved"
        )
    elif "timestamp" not in available_set:
        # Already flagged as blocking; no extra warning needed.
        pass
    if has_pressure and not units_declared:
        warnings.append(
            "pressure channel present but units not declared; "
            "unit_presence check will block import until resolved"
        )
    if has_flow_or_tank and not units_declared:
        warnings.append(
            "flow or tank-level channel present but units not declared; "
            "unit_presence check will block import until resolved"
        )
    if pump_state_present and not pump_speed_present:
        warnings.append(
            "no pump speed proxy exported (pump_speed_rpm / "
            "vfd_frequency_hz / speed_percent); VFD-driven pumps will be "
            "harder to model"
        )
    if (
        "flow_rate" not in available_set
        and "tank_level" in available_set
    ):
        warnings.append(
            "flow_rate missing; tank_level trend will be used as the "
            "hydraulic-output substitute"
        )
    if unknown_tokens:
        warnings.append(
            "ignored unknown field tokens: " + ",".join(sorted(unknown_tokens))
        )

    if blocking_gaps:
        grade = DPHM_READINESS_GRADE_BLOCKED
        recommendation = (
            "Dataset is blocked for dPHM testing. Resolve the blocking gaps "
            "before re-exporting; AquaOptima cannot test the model without "
            "timestamp, pump state, and at least one hydraulic channel."
        )
    else:
        # Score the dataset.
        good = (
            has_pressure
            and has_flow_or_tank
            and pump_state_present
            and pump_speed_present
            and units_declared
            and timezone_declared
            and "discharge_pressure" in available_set
            and "flow_rate" in available_set
        )
        usable = (
            has_pressure
            and has_flow_or_tank
            and pump_state_present
            and units_declared
            and timezone_declared
        )
        if good:
            grade = DPHM_READINESS_GRADE_GOOD
            recommendation = (
                "Dataset is sufficient for dPHM / dPL / dPHM-PINN replay "
                "testing without AMAX. Proceed with the read-only ingest "
                "pipeline."
            )
        elif usable:
            grade = DPHM_READINESS_GRADE_USABLE
            recommendation = (
                "Dataset is usable for limited dPHM replay and diagnostics. "
                "Capture the listed warnings as caveats before drawing "
                "model-quality conclusions."
            )
        else:
            grade = DPHM_READINESS_GRADE_POOR
            recommendation = (
                "Dataset can be inspected but is too sparse to confidently "
                "test dPHM. Request additional channels (flow / pressure "
                "with declared units) before model evaluation."
            )

    return SiteDataReadinessAssessment(
        schema_id=schema.schema_id,
        grade=grade,
        available_fields=available_fields_out,
        missing_required_fields=tuple(missing_required),
        optional_fields_present=optional_present,
        blocking_gaps=tuple(blocking_gaps),
        warnings=tuple(warnings),
        recommendation=recommendation,
        safety_notes=(
            "no live OT binding",
            "no PLC/PAC/SCADA write",
            "no command emission",
            "no setpoint output",
            "no control-loop closure",
            "Sprint 53 readiness assessment runs on an exported / uploaded "
            "dataset only; the site PLC retains direct VFD / pump / "
            "actuator authority.",
        ),
    )
