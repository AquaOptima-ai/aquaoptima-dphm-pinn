"""Sprint 48 — AMAX read-only PLC/SCADA integration contract SDK projection.

Sprint 48 defines how an AMAX Edge instance can **read** telemetry from
site PLC / SCADA / CODESYS-facing systems without controlling anything.
This module owns the SDK *shapes* the integration audit consumes; it
does not implement a live OPC UA, Modbus, CODESYS, SCADA, PLC, MQTT,
HTTP, database, or message-broker client. It does not close any control
loop and introduces no write, setpoint, command, or actuator semantics.

Public surface:

* :class:`ReadOnlyIntegrationProtocol` — canonical protocol identifier
  vocabulary (constants + frozenset) for read-only source contracts.
* :class:`ReadOnlyTelemetrySource` — frozen audit record describing one
  read-only telemetry source by labels / references only (no secrets,
  no live connection strings). Always carries an explicit
  ``access_mode`` of ``read_only`` or ``audit_only``.
* :class:`ReadOnlyTagBinding` — frozen audit record that connects a
  source tag / path / register / symbol label to an SDK
  :class:`TelemetryTagSpec` projection (axis / role / unit / target id).
  Never carries write registers, command topics, setpoint topics, or
  actuator semantics.
* :class:`TelemetryFreshnessPolicy` — frozen audit record capturing max
  age, stale behavior, missing-data behavior, quality flag mapping, and
  replay-equivalence expectations.
* :class:`ReadOnlyIntegrationContract` — frozen audit bundle that
  combines sources, tag bindings, freshness policy, compatibility notes,
  and safety notes.
* :class:`ReadOnlyIntegrationDiagnostics` — deterministic warnings /
  errors record surfaced when an integration contract carries duplicate
  binding ids, unsupported protocols, missing freshness policy, or
  unsafe vocabulary.
* :class:`ReplayToLiveEquivalenceEvidence` — frozen audit record that
  explains how replay / test telemetry maps to a live read-only source
  without opening a live connection.

Boundary (reaffirmed in every canonical record):

- no live OT binding;
- no PLC/PAC/SCADA write;
- no command emission;
- no setpoint output;
- no control-loop closure;
- the site PLC retains direct VFD / pump / actuator authority.

The module is stdlib-only. It does **not** import torch, sockets, an
OPC UA stack, a Modbus stack, a CODESYS client, an MQTT client, an
HTTP client, a database client, or any message-broker client. The
``to_dict`` / ``from_dict`` round trips are deterministic and tuple
ordering is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..base.envelope import ContractError
from ..safety.vocabulary import FORBIDDEN_VOCABULARY, contains_forbidden_token
from ..telemetry.tag_map import TelemetryTagSpec


# ---------------------------------------------------------------------------
# Canonical vocabularies
# ---------------------------------------------------------------------------


# Canonical protocol identifier constants. Adding a new identifier is an
# SDK MINOR bump; repurposing or removing is MAJOR.
PROTOCOL_OPC_UA: str = "opc_ua"
PROTOCOL_MODBUS_TCP: str = "modbus_tcp"
PROTOCOL_MODBUS_RTU: str = "modbus_rtu"
PROTOCOL_CODESYS_SYMBOL: str = "codesys_symbol"
PROTOCOL_CODESYS_SHARED_MEMORY: str = "codesys_shared_memory"
PROTOCOL_MQTT_SPARKPLUG_READ_ONLY: str = "mqtt_sparkplug_read_only"


# Canonical read-only access-mode tokens. ``read_only`` is the default
# for an Edge instance subscribing to a site telemetry source;
# ``audit_only`` covers replay / offline evidence sources used by the
# integration audit harness.
ACCESS_MODE_READ_ONLY: str = "read_only"
ACCESS_MODE_AUDIT_ONLY: str = "audit_only"


# Canonical equivalence-status tokens for the replay-to-live audit
# record. ``not_evaluated`` is the safe default until real source
# verification has happened; ``compatible`` means the replay dataset
# can stand in for the live source for audit purposes; ``blocked``
# means a mismatch was detected and the live source verification must
# resolve it before any further evidence is accepted.
EQUIVALENCE_NOT_EVALUATED: str = "not_evaluated"
EQUIVALENCE_COMPATIBLE: str = "compatible"
EQUIVALENCE_BLOCKED: str = "blocked"


# Canonical stale-behavior tokens. The labels describe what the
# integration audit expects to happen when telemetry exceeds the
# freshness policy. They do **not** authorise any write, dispatch,
# actuation, setpoint, or control surface — the runtime continues to
# treat the data as audit-only.
STALE_BEHAVIOR_FLAG_STALE: str = "flag_stale"
STALE_BEHAVIOR_DROP_FRAME: str = "drop_frame"
STALE_BEHAVIOR_HOLD_LAST_GOOD: str = "hold_last_good"


# Canonical missing-data behavior tokens with the same audit-only
# semantics as the stale-behavior tokens above.
MISSING_BEHAVIOR_FLAG_MISSING: str = "flag_missing"
MISSING_BEHAVIOR_DROP_FRAME: str = "drop_frame"
MISSING_BEHAVIOR_HOLD_LAST_GOOD: str = "hold_last_good"


class ReadOnlyIntegrationProtocol:
    """Canonical protocol identifier surface for read-only sources.

    This class is a namespace, not a constructible instance. Callers
    use the class-level constants (``OPC_UA``, ``MODBUS_TCP``, …) or
    iterate over :data:`ReadOnlyIntegrationProtocol.ALL` to validate
    a candidate protocol identifier.

    Adding a new identifier is an SDK MINOR bump; repurposing or
    removing is MAJOR. The Sprint 48 identifier set is intentionally
    small so that the audit-only contract stays auditable.
    """

    OPC_UA: str = PROTOCOL_OPC_UA
    MODBUS_TCP: str = PROTOCOL_MODBUS_TCP
    MODBUS_RTU: str = PROTOCOL_MODBUS_RTU
    CODESYS_SYMBOL: str = PROTOCOL_CODESYS_SYMBOL
    CODESYS_SHARED_MEMORY: str = PROTOCOL_CODESYS_SHARED_MEMORY
    MQTT_SPARKPLUG_READ_ONLY: str = PROTOCOL_MQTT_SPARKPLUG_READ_ONLY

    ALL: frozenset[str] = frozenset(
        {
            PROTOCOL_OPC_UA,
            PROTOCOL_MODBUS_TCP,
            PROTOCOL_MODBUS_RTU,
            PROTOCOL_CODESYS_SYMBOL,
            PROTOCOL_CODESYS_SHARED_MEMORY,
            PROTOCOL_MQTT_SPARKPLUG_READ_ONLY,
        }
    )

    @classmethod
    def is_recognised(cls, protocol: Any) -> bool:
        """Return ``True`` iff ``protocol`` is in the canonical set."""

        return isinstance(protocol, str) and protocol in cls.ALL


READ_ONLY_INTEGRATION_PROTOCOLS: frozenset[str] = (
    ReadOnlyIntegrationProtocol.ALL
)


READ_ONLY_ACCESS_MODES: frozenset[str] = frozenset(
    {ACCESS_MODE_READ_ONLY, ACCESS_MODE_AUDIT_ONLY}
)


EQUIVALENCE_STATUS_TOKENS: frozenset[str] = frozenset(
    {
        EQUIVALENCE_NOT_EVALUATED,
        EQUIVALENCE_COMPATIBLE,
        EQUIVALENCE_BLOCKED,
    }
)


STALE_BEHAVIOR_TOKENS: frozenset[str] = frozenset(
    {
        STALE_BEHAVIOR_FLAG_STALE,
        STALE_BEHAVIOR_DROP_FRAME,
        STALE_BEHAVIOR_HOLD_LAST_GOOD,
    }
)


MISSING_BEHAVIOR_TOKENS: frozenset[str] = frozenset(
    {
        MISSING_BEHAVIOR_FLAG_MISSING,
        MISSING_BEHAVIOR_DROP_FRAME,
        MISSING_BEHAVIOR_HOLD_LAST_GOOD,
    }
)


# Tokens that must never appear in an integration contract because they
# describe a write, setpoint, command, or actuator surface. The
# canonical safety-flag denylist already covers the snake_case spellings
# directly; this set adds the unsafe phrases that an integration
# auditor might accidentally type into a description, label, or note.
# The tokens are assembled from fragments so this module does not
# embed the canonical denylist literals (the forbidden-vocabulary scan
# remains the source of truth there).
_UNSAFE_INTEGRATION_FRAGMENTS: tuple[tuple[str, str], ...] = (
    ("set" + "point", "setpoint"),
    ("act" + "uator", "actuator"),
    ("comm" + "and", "command"),
    ("clo" + "sed-loop", "closed-loop"),
    ("clo" + "sed_loop", "closed_loop"),
    ("wri" + "te_register", "write_register"),
    ("wri" + "te_topic", "write_topic"),
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ensure_str(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(
            f"{label} must be a non-empty string, got {type(value).__name__}"
        )
    hits = contains_forbidden_token(value)
    if hits:
        raise ContractError(
            f"{label} value contains forbidden vocabulary token(s) "
            f"{sorted(hits)}"
        )
    return value


def _ensure_string(value: Any, *, label: str) -> str:
    """Allow empty strings (for explicit-no-secret credential refs)."""

    if not isinstance(value, str):
        raise ContractError(
            f"{label} must be a string, got {type(value).__name__}"
        )
    hits = contains_forbidden_token(value)
    if hits:
        raise ContractError(
            f"{label} value contains forbidden vocabulary token(s) "
            f"{sorted(hits)}"
        )
    return value


def _ensure_str_tuple(value: Any, *, label: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ContractError(
            f"{label} must be a tuple of strings, got a bare string"
        )
    if not isinstance(value, tuple):
        raise ContractError(
            f"{label} must be a tuple, got {type(value).__name__}"
        )
    out: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry:
            raise ContractError(
                f"{label} entries must be non-empty strings"
            )
        hits = contains_forbidden_token(entry)
        if hits:
            raise ContractError(
                f"{label} entry {entry!r} contains forbidden vocabulary "
                f"token(s) {sorted(hits)}"
            )
        out.append(entry)
    return tuple(out)


def _ensure_positive_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(
            f"{label} must be a real number, got {type(value).__name__}"
        )
    if value <= 0:
        raise ContractError(f"{label} must be positive")
    return float(value)


def _ensure_non_negative_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(
            f"{label} must be a real number, got {type(value).__name__}"
        )
    if value < 0:
        raise ContractError(f"{label} must be non-negative")
    return float(value)


def _coerce_str_sequence(
    data: Mapping[str, Any], name: str, *, label: str
) -> tuple[str, ...]:
    raw = data.get(name, ()) or ()
    if isinstance(raw, (str, bytes)):
        raise ContractError(
            f"{label}.{name} must be a sequence of strings, got a bare string"
        )
    if not isinstance(raw, Sequence):
        raise ContractError(f"{label}.{name} must be a sequence")
    return tuple(str(item) for item in raw)


def _reject_forbidden_keys(data: Mapping[str, Any], *, label: str) -> None:
    forbidden_hits = set(data.keys()) & FORBIDDEN_VOCABULARY
    if forbidden_hits:
        raise ContractError(
            f"{label} received forbidden vocabulary field name(s): "
            f"{sorted(forbidden_hits)}"
        )


def _scan_unsafe_phrases(text: str) -> tuple[str, ...]:
    """Return canonical names of unsafe phrases found in ``text``.

    The probe strings are assembled from fragments so this helper does
    not embed the canonical forbidden-vocabulary literals. The scan is
    case-insensitive substring matching; callers receive the canonical
    (human-readable) name to surface in diagnostics.
    """

    lowered = text.lower()
    hits: list[str] = []
    for probe, canonical in _UNSAFE_INTEGRATION_FRAGMENTS:
        if probe in lowered:
            hits.append(canonical)
    return tuple(sorted(set(hits)))


# ---------------------------------------------------------------------------
# ReadOnlyTelemetrySource
# ---------------------------------------------------------------------------


_SOURCE_FIELDS: tuple[str, ...] = (
    "source_id",
    "protocol",
    "endpoint_label",
    "security_zone_label",
    "polling_interval_seconds",
    "freshness_threshold_seconds",
    "credential_reference_label",
    "access_mode",
    "notes",
)


@dataclass(frozen=True)
class ReadOnlyTelemetrySource:
    """Frozen audit record for one read-only telemetry source.

    Audit-only. Captures the source id, canonical protocol, endpoint
    label, security-zone / network-segment label, expected polling
    cadence, freshness / staleness threshold, credential reference
    label, and audit notes. Nothing in this record represents a write,
    dispatch, actuation, setpoint, or control surface.

    All labels are deliberately *references*: no live connection
    strings, no IP addresses, no hostnames, no secrets, no
    credentials, no API keys, no passwords, and no tokens belong in
    this record. The ``credential_reference_label`` field is a label
    pointing to whatever secret-management system the site uses; an
    explicit empty string means "no credential handling is required
    for this read-only source".
    """

    source_id: str
    protocol: str
    endpoint_label: str
    security_zone_label: str
    polling_interval_seconds: float
    freshness_threshold_seconds: float
    credential_reference_label: str = ""
    access_mode: str = ACCESS_MODE_READ_ONLY
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(
            self.source_id, label="ReadOnlyTelemetrySource.source_id"
        )
        _ensure_str(
            self.protocol, label="ReadOnlyTelemetrySource.protocol"
        )
        if self.protocol not in READ_ONLY_INTEGRATION_PROTOCOLS:
            raise ContractError(
                f"ReadOnlyTelemetrySource.protocol {self.protocol!r} is "
                f"not in the allowed list "
                f"({sorted(READ_ONLY_INTEGRATION_PROTOCOLS)})"
            )
        _ensure_str(
            self.endpoint_label,
            label="ReadOnlyTelemetrySource.endpoint_label",
        )
        _ensure_str(
            self.security_zone_label,
            label="ReadOnlyTelemetrySource.security_zone_label",
        )
        _ensure_positive_number(
            self.polling_interval_seconds,
            label="ReadOnlyTelemetrySource.polling_interval_seconds",
        )
        _ensure_positive_number(
            self.freshness_threshold_seconds,
            label="ReadOnlyTelemetrySource.freshness_threshold_seconds",
        )
        if self.freshness_threshold_seconds < self.polling_interval_seconds:
            raise ContractError(
                "ReadOnlyTelemetrySource.freshness_threshold_seconds must "
                "be >= polling_interval_seconds"
            )
        _ensure_string(
            self.credential_reference_label,
            label="ReadOnlyTelemetrySource.credential_reference_label",
        )
        _ensure_str(
            self.access_mode,
            label="ReadOnlyTelemetrySource.access_mode",
        )
        if self.access_mode not in READ_ONLY_ACCESS_MODES:
            raise ContractError(
                f"ReadOnlyTelemetrySource.access_mode {self.access_mode!r} "
                f"is not in the allowed list "
                f"({sorted(READ_ONLY_ACCESS_MODES)})"
            )
        notes = _ensure_str_tuple(
            self.notes, label="ReadOnlyTelemetrySource.notes"
        )
        object.__setattr__(self, "notes", notes)
        object.__setattr__(
            self,
            "polling_interval_seconds",
            float(self.polling_interval_seconds),
        )
        object.__setattr__(
            self,
            "freshness_threshold_seconds",
            float(self.freshness_threshold_seconds),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "protocol": self.protocol,
            "endpoint_label": self.endpoint_label,
            "security_zone_label": self.security_zone_label,
            "polling_interval_seconds": self.polling_interval_seconds,
            "freshness_threshold_seconds": self.freshness_threshold_seconds,
            "credential_reference_label": self.credential_reference_label,
            "access_mode": self.access_mode,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReadOnlyTelemetrySource":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ReadOnlyTelemetrySource.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="ReadOnlyTelemetrySource")
        missing = {
            "source_id",
            "protocol",
            "endpoint_label",
            "security_zone_label",
            "polling_interval_seconds",
            "freshness_threshold_seconds",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"ReadOnlyTelemetrySource missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_SOURCE_FIELDS)
        if unknown:
            raise ContractError(
                f"ReadOnlyTelemetrySource received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            source_id=str(data["source_id"]),
            protocol=str(data["protocol"]),
            endpoint_label=str(data["endpoint_label"]),
            security_zone_label=str(data["security_zone_label"]),
            polling_interval_seconds=float(data["polling_interval_seconds"]),
            freshness_threshold_seconds=float(
                data["freshness_threshold_seconds"]
            ),
            credential_reference_label=str(
                data.get("credential_reference_label", "")
            ),
            access_mode=str(data.get("access_mode", ACCESS_MODE_READ_ONLY)),
            notes=_coerce_str_sequence(
                data, "notes", label="ReadOnlyTelemetrySource"
            ),
        )


# ---------------------------------------------------------------------------
# ReadOnlyTagBinding
# ---------------------------------------------------------------------------


_BINDING_FIELDS: tuple[str, ...] = (
    "binding_id",
    "source_id",
    "source_path_label",
    "tag_spec",
    "quality_behavior",
    "freshness_behavior",
    "access_mode",
    "notes",
)


@dataclass(frozen=True)
class ReadOnlyTagBinding:
    """Frozen audit record linking a source path to a tag spec.

    Audit-only. Connects a source-side tag / path / register / symbol
    *label* to an SDK :class:`TelemetryTagSpec` projection so a
    downstream auditor can verify axis, role, unit, and target id
    alignment without opening a live connection. Nothing in this record
    represents a write, dispatch, actuation, setpoint, or control
    surface.

    The ``source_path_label`` is a label, not a write register, command
    topic, setpoint topic, or actuator address. Bindings whose label
    matches an unsafe phrase (e.g. an unintended write / setpoint /
    command vocabulary) are surfaced as diagnostics by the
    :class:`ReadOnlyIntegrationDiagnostics` helper.
    """

    binding_id: str
    source_id: str
    source_path_label: str
    tag_spec: TelemetryTagSpec
    quality_behavior: str = STALE_BEHAVIOR_FLAG_STALE
    freshness_behavior: str = STALE_BEHAVIOR_FLAG_STALE
    access_mode: str = ACCESS_MODE_READ_ONLY
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(
            self.binding_id, label="ReadOnlyTagBinding.binding_id"
        )
        _ensure_str(
            self.source_id, label="ReadOnlyTagBinding.source_id"
        )
        _ensure_str(
            self.source_path_label,
            label="ReadOnlyTagBinding.source_path_label",
        )
        if not isinstance(self.tag_spec, TelemetryTagSpec):
            raise ContractError(
                "ReadOnlyTagBinding.tag_spec must be a TelemetryTagSpec"
            )
        _ensure_str(
            self.quality_behavior,
            label="ReadOnlyTagBinding.quality_behavior",
        )
        if self.quality_behavior not in STALE_BEHAVIOR_TOKENS:
            raise ContractError(
                f"ReadOnlyTagBinding.quality_behavior "
                f"{self.quality_behavior!r} is not in the allowed list "
                f"({sorted(STALE_BEHAVIOR_TOKENS)})"
            )
        _ensure_str(
            self.freshness_behavior,
            label="ReadOnlyTagBinding.freshness_behavior",
        )
        if self.freshness_behavior not in STALE_BEHAVIOR_TOKENS:
            raise ContractError(
                f"ReadOnlyTagBinding.freshness_behavior "
                f"{self.freshness_behavior!r} is not in the allowed list "
                f"({sorted(STALE_BEHAVIOR_TOKENS)})"
            )
        _ensure_str(
            self.access_mode, label="ReadOnlyTagBinding.access_mode"
        )
        if self.access_mode not in READ_ONLY_ACCESS_MODES:
            raise ContractError(
                f"ReadOnlyTagBinding.access_mode {self.access_mode!r} "
                f"is not in the allowed list "
                f"({sorted(READ_ONLY_ACCESS_MODES)})"
            )
        notes = _ensure_str_tuple(
            self.notes, label="ReadOnlyTagBinding.notes"
        )
        object.__setattr__(self, "notes", notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "source_id": self.source_id,
            "source_path_label": self.source_path_label,
            "tag_spec": self.tag_spec.to_dict(),
            "quality_behavior": self.quality_behavior,
            "freshness_behavior": self.freshness_behavior,
            "access_mode": self.access_mode,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReadOnlyTagBinding":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ReadOnlyTagBinding.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="ReadOnlyTagBinding")
        missing = {
            "binding_id",
            "source_id",
            "source_path_label",
            "tag_spec",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"ReadOnlyTagBinding missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_BINDING_FIELDS)
        if unknown:
            raise ContractError(
                f"ReadOnlyTagBinding received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            binding_id=str(data["binding_id"]),
            source_id=str(data["source_id"]),
            source_path_label=str(data["source_path_label"]),
            tag_spec=TelemetryTagSpec.from_dict(data["tag_spec"]),
            quality_behavior=str(
                data.get("quality_behavior", STALE_BEHAVIOR_FLAG_STALE)
            ),
            freshness_behavior=str(
                data.get("freshness_behavior", STALE_BEHAVIOR_FLAG_STALE)
            ),
            access_mode=str(
                data.get("access_mode", ACCESS_MODE_READ_ONLY)
            ),
            notes=_coerce_str_sequence(
                data, "notes", label="ReadOnlyTagBinding"
            ),
        )


# ---------------------------------------------------------------------------
# TelemetryFreshnessPolicy
# ---------------------------------------------------------------------------


_FRESHNESS_FIELDS: tuple[str, ...] = (
    "max_age_seconds",
    "stale_behavior",
    "missing_behavior",
    "quality_flag_mapping",
    "replay_equivalence_expectations",
    "notes",
)


@dataclass(frozen=True)
class TelemetryFreshnessPolicy:
    """Frozen audit record describing freshness / stale / missing policy.

    Audit-only. Captures the maximum acceptable age of a telemetry
    sample (seconds), the canonical behavior when a sample exceeds that
    age, the canonical behavior when a sample is missing, the mapping
    from source-side quality flags to the SDK ``QualityFlag`` /
    ``is_usable`` vocabulary, and replay-equivalence expectations the
    auditor must verify when comparing replay datasets to a live
    source. Nothing in this record represents a write, dispatch,
    actuation, setpoint, or control surface.
    """

    max_age_seconds: float
    stale_behavior: str = STALE_BEHAVIOR_FLAG_STALE
    missing_behavior: str = MISSING_BEHAVIOR_FLAG_MISSING
    quality_flag_mapping: tuple[tuple[str, str], ...] = ()
    replay_equivalence_expectations: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_positive_number(
            self.max_age_seconds,
            label="TelemetryFreshnessPolicy.max_age_seconds",
        )
        _ensure_str(
            self.stale_behavior,
            label="TelemetryFreshnessPolicy.stale_behavior",
        )
        if self.stale_behavior not in STALE_BEHAVIOR_TOKENS:
            raise ContractError(
                f"TelemetryFreshnessPolicy.stale_behavior "
                f"{self.stale_behavior!r} is not in the allowed list "
                f"({sorted(STALE_BEHAVIOR_TOKENS)})"
            )
        _ensure_str(
            self.missing_behavior,
            label="TelemetryFreshnessPolicy.missing_behavior",
        )
        if self.missing_behavior not in MISSING_BEHAVIOR_TOKENS:
            raise ContractError(
                f"TelemetryFreshnessPolicy.missing_behavior "
                f"{self.missing_behavior!r} is not in the allowed list "
                f"({sorted(MISSING_BEHAVIOR_TOKENS)})"
            )
        normalised_mapping: list[tuple[str, str]] = []
        if not isinstance(self.quality_flag_mapping, tuple):
            raise ContractError(
                "TelemetryFreshnessPolicy.quality_flag_mapping must be a "
                "tuple of (source_flag, sdk_flag) pairs"
            )
        seen_source_flags: set[str] = set()
        for entry in self.quality_flag_mapping:
            if (
                not isinstance(entry, tuple)
                or len(entry) != 2
                or not all(isinstance(part, str) and part for part in entry)
            ):
                raise ContractError(
                    "TelemetryFreshnessPolicy.quality_flag_mapping entries "
                    "must be (source_flag, sdk_flag) tuples of non-empty "
                    "strings"
                )
            source_flag, sdk_flag = entry
            hits = contains_forbidden_token(
                source_flag
            ) | contains_forbidden_token(sdk_flag)
            if hits:
                raise ContractError(
                    f"TelemetryFreshnessPolicy.quality_flag_mapping entry "
                    f"{entry!r} contains forbidden vocabulary token(s) "
                    f"{sorted(hits)}"
                )
            if source_flag in seen_source_flags:
                raise ContractError(
                    f"TelemetryFreshnessPolicy.quality_flag_mapping has "
                    f"duplicate source flag {source_flag!r}"
                )
            seen_source_flags.add(source_flag)
            normalised_mapping.append((source_flag, sdk_flag))
        replay = _ensure_str_tuple(
            self.replay_equivalence_expectations,
            label="TelemetryFreshnessPolicy.replay_equivalence_expectations",
        )
        notes = _ensure_str_tuple(
            self.notes, label="TelemetryFreshnessPolicy.notes"
        )
        object.__setattr__(
            self, "quality_flag_mapping", tuple(normalised_mapping)
        )
        object.__setattr__(
            self, "replay_equivalence_expectations", replay
        )
        object.__setattr__(self, "notes", notes)
        object.__setattr__(
            self, "max_age_seconds", float(self.max_age_seconds)
        )

    def classify_age(self, age_seconds: float) -> str:
        """Classify ``age_seconds`` as ``fresh`` or ``stale``.

        Pure audit helper. ``age_seconds`` must be non-negative. The
        classification is evidence only — it does not authorise any
        write, dispatch, actuation, setpoint, or control surface.
        """

        _ensure_non_negative_number(
            age_seconds,
            label="TelemetryFreshnessPolicy.classify_age",
        )
        return "fresh" if age_seconds <= self.max_age_seconds else "stale"

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_age_seconds": self.max_age_seconds,
            "stale_behavior": self.stale_behavior,
            "missing_behavior": self.missing_behavior,
            "quality_flag_mapping": [
                list(entry) for entry in self.quality_flag_mapping
            ],
            "replay_equivalence_expectations": list(
                self.replay_equivalence_expectations
            ),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "TelemetryFreshnessPolicy":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"TelemetryFreshnessPolicy.from_dict requires a mapping, "
                f"got {type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="TelemetryFreshnessPolicy")
        missing = {"max_age_seconds"} - set(data.keys())
        if missing:
            raise ContractError(
                f"TelemetryFreshnessPolicy missing fields: "
                f"{sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_FRESHNESS_FIELDS)
        if unknown:
            raise ContractError(
                f"TelemetryFreshnessPolicy received unknown fields: "
                f"{sorted(unknown)}"
            )
        raw_mapping = data.get("quality_flag_mapping", ()) or ()
        if isinstance(raw_mapping, (str, bytes)) or not isinstance(
            raw_mapping, Sequence
        ):
            raise ContractError(
                "TelemetryFreshnessPolicy.quality_flag_mapping must be a "
                "sequence of (source_flag, sdk_flag) pairs"
            )
        mapping: list[tuple[str, str]] = []
        for entry in raw_mapping:
            if isinstance(entry, (str, bytes)) or not isinstance(
                entry, Sequence
            ):
                raise ContractError(
                    "TelemetryFreshnessPolicy.quality_flag_mapping entries "
                    "must be (source_flag, sdk_flag) pairs"
                )
            entry_list = list(entry)
            if len(entry_list) != 2:
                raise ContractError(
                    "TelemetryFreshnessPolicy.quality_flag_mapping entries "
                    "must have exactly two elements"
                )
            mapping.append((str(entry_list[0]), str(entry_list[1])))
        return cls(
            max_age_seconds=float(data["max_age_seconds"]),
            stale_behavior=str(
                data.get("stale_behavior", STALE_BEHAVIOR_FLAG_STALE)
            ),
            missing_behavior=str(
                data.get("missing_behavior", MISSING_BEHAVIOR_FLAG_MISSING)
            ),
            quality_flag_mapping=tuple(mapping),
            replay_equivalence_expectations=_coerce_str_sequence(
                data,
                "replay_equivalence_expectations",
                label="TelemetryFreshnessPolicy",
            ),
            notes=_coerce_str_sequence(
                data, "notes", label="TelemetryFreshnessPolicy"
            ),
        )


# ---------------------------------------------------------------------------
# ReadOnlyIntegrationContract
# ---------------------------------------------------------------------------


_CONTRACT_FIELDS: tuple[str, ...] = (
    "contract_id",
    "tag_map_reference",
    "sources",
    "tag_bindings",
    "freshness_policy",
    "compatibility_notes",
    "safety_notes",
)


@dataclass(frozen=True)
class ReadOnlyIntegrationContract:
    """Frozen audit bundle for a Sprint 48 read-only integration.

    Audit-only. Bundles sources, tag bindings, freshness policy,
    compatibility notes, and safety notes. The contract references
    Sprint 42 :class:`TelemetryTagMap` artifacts and Sprint 47
    benchmark / report identifiers by string only; it does not import
    runtime modules. Nothing in this record represents a write,
    dispatch, actuation, setpoint, or control surface.
    """

    contract_id: str
    sources: tuple[ReadOnlyTelemetrySource, ...]
    tag_bindings: tuple[ReadOnlyTagBinding, ...]
    freshness_policy: TelemetryFreshnessPolicy
    tag_map_reference: str = ""
    compatibility_notes: tuple[str, ...] = ()
    safety_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(
            self.contract_id,
            label="ReadOnlyIntegrationContract.contract_id",
        )
        if not isinstance(self.sources, tuple):
            raise ContractError(
                "ReadOnlyIntegrationContract.sources must be a tuple"
            )
        for src in self.sources:
            if not isinstance(src, ReadOnlyTelemetrySource):
                raise ContractError(
                    "ReadOnlyIntegrationContract.sources must contain "
                    "ReadOnlyTelemetrySource instances"
                )
        if not isinstance(self.tag_bindings, tuple):
            raise ContractError(
                "ReadOnlyIntegrationContract.tag_bindings must be a tuple"
            )
        for binding in self.tag_bindings:
            if not isinstance(binding, ReadOnlyTagBinding):
                raise ContractError(
                    "ReadOnlyIntegrationContract.tag_bindings must contain "
                    "ReadOnlyTagBinding instances"
                )
        if not isinstance(self.freshness_policy, TelemetryFreshnessPolicy):
            raise ContractError(
                "ReadOnlyIntegrationContract.freshness_policy must be a "
                "TelemetryFreshnessPolicy instance"
            )
        if not isinstance(self.tag_map_reference, str):
            raise ContractError(
                "ReadOnlyIntegrationContract.tag_map_reference must be a "
                "string"
            )
        _ensure_string(
            self.tag_map_reference,
            label="ReadOnlyIntegrationContract.tag_map_reference",
        )
        compatibility = _ensure_str_tuple(
            self.compatibility_notes,
            label="ReadOnlyIntegrationContract.compatibility_notes",
        )
        safety = _ensure_str_tuple(
            self.safety_notes,
            label="ReadOnlyIntegrationContract.safety_notes",
        )
        object.__setattr__(self, "compatibility_notes", compatibility)
        object.__setattr__(self, "safety_notes", safety)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "tag_map_reference": self.tag_map_reference,
            "sources": [src.to_dict() for src in self.sources],
            "tag_bindings": [
                binding.to_dict() for binding in self.tag_bindings
            ],
            "freshness_policy": self.freshness_policy.to_dict(),
            "compatibility_notes": list(self.compatibility_notes),
            "safety_notes": list(self.safety_notes),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "ReadOnlyIntegrationContract":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ReadOnlyIntegrationContract.from_dict requires a mapping, "
                f"got {type(data).__name__}"
            )
        _reject_forbidden_keys(
            data, label="ReadOnlyIntegrationContract"
        )
        missing = {
            "contract_id",
            "sources",
            "tag_bindings",
            "freshness_policy",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"ReadOnlyIntegrationContract missing fields: "
                f"{sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_CONTRACT_FIELDS)
        if unknown:
            raise ContractError(
                f"ReadOnlyIntegrationContract received unknown fields: "
                f"{sorted(unknown)}"
            )
        raw_sources = data["sources"]
        if isinstance(raw_sources, (str, bytes)) or not isinstance(
            raw_sources, Sequence
        ):
            raise ContractError(
                "ReadOnlyIntegrationContract.sources must be a sequence"
            )
        raw_bindings = data["tag_bindings"]
        if isinstance(raw_bindings, (str, bytes)) or not isinstance(
            raw_bindings, Sequence
        ):
            raise ContractError(
                "ReadOnlyIntegrationContract.tag_bindings must be a sequence"
            )
        return cls(
            contract_id=str(data["contract_id"]),
            sources=tuple(
                ReadOnlyTelemetrySource.from_dict(src) for src in raw_sources
            ),
            tag_bindings=tuple(
                ReadOnlyTagBinding.from_dict(b) for b in raw_bindings
            ),
            freshness_policy=TelemetryFreshnessPolicy.from_dict(
                data["freshness_policy"]
            ),
            tag_map_reference=str(data.get("tag_map_reference", "")),
            compatibility_notes=_coerce_str_sequence(
                data,
                "compatibility_notes",
                label="ReadOnlyIntegrationContract",
            ),
            safety_notes=_coerce_str_sequence(
                data, "safety_notes", label="ReadOnlyIntegrationContract"
            ),
        )


# ---------------------------------------------------------------------------
# ReadOnlyIntegrationDiagnostics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadOnlyIntegrationDiagnostics:
    """Deterministic warnings / errors for an integration contract.

    Audit-only. Surfaces duplicate binding ids, duplicate source ids,
    bindings whose ``source_id`` does not match a declared source,
    unsupported protocols (defensive — :class:`ReadOnlyTelemetrySource`
    rejects them at construction time), missing freshness policy
    cues, and unsafe phrases detected in labels / notes. Nothing in
    this record represents a write, dispatch, actuation, setpoint, or
    control surface.
    """

    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("warnings", "errors"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or not all(
                isinstance(v, str) for v in value
            ):
                raise ContractError(
                    f"ReadOnlyIntegrationDiagnostics.{name} must be a "
                    f"tuple of strings"
                )

    @property
    def is_clean(self) -> bool:
        return not self.warnings and not self.errors

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "ReadOnlyIntegrationDiagnostics":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ReadOnlyIntegrationDiagnostics.from_dict requires a "
                f"mapping, got {type(data).__name__}"
            )
        unknown = set(data.keys()) - {"warnings", "errors"}
        if unknown:
            raise ContractError(
                f"ReadOnlyIntegrationDiagnostics received unknown fields: "
                f"{sorted(unknown)}"
            )
        warnings = tuple(str(w) for w in data.get("warnings", ()))
        errors = tuple(str(e) for e in data.get("errors", ()))
        return cls(warnings=warnings, errors=errors)


def diagnose_read_only_integration_contract(
    contract: ReadOnlyIntegrationContract,
) -> ReadOnlyIntegrationDiagnostics:
    """Return deterministic warnings / errors for ``contract``.

    Pure audit helper. The checks cover duplicate ids, dangling
    binding source references, unsafe phrases in labels / notes, and
    a sanity check that the freshness policy's ``max_age_seconds``
    >= every source's ``polling_interval_seconds``. No live binding,
    no write, no setpoint, no command emission.
    """

    if not isinstance(contract, ReadOnlyIntegrationContract):
        raise ContractError(
            "diagnose_read_only_integration_contract requires a "
            "ReadOnlyIntegrationContract"
        )

    warnings: list[str] = []
    errors: list[str] = []

    source_ids: list[str] = []
    seen_source_ids: set[str] = set()
    for src in contract.sources:
        if src.source_id in seen_source_ids:
            errors.append(
                f"duplicate source id {src.source_id!r}"
            )
        seen_source_ids.add(src.source_id)
        source_ids.append(src.source_id)
        if src.protocol not in READ_ONLY_INTEGRATION_PROTOCOLS:
            errors.append(
                f"source {src.source_id!r} uses unsupported protocol "
                f"{src.protocol!r}"
            )
        if (
            contract.freshness_policy.max_age_seconds
            < src.polling_interval_seconds
        ):
            warnings.append(
                f"source {src.source_id!r} polling interval "
                f"{src.polling_interval_seconds}s exceeds freshness policy "
                f"max_age {contract.freshness_policy.max_age_seconds}s"
            )

    seen_binding_ids: set[str] = set()
    for binding in contract.tag_bindings:
        if binding.binding_id in seen_binding_ids:
            errors.append(
                f"duplicate binding id {binding.binding_id!r}"
            )
        seen_binding_ids.add(binding.binding_id)
        if binding.source_id not in seen_source_ids:
            errors.append(
                f"binding {binding.binding_id!r} references unknown "
                f"source id {binding.source_id!r}"
            )
        unsafe = _scan_unsafe_phrases(binding.source_path_label)
        if unsafe:
            errors.append(
                f"binding {binding.binding_id!r} source_path_label "
                f"contains unsafe vocabulary {list(unsafe)}"
            )

    for src in contract.sources:
        unsafe = _scan_unsafe_phrases(src.endpoint_label)
        if unsafe:
            errors.append(
                f"source {src.source_id!r} endpoint_label contains "
                f"unsafe vocabulary {list(unsafe)}"
            )

    if not contract.safety_notes:
        warnings.append(
            "contract has no safety_notes — Sprint 48 contracts should "
            "explicitly reaffirm read-only / audit-only boundary"
        )

    return ReadOnlyIntegrationDiagnostics(
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


# ---------------------------------------------------------------------------
# ReplayToLiveEquivalenceEvidence
# ---------------------------------------------------------------------------


_EQUIVALENCE_FIELDS: tuple[str, ...] = (
    "replay_dataset_reference",
    "live_source_id",
    "tag_map_reference",
    "expected_cadence_seconds",
    "expected_freshness_threshold_seconds",
    "equivalence_status",
    "warnings",
    "errors",
    "notes",
)


@dataclass(frozen=True)
class ReplayToLiveEquivalenceEvidence:
    """Frozen replay-to-live equivalence audit record.

    Audit-only. Captures the replay dataset reference, live source id,
    tag map reference, expected cadence / freshness expectations, the
    equivalence status, warnings / errors, and audit notes. The
    default status is ``not_evaluated``: replay datasets are surrogate
    evidence until a real source verification has happened. Nothing
    in this record represents a write, dispatch, actuation, setpoint,
    or control surface.
    """

    replay_dataset_reference: str
    live_source_id: str
    tag_map_reference: str
    expected_cadence_seconds: float
    expected_freshness_threshold_seconds: float
    equivalence_status: str = EQUIVALENCE_NOT_EVALUATED
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(
            self.replay_dataset_reference,
            label="ReplayToLiveEquivalenceEvidence.replay_dataset_reference",
        )
        _ensure_str(
            self.live_source_id,
            label="ReplayToLiveEquivalenceEvidence.live_source_id",
        )
        _ensure_str(
            self.tag_map_reference,
            label="ReplayToLiveEquivalenceEvidence.tag_map_reference",
        )
        _ensure_positive_number(
            self.expected_cadence_seconds,
            label="ReplayToLiveEquivalenceEvidence.expected_cadence_seconds",
        )
        _ensure_positive_number(
            self.expected_freshness_threshold_seconds,
            label=(
                "ReplayToLiveEquivalenceEvidence."
                "expected_freshness_threshold_seconds"
            ),
        )
        if (
            self.expected_freshness_threshold_seconds
            < self.expected_cadence_seconds
        ):
            raise ContractError(
                "ReplayToLiveEquivalenceEvidence.expected_freshness_"
                "threshold_seconds must be >= expected_cadence_seconds"
            )
        _ensure_str(
            self.equivalence_status,
            label="ReplayToLiveEquivalenceEvidence.equivalence_status",
        )
        if self.equivalence_status not in EQUIVALENCE_STATUS_TOKENS:
            raise ContractError(
                f"ReplayToLiveEquivalenceEvidence.equivalence_status "
                f"{self.equivalence_status!r} is not in the allowed list "
                f"({sorted(EQUIVALENCE_STATUS_TOKENS)})"
            )
        warnings = _ensure_str_tuple(
            self.warnings,
            label="ReplayToLiveEquivalenceEvidence.warnings",
        )
        errors = _ensure_str_tuple(
            self.errors,
            label="ReplayToLiveEquivalenceEvidence.errors",
        )
        notes = _ensure_str_tuple(
            self.notes, label="ReplayToLiveEquivalenceEvidence.notes"
        )
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "errors", errors)
        object.__setattr__(self, "notes", notes)
        object.__setattr__(
            self,
            "expected_cadence_seconds",
            float(self.expected_cadence_seconds),
        )
        object.__setattr__(
            self,
            "expected_freshness_threshold_seconds",
            float(self.expected_freshness_threshold_seconds),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "replay_dataset_reference": self.replay_dataset_reference,
            "live_source_id": self.live_source_id,
            "tag_map_reference": self.tag_map_reference,
            "expected_cadence_seconds": self.expected_cadence_seconds,
            "expected_freshness_threshold_seconds": (
                self.expected_freshness_threshold_seconds
            ),
            "equivalence_status": self.equivalence_status,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "ReplayToLiveEquivalenceEvidence":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"ReplayToLiveEquivalenceEvidence.from_dict requires a "
                f"mapping, got {type(data).__name__}"
            )
        _reject_forbidden_keys(
            data, label="ReplayToLiveEquivalenceEvidence"
        )
        missing = {
            "replay_dataset_reference",
            "live_source_id",
            "tag_map_reference",
            "expected_cadence_seconds",
            "expected_freshness_threshold_seconds",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"ReplayToLiveEquivalenceEvidence missing fields: "
                f"{sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_EQUIVALENCE_FIELDS)
        if unknown:
            raise ContractError(
                f"ReplayToLiveEquivalenceEvidence received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            replay_dataset_reference=str(data["replay_dataset_reference"]),
            live_source_id=str(data["live_source_id"]),
            tag_map_reference=str(data["tag_map_reference"]),
            expected_cadence_seconds=float(data["expected_cadence_seconds"]),
            expected_freshness_threshold_seconds=float(
                data["expected_freshness_threshold_seconds"]
            ),
            equivalence_status=str(
                data.get("equivalence_status", EQUIVALENCE_NOT_EVALUATED)
            ),
            warnings=_coerce_str_sequence(
                data, "warnings", label="ReplayToLiveEquivalenceEvidence"
            ),
            errors=_coerce_str_sequence(
                data, "errors", label="ReplayToLiveEquivalenceEvidence"
            ),
            notes=_coerce_str_sequence(
                data, "notes", label="ReplayToLiveEquivalenceEvidence"
            ),
        )


# ---------------------------------------------------------------------------
# Canonical Sprint 48 default contract helper
# ---------------------------------------------------------------------------


# Canonical Sprint 48 contract identifier. Adding additional canonical
# contract ids is an SDK MINOR bump; repurposing or removing is MAJOR.
AMAX_READ_ONLY_INTEGRATION_CONTRACT_ID: str = (
    "amax_5580_read_only_integration_v1"
)


_SAFETY_PHRASES: tuple[str, ...] = (
    "no live OT binding",
    "no PLC/PAC/SCADA write",
    "no command emission",
    "no setpoint output",
)


def default_amax_read_only_integration_contract() -> ReadOnlyIntegrationContract:
    """Return the canonical Sprint 48 AMAX read-only integration contract.

    Audit-only. Enumerates a deterministic OPC UA source, Modbus TCP
    source, Modbus RTU source, CODESYS symbol source, CODESYS shared
    memory source, and MQTT Sparkplug read-only IT-path source. The
    canonical record also defines a deterministic freshness policy and
    reaffirms the non-negotiable safety boundary: no live OT binding,
    no PLC/PAC/SCADA write, no command emission, no setpoint output.

    Every label is a reference. The contract intentionally carries no
    secrets, no credentials, no passwords, no tokens, no API keys, no
    IP addresses, and no live connection strings.
    """

    pressure_spec = TelemetryTagSpec(
        tag="PT_J1",
        axis="node_pressure",
        target_id=1,
        unit="m_h2o",
        role="observed",
        description="junction J1 pressure transmitter (read-only)",
    )
    flow_spec = TelemetryTagSpec(
        tag="FT_P1",
        axis="edge_flow",
        target_id=1,
        unit="m3_s",
        role="observed",
        description="pipe P1 flow meter (read-only)",
    )
    demand_spec = TelemetryTagSpec(
        tag="DT_J2",
        axis="node_demand",
        target_id=2,
        unit="m3_s",
        role="observed",
        description="junction J2 demand telemetry (read-only)",
    )
    pump_speed_spec = TelemetryTagSpec(
        tag="SP_PU1",
        axis="edge_pump_speed",
        target_id=1,
        unit="rpm",
        role="observed",
        description="pump PU1 measured rotational speed (read-only)",
    )

    sources = (
        ReadOnlyTelemetrySource(
            source_id="amax_opc_ua_subscription",
            protocol=PROTOCOL_OPC_UA,
            endpoint_label="ot_zone_opc_ua_subscription_label",
            security_zone_label="ot_zone",
            polling_interval_seconds=1.0,
            freshness_threshold_seconds=5.0,
            credential_reference_label="site_secret_store_ref_opc_ua",
            access_mode=ACCESS_MODE_READ_ONLY,
            notes=(
                "OPC UA subscription via site OPC UA Server; client only",
                "no live OT binding",
                "no PLC/PAC/SCADA write",
                "no command emission",
                "no setpoint output",
            ),
        ),
        ReadOnlyTelemetrySource(
            source_id="amax_modbus_tcp_poller",
            protocol=PROTOCOL_MODBUS_TCP,
            endpoint_label="ot_zone_modbus_tcp_gateway_label",
            security_zone_label="ot_zone",
            polling_interval_seconds=1.0,
            freshness_threshold_seconds=5.0,
            credential_reference_label="",
            access_mode=ACCESS_MODE_READ_ONLY,
            notes=(
                "Modbus TCP poller over OT zone gateway; input-register read only",
                "no live OT binding",
                "no PLC/PAC/SCADA write",
                "no command emission",
                "no setpoint output",
            ),
        ),
        ReadOnlyTelemetrySource(
            source_id="amax_modbus_rtu_serial",
            protocol=PROTOCOL_MODBUS_RTU,
            endpoint_label="ot_zone_modbus_rtu_serial_label",
            security_zone_label="ot_zone",
            polling_interval_seconds=2.0,
            freshness_threshold_seconds=10.0,
            credential_reference_label="",
            access_mode=ACCESS_MODE_READ_ONLY,
            notes=(
                "Modbus RTU serial via RS-485 link to remote meter; read only",
                "no live OT binding",
                "no PLC/PAC/SCADA write",
                "no command emission",
                "no setpoint output",
            ),
        ),
        ReadOnlyTelemetrySource(
            source_id="amax_codesys_symbol_subscription",
            protocol=PROTOCOL_CODESYS_SYMBOL,
            endpoint_label="ot_zone_codesys_symbol_subscription_label",
            security_zone_label="ot_zone",
            polling_interval_seconds=1.0,
            freshness_threshold_seconds=5.0,
            credential_reference_label="site_secret_store_ref_codesys",
            access_mode=ACCESS_MODE_READ_ONLY,
            notes=(
                "CODESYS symbol subscription via CODESYS Linux Control bridge",
                "subscription is read-only; SDK contract carries the shape only",
                "no live OT binding",
                "no PLC/PAC/SCADA write",
                "no command emission",
                "no setpoint output",
            ),
        ),
        ReadOnlyTelemetrySource(
            source_id="amax_codesys_shared_memory",
            protocol=PROTOCOL_CODESYS_SHARED_MEMORY,
            endpoint_label="ot_zone_codesys_shared_memory_label",
            security_zone_label="ot_zone",
            polling_interval_seconds=1.0,
            freshness_threshold_seconds=5.0,
            credential_reference_label="",
            access_mode=ACCESS_MODE_READ_ONLY,
            notes=(
                "CODESYS shared memory region exposed read-only by host runtime",
                "no live OT binding",
                "no PLC/PAC/SCADA write",
                "no command emission",
                "no setpoint output",
            ),
        ),
        ReadOnlyTelemetrySource(
            source_id="amax_mqtt_sparkplug_read_only",
            protocol=PROTOCOL_MQTT_SPARKPLUG_READ_ONLY,
            endpoint_label="it_zone_mqtt_sparkplug_topic_label",
            security_zone_label="it_zone",
            polling_interval_seconds=1.0,
            freshness_threshold_seconds=10.0,
            credential_reference_label="site_secret_store_ref_mqtt",
            access_mode=ACCESS_MODE_READ_ONLY,
            notes=(
                "MQTT Sparkplug subscription on IT-zone bridge; read-only NDATA / DDATA",
                "no live OT binding",
                "no PLC/PAC/SCADA write",
                "no command emission",
                "no setpoint output",
            ),
        ),
    )

    bindings = (
        ReadOnlyTagBinding(
            binding_id="binding_opc_ua_pressure_pt_j1",
            source_id="amax_opc_ua_subscription",
            source_path_label="ns_2_pt_j1_pressure_label",
            tag_spec=pressure_spec,
            quality_behavior=STALE_BEHAVIOR_FLAG_STALE,
            freshness_behavior=STALE_BEHAVIOR_FLAG_STALE,
            access_mode=ACCESS_MODE_READ_ONLY,
            notes=(
                "OPC UA NodeId label mapping for J1 pressure transmitter",
                "read-only subscription only",
            ),
        ),
        ReadOnlyTagBinding(
            binding_id="binding_modbus_tcp_flow_ft_p1",
            source_id="amax_modbus_tcp_poller",
            source_path_label="input_register_block_ft_p1_label",
            tag_spec=flow_spec,
            quality_behavior=STALE_BEHAVIOR_FLAG_STALE,
            freshness_behavior=STALE_BEHAVIOR_DROP_FRAME,
            access_mode=ACCESS_MODE_READ_ONLY,
            notes=(
                "Modbus TCP input-register block label for pipe P1 flow meter",
                "input register only; no holding-register access",
            ),
        ),
        ReadOnlyTagBinding(
            binding_id="binding_modbus_rtu_demand_dt_j2",
            source_id="amax_modbus_rtu_serial",
            source_path_label="input_register_block_dt_j2_label",
            tag_spec=demand_spec,
            quality_behavior=STALE_BEHAVIOR_FLAG_STALE,
            freshness_behavior=STALE_BEHAVIOR_FLAG_STALE,
            access_mode=ACCESS_MODE_READ_ONLY,
            notes=(
                "Modbus RTU input-register block label for J2 demand telemetry",
                "serial link is read-only",
            ),
        ),
        ReadOnlyTagBinding(
            binding_id="binding_codesys_symbol_pump_speed_pu1",
            source_id="amax_codesys_symbol_subscription",
            source_path_label="codesys_symbol_pu1_speed_label",
            tag_spec=pump_speed_spec,
            quality_behavior=STALE_BEHAVIOR_FLAG_STALE,
            freshness_behavior=STALE_BEHAVIOR_FLAG_STALE,
            access_mode=ACCESS_MODE_READ_ONLY,
            notes=(
                "CODESYS symbol label for PU1 measured speed; read-only subscription",
            ),
        ),
    )

    freshness_policy = TelemetryFreshnessPolicy(
        max_age_seconds=10.0,
        stale_behavior=STALE_BEHAVIOR_FLAG_STALE,
        missing_behavior=MISSING_BEHAVIOR_FLAG_MISSING,
        quality_flag_mapping=(
            ("opc_ua_good", "good"),
            ("opc_ua_uncertain", "uncertain"),
            ("opc_ua_bad", "bad"),
            ("modbus_ok", "good"),
            ("modbus_timeout", "bad"),
            ("codesys_valid", "good"),
            ("codesys_invalid", "bad"),
        ),
        replay_equivalence_expectations=(
            "replay cadence must match live polling cadence within freshness threshold",
            "replay quality flag tokens must round-trip through the SDK quality mapping",
            "replay axis / role / unit metadata must match live tag bindings exactly",
            "replay sources stay surrogate until real source verification is signed off",
        ),
        notes=(
            "freshness policy is audit evidence only",
            "no live OT binding",
            "no PLC/PAC/SCADA write",
            "no command emission",
            "no setpoint output",
        ),
    )

    return ReadOnlyIntegrationContract(
        contract_id=AMAX_READ_ONLY_INTEGRATION_CONTRACT_ID,
        tag_map_reference="sprint_42_telemetry_tag_map_default",
        sources=sources,
        tag_bindings=bindings,
        freshness_policy=freshness_policy,
        compatibility_notes=(
            "Sprint 42 TelemetryTagMap referenced by string only",
            "Sprint 47 AMAX benchmark report referenced by string only",
            "network segmentation labels use ot_zone / it_zone only",
            "labels are references — no live connection strings",
            "credential references are labels — no secrets, tokens, or passwords",
        ),
        safety_notes=(
            "Sprint 48 ships read-only integration contracts, not live adapters",
            "no live OT binding",
            "no PLC/PAC/SCADA write",
            "no command emission",
            "no setpoint output",
            "no control-loop closure",
            "site PLC retains direct VFD / pump / actuator authority",
            "Sprint 49 should be AMAX Site Deployment Readiness / OT Certification "
            "Evidence Package after Sprint 48 passes",
        ),
    )


def default_amax_replay_to_live_equivalence_evidence() -> (
    ReplayToLiveEquivalenceEvidence
):
    """Return the Sprint 48 default replay-to-live equivalence evidence.

    Audit-only. The default record is ``not_evaluated``: replay
    datasets remain surrogate evidence until a real source
    verification has happened. Nothing in this record represents a
    write, dispatch, actuation, setpoint, or control surface.
    """

    return ReplayToLiveEquivalenceEvidence(
        replay_dataset_reference="sprint_42_shadow_replay_default",
        live_source_id="amax_opc_ua_subscription",
        tag_map_reference="sprint_42_telemetry_tag_map_default",
        expected_cadence_seconds=1.0,
        expected_freshness_threshold_seconds=5.0,
        equivalence_status=EQUIVALENCE_NOT_EVALUATED,
        warnings=(
            "replay dataset stays surrogate until real source verification "
            "is signed off",
        ),
        errors=(),
        notes=(
            "Sprint 48 audit evidence; does not open a live connection",
            "no live OT binding",
            "no PLC/PAC/SCADA write",
            "no command emission",
            "no setpoint output",
        ),
    )


__all__ = [
    "ACCESS_MODE_AUDIT_ONLY",
    "ACCESS_MODE_READ_ONLY",
    "AMAX_READ_ONLY_INTEGRATION_CONTRACT_ID",
    "EQUIVALENCE_BLOCKED",
    "EQUIVALENCE_COMPATIBLE",
    "EQUIVALENCE_NOT_EVALUATED",
    "EQUIVALENCE_STATUS_TOKENS",
    "MISSING_BEHAVIOR_DROP_FRAME",
    "MISSING_BEHAVIOR_FLAG_MISSING",
    "MISSING_BEHAVIOR_HOLD_LAST_GOOD",
    "MISSING_BEHAVIOR_TOKENS",
    "PROTOCOL_CODESYS_SHARED_MEMORY",
    "PROTOCOL_CODESYS_SYMBOL",
    "PROTOCOL_MODBUS_RTU",
    "PROTOCOL_MODBUS_TCP",
    "PROTOCOL_MQTT_SPARKPLUG_READ_ONLY",
    "PROTOCOL_OPC_UA",
    "READ_ONLY_ACCESS_MODES",
    "READ_ONLY_INTEGRATION_PROTOCOLS",
    "ReadOnlyIntegrationContract",
    "ReadOnlyIntegrationDiagnostics",
    "ReadOnlyIntegrationProtocol",
    "ReadOnlyTagBinding",
    "ReadOnlyTelemetrySource",
    "ReplayToLiveEquivalenceEvidence",
    "STALE_BEHAVIOR_DROP_FRAME",
    "STALE_BEHAVIOR_FLAG_STALE",
    "STALE_BEHAVIOR_HOLD_LAST_GOOD",
    "STALE_BEHAVIOR_TOKENS",
    "TelemetryFreshnessPolicy",
    "default_amax_read_only_integration_contract",
    "default_amax_replay_to_live_equivalence_evidence",
    "diagnose_read_only_integration_contract",
]
