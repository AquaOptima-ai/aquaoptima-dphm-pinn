"""Read-only deployment readiness report for Optimizer Lite."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Tuple

from ..api import create_app
from ..app.demo import run_demo
from ..config import compute_config_hash, load_site_config


@dataclass(frozen=True)
class GateResult:
    name: str
    status: str
    reason_codes: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SafetyReadiness:
    no_console_direct_write_path: bool = True
    no_new_field_write_path: bool = True
    baseline_remains_authority: bool = True


@dataclass(frozen=True)
class ConfigReadiness:
    site_id: str | None
    config_path: str
    config_hash: str | None = None


@dataclass(frozen=True)
class ReplayReadiness:
    replay_path: str
    requested_cycles: int
    audit_count: int = 0
    learner_status: str | None = None
    performance_status: str | None = None
    advisory_status: str | None = None


@dataclass(frozen=True)
class ApiReadiness:
    has_console_evidence_endpoint: bool
    has_status_endpoint: bool
    has_recommendation_endpoint: bool


@dataclass(frozen=True)
class HandoffReadiness:
    operator_review_required: bool
    checklist: Tuple[str, ...]


@dataclass(frozen=True)
class DeploymentReadinessReport:
    status: str
    read_only: bool
    influences_control: bool
    reason_codes: Tuple[str, ...]
    gates: Tuple[GateResult, ...]
    safety: SafetyReadiness
    config: ConfigReadiness
    replay: ReplayReadiness
    api: ApiReadiness
    handoff: HandoffReadiness

    def __post_init__(self) -> None:
        object.__setattr__(self, "read_only", True)
        object.__setattr__(self, "influences_control", False)
        if self.status not in ("ready_for_pilot_review", "blocked"):
            raise ValueError(f"unsupported readiness status: {self.status!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DeploymentReadinessChecker:
    """Build deterministic pre-pilot readiness reports.

    The checker is a gate/report only.  It reads config, replay/demo output,
    and API route metadata; it never emits commands or requests field writes.
    """

    def check(self, *, config_path: str | Path, replay_path: str | Path, cycles: int = 4) -> DeploymentReadinessReport:
        config_path = Path(config_path)
        replay_path = Path(replay_path)
        gates: list[GateResult] = []
        reasons: list[str] = []
        config_info = ConfigReadiness(site_id=None, config_path=str(config_path), config_hash=None)
        replay_info = ReplayReadiness(replay_path=str(replay_path), requested_cycles=cycles)

        config = None
        if not config_path.exists():
            gates.append(GateResult("config_exists", "block", ("missing_config_file",)))
            reasons.append("missing_config_file")
        else:
            config = load_site_config(config_path)
            config_info = ConfigReadiness(
                site_id=config.site_id,
                config_path=str(config_path),
                config_hash=compute_config_hash(config),
            )
            gates.append(GateResult("config_exists", "pass", ("config_loaded",)))

        if not replay_path.exists():
            gates.append(GateResult("replay_exists", "block", ("missing_replay_file",)))
            reasons.append("missing_replay_file")
        else:
            gates.append(GateResult("replay_exists", "pass", ("replay_loaded",)))

        api_info = self._api_readiness()
        gates.append(
            GateResult(
                "console_evidence_api",
                "pass" if api_info.has_console_evidence_endpoint else "block",
                ("console_evidence_endpoint_present",) if api_info.has_console_evidence_endpoint else ("console_evidence_endpoint_missing",),
            )
        )
        if not api_info.has_console_evidence_endpoint:
            reasons.append("console_evidence_endpoint_missing")

        if config is not None and replay_path.exists():
            demo = run_demo(
                config_path=config_path,
                replay_path=replay_path,
                cycles=cycles,
                enable_learner_shadow=True,
                enable_performance_shadow=True,
                enable_advisory_ranking=True,
            )
            learner = demo.get("learner_shadow", {})
            performance = demo.get("performance_model", {})
            advisory = demo.get("advisory_ranking", {})
            audit_count_raw = demo.get("audit_count")
            audit_count = int(audit_count_raw) if isinstance(audit_count_raw, (int, float, str)) else 0
            replay_info = ReplayReadiness(
                replay_path=str(replay_path),
                requested_cycles=cycles,
                audit_count=audit_count,
                learner_status=learner.get("status") if isinstance(learner, dict) else None,
                performance_status=performance.get("readiness") if isinstance(performance, dict) else None,
                advisory_status=advisory.get("readiness") if isinstance(advisory, dict) else None,
            )
            if replay_info.audit_count >= cycles:
                gates.append(GateResult("demo_replay_cycles", "pass", ("audit_count_matches_cycles",)))
            else:
                gates.append(GateResult("demo_replay_cycles", "block", ("audit_count_below_requested_cycles",)))
                reasons.append("audit_count_below_requested_cycles")

        handoff = HandoffReadiness(
            operator_review_required=True,
            checklist=(
                "review_console_evidence_before_pilot",
                "confirm_site_tag_map_and_units",
                "confirm_existing_mvp_baseline_authority",
                "confirm_no_new_field_write_path",
                "archive_readiness_report_with_operator_handoff",
            ),
        )
        status = "blocked" if reasons or any(g.status == "block" for g in gates) else "ready_for_pilot_review"
        return DeploymentReadinessReport(
            status=status,
            read_only=True,
            influences_control=False,
            reason_codes=tuple(dict.fromkeys(reasons)),
            gates=tuple(gates),
            safety=SafetyReadiness(),
            config=config_info,
            replay=replay_info,
            api=api_info,
            handoff=handoff,
        )

    def _api_readiness(self) -> ApiReadiness:
        app = create_app()
        paths = {route.path for route in app.routes if hasattr(route, "path")}
        return ApiReadiness(
            has_console_evidence_endpoint="/console/evidence/current" in paths,
            has_status_endpoint="/status" in paths,
            has_recommendation_endpoint="/recommendation/current" in paths,
        )
