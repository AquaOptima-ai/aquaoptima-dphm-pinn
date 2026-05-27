"""Sprint 47 — AMAX CPU benchmark / packaging smoke evidence SDK projection.

Sprint 47 promotes the Advantech AMAX-5580 CPU inference feasibility
case from datasheet evidence (Sprint 46) to host-derived **surrogate**
benchmark evidence. This module owns the SDK *shapes* the offline
benchmark runner and CLI emit:

* :class:`AMAXBenchmarkScenario` — frozen scenario record (graph
  size, sequence length, batch size, model hidden dim, runtime,
  thread count, target hardware profile id).
* :class:`AMAXBenchmarkMetrics` — frozen latency p50 / p95 / p99
  envelope plus optional RSS / framework / Python / torch / host /
  surrogate metadata.
* :class:`AMAXBenchmarkReport` — frozen scenario + metrics +
  feasibility / package / cadence classification + warnings record.
* :func:`canonical_amax_benchmark_scenarios` — canonical Sprint 47
  scenario tuple (branch / single-loop / pump).
* :func:`classify_supervisory_cadence` — pure helper that maps a
  measured p95 latency to a supervisory cadence bucket.

The SDK module is stdlib-only. It does **not** import torch and it
performs no hardware probing, no network IO, no PLC/PAC client code,
no live OT binding, no PLC/PAC/SCADA write, no command emission, no
setpoint output, no control-loop closure, no model loading, no inline
model weights. Benchmarks captured here remain evidence-only until run
on real AMAX-5580 hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..base.envelope import ContractError
from ..safety.vocabulary import FORBIDDEN_VOCABULARY, contains_forbidden_token
from .hardware_profile import AMAX_5580_PROFILE_ID


# ---------------------------------------------------------------------------
# Canonical vocabularies
# ---------------------------------------------------------------------------


# Supervisory cadence buckets recognised by the Sprint 47 cadence
# classifier. ``sub_1s_supervisory`` covers p95 latency at or below
# 1000 ms; ``sub_5s_supervisory`` covers up to 5000 ms;
# ``sub_60s_supervisory`` covers up to 60000 ms; ``slower_than_60s``
# covers anything beyond 60 s. Evidence classification only — not a
# real-time control guarantee.
AMAX_BENCHMARK_CADENCE_BUCKETS: tuple[str, ...] = (
    "sub_1s_supervisory",
    "sub_5s_supervisory",
    "sub_60s_supervisory",
    "slower_than_60s",
)


# Latency thresholds for the cadence classifier, in milliseconds. The
# classifier picks the smallest bucket whose threshold is >= p95.
_CADENCE_THRESHOLDS_MS: tuple[tuple[str, float], ...] = (
    ("sub_1s_supervisory", 1000.0),
    ("sub_5s_supervisory", 5000.0),
    ("sub_60s_supervisory", 60000.0),
)


# Frameworks / runtimes the Sprint 47 SDK contract recognises. Adding a
# new entry is an SDK MINOR bump; repurposing or removing is MAJOR.
AMAX_BENCHMARK_FRAMEWORKS: frozenset[str] = frozenset(
    {
        "pytorch_cpu",
        "onnx_runtime_cpu",
        "openvino",
    }
)


_SCENARIO_FIELDS: tuple[str, ...] = (
    "scenario_id",
    "description",
    "num_nodes",
    "num_edges",
    "sequence_length",
    "batch_size",
    "hidden_dim",
    "framework",
    "thread_count",
    "target_hardware_profile_id",
    "notes",
)


_METRICS_FIELDS: tuple[str, ...] = (
    "latency_p50_ms",
    "latency_p95_ms",
    "latency_p99_ms",
    "memory_rss_max_kb",
    "iterations",
    "warmup_iterations",
    "framework",
    "python_version",
    "torch_version",
    "host_label",
    "surrogate_hardware",
    "notes",
)


_REPORT_FIELDS: tuple[str, ...] = (
    "scenario",
    "metrics",
    "cadence_classification",
    "feasibility_profile_id",
    "package_manifest_reference",
    "surrogate_hardware",
    "warnings",
    "notes",
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


def _ensure_optional_str(value: Any, *, label: str) -> str:
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


def _ensure_positive_int(value: Any, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ContractError(
            f"{label} must be an int, got {type(value).__name__}"
        )
    if value <= 0:
        raise ContractError(f"{label} must be positive")
    return value


def _ensure_non_negative_int(value: Any, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ContractError(
            f"{label} must be an int, got {type(value).__name__}"
        )
    if value < 0:
        raise ContractError(f"{label} must be non-negative")
    return value


def _ensure_non_negative_float(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(
            f"{label} must be a real number, got {type(value).__name__}"
        )
    if value < 0:
        raise ContractError(f"{label} must be non-negative")
    return float(value)


def _ensure_optional_non_negative_int(
    value: Any, *, label: str
) -> int | None:
    if value is None:
        return None
    return _ensure_non_negative_int(value, label=label)


def _coerce_sequence(
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


# ---------------------------------------------------------------------------
# AMAXBenchmarkScenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AMAXBenchmarkScenario:
    """Frozen Sprint 47 AMAX CPU benchmark scenario record.

    Audit-only. Describes the topology size, sequence length, batch
    size, hidden dim, framework, and thread budget for a single
    benchmark scenario. Nothing in this record represents a write,
    dispatch, actuation, setpoint, or control surface.
    """

    scenario_id: str
    description: str
    num_nodes: int
    num_edges: int
    sequence_length: int
    batch_size: int
    hidden_dim: int
    framework: str
    thread_count: int
    target_hardware_profile_id: str
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_str(self.scenario_id, label="AMAXBenchmarkScenario.scenario_id")
        _ensure_str(self.description, label="AMAXBenchmarkScenario.description")
        _ensure_positive_int(
            self.num_nodes, label="AMAXBenchmarkScenario.num_nodes"
        )
        _ensure_positive_int(
            self.num_edges, label="AMAXBenchmarkScenario.num_edges"
        )
        _ensure_positive_int(
            self.sequence_length,
            label="AMAXBenchmarkScenario.sequence_length",
        )
        _ensure_positive_int(
            self.batch_size, label="AMAXBenchmarkScenario.batch_size"
        )
        _ensure_positive_int(
            self.hidden_dim, label="AMAXBenchmarkScenario.hidden_dim"
        )
        _ensure_str(self.framework, label="AMAXBenchmarkScenario.framework")
        if self.framework not in AMAX_BENCHMARK_FRAMEWORKS:
            raise ContractError(
                f"AMAXBenchmarkScenario.framework {self.framework!r} is not "
                f"in the allowed list ({sorted(AMAX_BENCHMARK_FRAMEWORKS)})"
            )
        _ensure_positive_int(
            self.thread_count, label="AMAXBenchmarkScenario.thread_count"
        )
        _ensure_str(
            self.target_hardware_profile_id,
            label="AMAXBenchmarkScenario.target_hardware_profile_id",
        )
        notes = _ensure_str_tuple(
            self.notes, label="AMAXBenchmarkScenario.notes"
        )
        object.__setattr__(self, "notes", notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "description": self.description,
            "num_nodes": self.num_nodes,
            "num_edges": self.num_edges,
            "sequence_length": self.sequence_length,
            "batch_size": self.batch_size,
            "hidden_dim": self.hidden_dim,
            "framework": self.framework,
            "thread_count": self.thread_count,
            "target_hardware_profile_id": self.target_hardware_profile_id,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AMAXBenchmarkScenario":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AMAXBenchmarkScenario.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="AMAXBenchmarkScenario")
        missing = {
            "scenario_id",
            "description",
            "num_nodes",
            "num_edges",
            "sequence_length",
            "batch_size",
            "hidden_dim",
            "framework",
            "thread_count",
            "target_hardware_profile_id",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"AMAXBenchmarkScenario missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_SCENARIO_FIELDS)
        if unknown:
            raise ContractError(
                f"AMAXBenchmarkScenario received unknown fields: "
                f"{sorted(unknown)}"
            )
        return cls(
            scenario_id=str(data["scenario_id"]),
            description=str(data["description"]),
            num_nodes=int(data["num_nodes"]),
            num_edges=int(data["num_edges"]),
            sequence_length=int(data["sequence_length"]),
            batch_size=int(data["batch_size"]),
            hidden_dim=int(data["hidden_dim"]),
            framework=str(data["framework"]),
            thread_count=int(data["thread_count"]),
            target_hardware_profile_id=str(
                data["target_hardware_profile_id"]
            ),
            notes=_coerce_sequence(
                data, "notes", label="AMAXBenchmarkScenario"
            ),
        )


# ---------------------------------------------------------------------------
# AMAXBenchmarkMetrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AMAXBenchmarkMetrics:
    """Frozen Sprint 47 AMAX CPU benchmark metrics record.

    Audit-only. Captures p50/p95/p99 latency (milliseconds), iteration
    counts, and the measured framework / Python / torch / host /
    surrogate metadata. Nothing in this record represents a write,
    dispatch, actuation, setpoint, or control surface.
    """

    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    iterations: int
    warmup_iterations: int
    framework: str
    python_version: str
    torch_version: str
    host_label: str
    surrogate_hardware: bool = True
    memory_rss_max_kb: int | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_non_negative_float(
            self.latency_p50_ms,
            label="AMAXBenchmarkMetrics.latency_p50_ms",
        )
        _ensure_non_negative_float(
            self.latency_p95_ms,
            label="AMAXBenchmarkMetrics.latency_p95_ms",
        )
        _ensure_non_negative_float(
            self.latency_p99_ms,
            label="AMAXBenchmarkMetrics.latency_p99_ms",
        )
        _ensure_positive_int(
            self.iterations, label="AMAXBenchmarkMetrics.iterations"
        )
        _ensure_non_negative_int(
            self.warmup_iterations,
            label="AMAXBenchmarkMetrics.warmup_iterations",
        )
        _ensure_str(self.framework, label="AMAXBenchmarkMetrics.framework")
        if self.framework not in AMAX_BENCHMARK_FRAMEWORKS:
            raise ContractError(
                f"AMAXBenchmarkMetrics.framework {self.framework!r} is not "
                f"in the allowed list ({sorted(AMAX_BENCHMARK_FRAMEWORKS)})"
            )
        _ensure_str(
            self.python_version, label="AMAXBenchmarkMetrics.python_version"
        )
        if not isinstance(self.torch_version, str):
            raise ContractError(
                "AMAXBenchmarkMetrics.torch_version must be a string"
            )
        _ensure_optional_str(
            self.torch_version, label="AMAXBenchmarkMetrics.torch_version"
        )
        _ensure_str(self.host_label, label="AMAXBenchmarkMetrics.host_label")
        if not isinstance(self.surrogate_hardware, bool):
            raise ContractError(
                "AMAXBenchmarkMetrics.surrogate_hardware must be a bool"
            )
        _ensure_optional_non_negative_int(
            self.memory_rss_max_kb,
            label="AMAXBenchmarkMetrics.memory_rss_max_kb",
        )
        if self.latency_p95_ms < self.latency_p50_ms:
            raise ContractError(
                "AMAXBenchmarkMetrics.latency_p95_ms must be >= latency_p50_ms"
            )
        if self.latency_p99_ms < self.latency_p95_ms:
            raise ContractError(
                "AMAXBenchmarkMetrics.latency_p99_ms must be >= latency_p95_ms"
            )
        notes = _ensure_str_tuple(
            self.notes, label="AMAXBenchmarkMetrics.notes"
        )
        object.__setattr__(self, "notes", notes)
        object.__setattr__(
            self, "latency_p50_ms", float(self.latency_p50_ms)
        )
        object.__setattr__(
            self, "latency_p95_ms", float(self.latency_p95_ms)
        )
        object.__setattr__(
            self, "latency_p99_ms", float(self.latency_p99_ms)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "latency_p99_ms": self.latency_p99_ms,
            "iterations": self.iterations,
            "warmup_iterations": self.warmup_iterations,
            "framework": self.framework,
            "python_version": self.python_version,
            "torch_version": self.torch_version,
            "host_label": self.host_label,
            "surrogate_hardware": self.surrogate_hardware,
            "memory_rss_max_kb": self.memory_rss_max_kb,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AMAXBenchmarkMetrics":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AMAXBenchmarkMetrics.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="AMAXBenchmarkMetrics")
        missing = {
            "latency_p50_ms",
            "latency_p95_ms",
            "latency_p99_ms",
            "iterations",
            "warmup_iterations",
            "framework",
            "python_version",
            "torch_version",
            "host_label",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"AMAXBenchmarkMetrics missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_METRICS_FIELDS)
        if unknown:
            raise ContractError(
                f"AMAXBenchmarkMetrics received unknown fields: "
                f"{sorted(unknown)}"
            )
        raw_rss = data.get("memory_rss_max_kb")
        rss = None if raw_rss is None else int(raw_rss)
        surrogate_raw = data.get("surrogate_hardware", True)
        if not isinstance(surrogate_raw, bool):
            raise ContractError(
                "AMAXBenchmarkMetrics.surrogate_hardware must be a bool"
            )
        return cls(
            latency_p50_ms=float(data["latency_p50_ms"]),
            latency_p95_ms=float(data["latency_p95_ms"]),
            latency_p99_ms=float(data["latency_p99_ms"]),
            iterations=int(data["iterations"]),
            warmup_iterations=int(data["warmup_iterations"]),
            framework=str(data["framework"]),
            python_version=str(data["python_version"]),
            torch_version=str(data["torch_version"]),
            host_label=str(data["host_label"]),
            surrogate_hardware=surrogate_raw,
            memory_rss_max_kb=rss,
            notes=_coerce_sequence(
                data, "notes", label="AMAXBenchmarkMetrics"
            ),
        )


# ---------------------------------------------------------------------------
# AMAXBenchmarkReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AMAXBenchmarkReport:
    """Frozen Sprint 47 AMAX CPU benchmark report record.

    Audit-only. Bundles a single :class:`AMAXBenchmarkScenario` with
    its measured :class:`AMAXBenchmarkMetrics`, the supervisory
    cadence classification, the feasibility / package references the
    benchmark applies to, and an explicit surrogate-hardware flag.
    Nothing in this record represents a write, dispatch, actuation,
    setpoint, or control surface.
    """

    scenario: AMAXBenchmarkScenario
    metrics: AMAXBenchmarkMetrics
    cadence_classification: str
    feasibility_profile_id: str = AMAX_5580_PROFILE_ID
    package_manifest_reference: str = ""
    surrogate_hardware: bool = True
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.scenario, AMAXBenchmarkScenario):
            raise ContractError(
                "AMAXBenchmarkReport.scenario must be an "
                "AMAXBenchmarkScenario"
            )
        if not isinstance(self.metrics, AMAXBenchmarkMetrics):
            raise ContractError(
                "AMAXBenchmarkReport.metrics must be an "
                "AMAXBenchmarkMetrics"
            )
        _ensure_str(
            self.cadence_classification,
            label="AMAXBenchmarkReport.cadence_classification",
        )
        if self.cadence_classification not in AMAX_BENCHMARK_CADENCE_BUCKETS:
            raise ContractError(
                f"AMAXBenchmarkReport.cadence_classification "
                f"{self.cadence_classification!r} is not in the allowed "
                f"list ({list(AMAX_BENCHMARK_CADENCE_BUCKETS)})"
            )
        _ensure_str(
            self.feasibility_profile_id,
            label="AMAXBenchmarkReport.feasibility_profile_id",
        )
        if not isinstance(self.package_manifest_reference, str):
            raise ContractError(
                "AMAXBenchmarkReport.package_manifest_reference must be a string"
            )
        _ensure_optional_str(
            self.package_manifest_reference,
            label="AMAXBenchmarkReport.package_manifest_reference",
        )
        if not isinstance(self.surrogate_hardware, bool):
            raise ContractError(
                "AMAXBenchmarkReport.surrogate_hardware must be a bool"
            )
        warnings = _ensure_str_tuple(
            self.warnings, label="AMAXBenchmarkReport.warnings"
        )
        notes = _ensure_str_tuple(
            self.notes, label="AMAXBenchmarkReport.notes"
        )
        if self.surrogate_hardware != self.metrics.surrogate_hardware:
            raise ContractError(
                "AMAXBenchmarkReport.surrogate_hardware must match "
                "metrics.surrogate_hardware"
            )
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "notes", notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario.to_dict(),
            "metrics": self.metrics.to_dict(),
            "cadence_classification": self.cadence_classification,
            "feasibility_profile_id": self.feasibility_profile_id,
            "package_manifest_reference": self.package_manifest_reference,
            "surrogate_hardware": self.surrogate_hardware,
            "warnings": list(self.warnings),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AMAXBenchmarkReport":
        if not isinstance(data, Mapping):
            raise ContractError(
                f"AMAXBenchmarkReport.from_dict requires a mapping, got "
                f"{type(data).__name__}"
            )
        _reject_forbidden_keys(data, label="AMAXBenchmarkReport")
        missing = {
            "scenario",
            "metrics",
            "cadence_classification",
        } - set(data.keys())
        if missing:
            raise ContractError(
                f"AMAXBenchmarkReport missing fields: {sorted(missing)}"
            )
        unknown = set(data.keys()) - set(_REPORT_FIELDS)
        if unknown:
            raise ContractError(
                f"AMAXBenchmarkReport received unknown fields: "
                f"{sorted(unknown)}"
            )
        surrogate_raw = data.get("surrogate_hardware", True)
        if not isinstance(surrogate_raw, bool):
            raise ContractError(
                "AMAXBenchmarkReport.surrogate_hardware must be a bool"
            )
        return cls(
            scenario=AMAXBenchmarkScenario.from_dict(data["scenario"]),
            metrics=AMAXBenchmarkMetrics.from_dict(data["metrics"]),
            cadence_classification=str(data["cadence_classification"]),
            feasibility_profile_id=str(
                data.get("feasibility_profile_id", AMAX_5580_PROFILE_ID)
            ),
            package_manifest_reference=str(
                data.get("package_manifest_reference", "")
            ),
            surrogate_hardware=surrogate_raw,
            warnings=_coerce_sequence(
                data, "warnings", label="AMAXBenchmarkReport"
            ),
            notes=_coerce_sequence(
                data, "notes", label="AMAXBenchmarkReport"
            ),
        )


# ---------------------------------------------------------------------------
# Cadence classifier
# ---------------------------------------------------------------------------


def classify_supervisory_cadence(latency_p95_ms: float) -> str:
    """Map a measured p95 latency (milliseconds) to a cadence bucket.

    Evidence classification only — this helper does **not** authorise a
    control loop, command emission, setpoint output, or any closed-loop
    surface. The Sprint 47 cadence buckets are:

    * ``sub_1s_supervisory`` for p95 <= 1000 ms;
    * ``sub_5s_supervisory`` for 1000 < p95 <= 5000 ms;
    * ``sub_60s_supervisory`` for 5000 < p95 <= 60000 ms;
    * ``slower_than_60s`` for p95 > 60000 ms.
    """

    if isinstance(latency_p95_ms, bool) or not isinstance(
        latency_p95_ms, (int, float)
    ):
        raise ContractError(
            "classify_supervisory_cadence requires a real-number "
            "latency_p95_ms"
        )
    if latency_p95_ms < 0:
        raise ContractError(
            "classify_supervisory_cadence requires latency_p95_ms >= 0"
        )
    for bucket, threshold in _CADENCE_THRESHOLDS_MS:
        if latency_p95_ms <= threshold:
            return bucket
    return "slower_than_60s"


# ---------------------------------------------------------------------------
# Canonical Sprint 47 scenarios
# ---------------------------------------------------------------------------


# Canonical Sprint 47 scenario identifiers. Adding additional canonical
# scenarios is an SDK MINOR bump; repurposing or removing is MAJOR.
AMAX_BENCHMARK_SCENARIO_BRANCH: str = "amax_cpu_branch_smoke"
AMAX_BENCHMARK_SCENARIO_SINGLE_LOOP: str = "amax_cpu_single_loop_smoke"
AMAX_BENCHMARK_SCENARIO_PUMP: str = "amax_cpu_pump_smoke"


def canonical_amax_benchmark_scenarios() -> tuple[
    AMAXBenchmarkScenario, ...
]:
    """Return the canonical Sprint 47 AMAX CPU benchmark scenario tuple.

    Tuple order is stable: branch first, single-loop second, pump
    third. Sequence length matches the Sprint 3 SCADA window of 32
    steps. Hidden dim, batch size, and thread count are kept small so
    the harness fits a Celeron / i5 / i7 8 GB AMAX-5580 envelope and
    is cheap enough for CI on a developer host.

    Every record carries audit-only notes that reaffirm the
    non-negotiable safety boundary: no live OT binding, no PLC/PAC/SCADA
    write, no command emission, no setpoint output.
    """
    safety_notes = (
        "no live OT binding",
        "no PLC/PAC/SCADA write",
        "no command emission",
        "no setpoint output",
    )
    return (
        AMAXBenchmarkScenario(
            scenario_id=AMAX_BENCHMARK_SCENARIO_BRANCH,
            description=(
                "Branch fixture: reservoir feeding two demand nodes through "
                "a Y junction; smallest dPHM-PINN smoke scenario."
            ),
            num_nodes=4,
            num_edges=3,
            sequence_length=32,
            batch_size=1,
            hidden_dim=16,
            framework="pytorch_cpu",
            thread_count=1,
            target_hardware_profile_id=AMAX_5580_PROFILE_ID,
            notes=safety_notes,
        ),
        AMAXBenchmarkScenario(
            scenario_id=AMAX_BENCHMARK_SCENARIO_SINGLE_LOOP,
            description=(
                "Single-loop fixture: triangular loop with one demand; "
                "smallest closed-loop topology in the dPHM fixture suite."
            ),
            num_nodes=4,
            num_edges=4,
            sequence_length=32,
            batch_size=1,
            hidden_dim=16,
            framework="pytorch_cpu",
            thread_count=1,
            target_hardware_profile_id=AMAX_5580_PROFILE_ID,
            notes=safety_notes,
        ),
        AMAXBenchmarkScenario(
            scenario_id=AMAX_BENCHMARK_SCENARIO_PUMP,
            description=(
                "Pump fixture: suction reservoir, in-line pump, delivery "
                "pipe to a demand node; smallest pump-edge smoke scenario."
            ),
            num_nodes=3,
            num_edges=2,
            sequence_length=32,
            batch_size=1,
            hidden_dim=16,
            framework="pytorch_cpu",
            thread_count=1,
            target_hardware_profile_id=AMAX_5580_PROFILE_ID,
            notes=safety_notes,
        ),
    )


__all__ = [
    "AMAX_BENCHMARK_CADENCE_BUCKETS",
    "AMAX_BENCHMARK_FRAMEWORKS",
    "AMAX_BENCHMARK_SCENARIO_BRANCH",
    "AMAX_BENCHMARK_SCENARIO_PUMP",
    "AMAX_BENCHMARK_SCENARIO_SINGLE_LOOP",
    "AMAXBenchmarkMetrics",
    "AMAXBenchmarkReport",
    "AMAXBenchmarkScenario",
    "canonical_amax_benchmark_scenarios",
    "classify_supervisory_cadence",
]
