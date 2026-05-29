"""AOPSO Sprint 34 -- Unified A+B offline evidence package builder.

OFFLINE EVIDENCE ONLY. This module DOES NOT load any model, does not drive
any actuation, does not emit setpoints, does not open any network/OT connection, and does
not write to anything other than the offline evidence directory it is told to
write to. It assembles a HONEST unified package out of the locked-March-2026
holdout scorecards already produced by Sprints 30b (Pillar A) and 33
(Pillar B):

* an aggregate unified scorecard JSON that carries BOTH pillars' verdicts;
* a portable health-event export (CSV + JSON);
* a portable efficiency-advisory export (CSV + JSON);
* a static, read-only HTML dashboard (no forms, no inputs, no buttons that
  set anything);
* a plant-manager executive report (Markdown);
* an ML audit appendix (Markdown);
* an artifact manifest (JSON) that wraps the pillar artifacts in the
  contracts-SDK ``ModelArtifactRecord`` shape with the all-True safety flag
  set;
* a 1-page plant-manager summary (Markdown).

The package's gate is FAILED if any of the unbreakable safety invariants
is violated (banner missing, dashboard contains a form/input/button, edge
import / write-connector token appears anywhere in the modeling source).

The verdicts of the underlying pillars are REPORTED HONESTLY: an honest
FAIL on either pillar is still a PASS of the Sprint 34 packaging gate IFF
the package itself preserves the honest verdict and the boundary; it
becomes a FAIL of the Sprint 34 packaging gate only when the package
misrepresents the underlying evidence or relaxes the safety boundary.
"""

from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import io
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from aquaoptima_contracts import ModelArtifactRecord  # noqa: F401  (re-export)

from .efficiency_artifact_schema import build_efficiency_artifact_record
from .governance import (
    GovernanceScanResult,
    scan_modeling_source_for_governance_violations,
)
from .health_artifact_schema import build_health_artifact_record

# --------------------------------------------------------------------------- #
# Identity & invariants
# --------------------------------------------------------------------------- #
SPRINT: int = 34
REPORT_VERSION: str = "sprint34.unified_ab.v1"

# This banner string MUST appear verbatim on every surface produced by this
# packager (scorecard JSON, dashboard HTML, every report, every export
# metadata block). Tests pin the exact string.
SAFETY_BANNER: str = (
    "ADVISORY-ONLY OFFLINE EVIDENCE - NOT FOR ACTUATION OR CONTROL - "
    "NO LIVE SITE INTEGRATION - SITE DEPLOYMENT NOT AUTHORIZED IN THIS VERSION"
)

# Permanent "cannot claim" statements: the package is required to display
# these on every report surface.
CANNOT_CLAIM_STATEMENTS: tuple[str, ...] = (
    "We do NOT claim guaranteed energy savings.",
    "We do NOT claim a deployable control policy.",
    "We do NOT claim field-validated fault recall or predictive maintenance accuracy.",
    "We do NOT claim site integration, actuation, or write-path readiness.",
    "We do NOT claim that an advisory operating point may be used as a setpoint.",
    "We do NOT claim opportunity on intervals the envelope honestly REJECTED.",
)

# Languages/phrases allowed for Pillar B (advisory language). These appear in
# the executive report verbatim.
ALLOWED_PILLAR_B_LANGUAGE: tuple[str, ...] = (
    "In offline historical replay, the matched-condition envelope identified an "
    "estimated counterfactual opportunity on supported intervals only.",
    "Under similar historical demand/head/level/pressure conditions, lower "
    "specific energy was observed at the reported speed range.",
    "This is a counterfactual offline estimate requiring future operational "
    "validation under the same hydraulic constraints.",
    "No control action was taken.",
)

# Edge / packaging is BLOCKED. These are the explicit, honest "blocked" tokens
# we emit into the package so any reviewer immediately sees the boundary.
PACKAGING_BLOCKS: Mapping[str, str] = {
    "onnx_export": "BLOCKED -- not produced in this sprint",
    "edge_wiring": "BLOCKED -- no aquaoptima.edge / aquaoptima_contracts.edge imports",
    "site_integration": "BLOCKED -- not authorized in this version",
    "control_endpoint": "BLOCKED -- no control endpoints exist",
    "ui_controls_that_set_anything": "BLOCKED -- read-only dashboard, no form/input/button",
    "write_path": "BLOCKED -- no setpoint, no actuation, no OT connector",
}

# Paths to the upstream pillar scorecards, relative to the repo root.
DEFAULT_PILLAR_A_SCORECARD = Path("data/eval/pillarA/sprint30b_fullyear_holdout_scorecard.json")
DEFAULT_PILLAR_B_SCORECARD = Path("data/eval/pillarB/sprint33_locked_march_scorecard.json")

# Where the Sprint 34 unified package writes its artifacts.
DEFAULT_UNIFIED_DIR = Path("data/eval/unified")


# --------------------------------------------------------------------------- #
# IO helpers
# --------------------------------------------------------------------------- #
def _read_json(path: Path) -> dict[str, Any]:
    """Tolerant JSON loader -- handles ``NaN`` literals so a sprint33-style
    scorecard with ``NaN`` numbers in its samples can be loaded losslessly."""
    text = path.read_text(encoding="utf-8")
    # Python's stdlib json accepts NaN/Infinity by default; we just call it.
    return json.loads(text)


def _file_sha256(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def _utcnow_iso() -> str:
    """UTC ISO-8601 'now' with no microseconds and a 'Z' suffix."""
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


# --------------------------------------------------------------------------- #
# Verdict synthesis
# --------------------------------------------------------------------------- #
def _read_pillar_a(scorecard: Mapping[str, Any]) -> dict[str, Any]:
    verdict = str(scorecard.get("verdict", "UNKNOWN")).upper()
    gate = scorecard.get("acceptance_gate", {}) or {}
    metrics = (gate.get("metrics") or {}) if isinstance(gate, Mapping) else {}
    holdout = scorecard.get("holdout_window") or {}
    proto = scorecard.get("out_of_sample_protocol") or {}
    return {
        "verdict": verdict,
        "gate_version": gate.get("gate_version") or scorecard.get("gate_version"),
        "rule": gate.get("rule"),
        "rule_parameters": gate.get("rule_parameters"),
        "criteria": gate.get("criteria"),
        "metrics": dict(metrics) if isinstance(metrics, Mapping) else {},
        "benchmark": scorecard.get("benchmark"),
        "holdout_window": dict(holdout) if isinstance(holdout, Mapping) else {},
        "out_of_sample_protocol_summary": {
            "labeled_eval_set": proto.get("labeled_eval_set"),
            "labeled_eval_limitation": proto.get("labeled_eval_limitation"),
            "unsupervised_eval_set": proto.get("unsupervised_eval_set"),
            "leakage_isolation": proto.get("leakage_isolation"),
            "seasonal_confound_fix": proto.get("seasonal_confound_fix"),
        },
        "leakage": (scorecard.get("safety", {}) or {}).get("governance", {}).get(
            "holdout_isolation"
        ),
        "raw_march_flag_rates": scorecard.get("raw_march_flag_rates"),
    }


def _read_pillar_b(scorecard: Mapping[str, Any]) -> dict[str, Any]:
    verdict = str(scorecard.get("verdict", "UNKNOWN")).upper()
    gate = scorecard.get("acceptance_gate", {}) or {}
    holdout = scorecard.get("holdout_window") or {}
    proto = scorecard.get("out_of_sample_protocol") or {}
    return {
        "verdict": verdict,
        "frozen_gate": scorecard.get("frozen_gate"),
        "gate_version": (gate.get("frozen_gate_version") if isinstance(gate, Mapping) else None)
        or (scorecard.get("frozen_gate") or {}).get("gate_version"),
        "rule": gate.get("rule"),
        "criteria": gate.get("criteria"),
        "coverage_waterfall": scorecard.get("coverage_waterfall"),
        "coverage_explanation": scorecard.get("coverage_explanation"),
        "opportunity": scorecard.get("opportunity"),
        "mvpv1_comparison": scorecard.get("mvpv1_comparison"),
        "leakage_check": scorecard.get("leakage_check"),
        "out_of_sample_protocol_summary": {
            "description": proto.get("description"),
            "honest_limitations": proto.get("honest_limitations"),
            "pre_registration": proto.get("pre_registration"),
        },
        "holdout_window": dict(holdout) if isinstance(holdout, Mapping) else {},
    }


def _product_status_line(a_verdict: str, b_verdict: str) -> str:
    """Honest one-liner reflecting BOTH pillars' verdicts truthfully."""
    a_v = a_verdict.upper()
    b_v = b_verdict.upper()
    if a_v == "PASS" and b_v == "PASS":
        return "Pillar A validated; Pillar B validated. Advisory evidence only; deployment NOT authorized in this version."
    if a_v == "PASS" and b_v == "FAIL":
        return "Pillar A validated; Pillar B FAILED its locked-March acceptance gate (honest result). Advisory evidence only; deployment NOT authorized in this version."
    if a_v == "FAIL" and b_v == "PASS":
        return "Pillar A FAILED its locked-March acceptance gate (honest result); Pillar B validated. Advisory evidence only; deployment NOT authorized in this version."
    if a_v == "FAIL" and b_v == "FAIL":
        return "Pillar A FAILED and Pillar B FAILED on the locked-March holdout (honest dual-FAIL result). No deployment claim; preserve evidence; consider data remediation, scope reduction, or stop/pause per PRD §10.5."
    return f"Pillar A: {a_v}; Pillar B: {b_v}. Advisory evidence only; deployment NOT authorized in this version."


# --------------------------------------------------------------------------- #
# Safety / governance checks for THIS package
# --------------------------------------------------------------------------- #
def _govern_modeling_source(repo_root: Path) -> GovernanceScanResult:
    """Scan the advisory + training + models + dataio source for forbidden tokens.

    Mirrors the Sprint 30b governance scan but rooted at the Sprint 34 working
    directory (not the original sprint30b path baked into the upstream
    scorecard JSON). This is what makes the Sprint 34 packaging-gate scan
    honestly current."""
    roots = [
        repo_root / "src" / "aquaoptima" / "advisory",
        repo_root / "src" / "aquaoptima" / "training",
        repo_root / "src" / "aquaoptima" / "models",
        repo_root / "src" / "aquaoptima" / "dataio",
    ]
    existing = [r for r in roots if r.exists()]
    return scan_modeling_source_for_governance_violations(existing)


# --------------------------------------------------------------------------- #
# Exports
# --------------------------------------------------------------------------- #
def build_health_event_export(pillar_a_scorecard: Mapping[str, Any]) -> dict[str, Any]:
    """Build the portable Pillar-A injected-fault / flagged-event evidence.

    Returns a dict with two keys: ``metadata`` (advisory-only banner, schema
    note, source attribution) and ``events`` (a list of per-episode rows).
    """
    injected = pillar_a_scorecard.get("injected_faults", {}) or {}
    episodes_in: Sequence[Mapping[str, Any]] = injected.get("episodes", []) or []
    eval_block = pillar_a_scorecard.get("evaluation", {}) or {}
    det = eval_block.get("detector", {}) or {}
    base = eval_block.get("baseline", {}) or {}
    det_per_ep: Sequence[Mapping[str, Any]] = (
        (det.get("lead_time_summary") or {}).get("per_episode") or []
    )
    base_per_ep: Sequence[Mapping[str, Any]] = (
        (base.get("lead_time_summary") or {}).get("per_episode") or []
    )

    # Index per-episode detection by onset_index for stable join.
    by_onset_det = {int(r.get("onset_index", -1)): r for r in det_per_ep}
    by_onset_base = {int(r.get("onset_index", -1)): r for r in base_per_ep}

    events: list[dict[str, Any]] = []
    for ep in episodes_in:
        onset = int(ep.get("onset_index", -1))
        d = by_onset_det.get(onset, {})
        b = by_onset_base.get(onset, {})
        events.append({
            "onset_index": onset,
            "end_index": int(ep.get("end_index", -1)),
            "kind": ep.get("kind"),
            "axis": ep.get("axis"),
            "length_rows": int(ep.get("length", 0)),
            "magnitude_sigmas": float(ep.get("magnitude_sigmas", 0.0)),
            "detector_detected": bool(d.get("detected", False)),
            "detector_lead_time_rows": d.get("lead_time"),
            "baseline_detected": bool(b.get("detected", False)),
            "baseline_lead_time_rows": b.get("lead_time"),
            "advisory_only": True,
            "is_evidence_not_setpoint": True,
        })

    return {
        "metadata": {
            "pillar": "A_health",
            "schema": "sprint34.health_event_export.v1",
            "safety_banner": SAFETY_BANNER,
            "advisory_only": True,
            "evaluation_mode": "offline_only",
            "is_evidence_not_setpoint": True,
            "label_regime": "synthetic_injected_faults_on_real_march2026_normal_frames",
            "cannot_claim": list(CANNOT_CLAIM_STATEMENTS),
            "source_scorecard": "data/eval/pillarA/sprint30b_fullyear_holdout_scorecard.json",
            "holdout_window": pillar_a_scorecard.get("holdout_window"),
            "n_episodes": len(events),
        },
        "events": events,
    }


def health_event_export_to_csv(export: Mapping[str, Any]) -> str:
    """Render the health-event export as a CSV string with a banner header."""
    events: Sequence[Mapping[str, Any]] = export.get("events", []) or []
    columns = [
        "onset_index",
        "end_index",
        "kind",
        "axis",
        "length_rows",
        "magnitude_sigmas",
        "detector_detected",
        "detector_lead_time_rows",
        "baseline_detected",
        "baseline_lead_time_rows",
        "advisory_only",
        "is_evidence_not_setpoint",
    ]
    buf = io.StringIO()
    # Banner as a comment line so the CSV remains machine-readable.
    buf.write(f"# {SAFETY_BANNER}\n")
    buf.write("# schema=sprint34.health_event_export.v1\n")
    buf.write("# advisory_only=true; evaluation_mode=offline_only\n")
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    for row in events:
        writer.writerow({k: row.get(k) for k in columns})
    return buf.getvalue()


def build_efficiency_advisory_export(
    pillar_b_scorecard: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the portable Pillar-B counterfactual advisory evidence.

    Only intervals marked supported in the scorecard's ``samples.supported_head``
    are emitted as numeric rows. Unsupported intervals are NEVER emitted as
    advisory rows; their count is recorded in the metadata block so a
    reviewer can see the rejection volume.
    """
    samples = pillar_b_scorecard.get("samples", {}) or {}
    supported_head: Sequence[Mapping[str, Any]] = samples.get("supported_head") or []
    unsupported_head: Sequence[Mapping[str, Any]] = samples.get("unsupported_head") or []
    waterfall = pillar_b_scorecard.get("coverage_waterfall", {}) or {}

    rows: list[dict[str, Any]] = []
    for s in supported_head:
        q = s.get("query") or {}
        rows.append({
            "window_start": s.get("window_start"),
            "window_end": s.get("window_end"),
            "window_minutes": s.get("window_minutes"),
            "supported": True,
            "comparable_count": s.get("comparable_count"),
            "demand_m3_per_h": q.get("demand_m3_per_h"),
            "level_m": q.get("level_m"),
            "pressure_m_head": q.get("pressure_m_head"),
            "flow_m3_per_h": q.get("flow_m3_per_h"),
            "observed_specific_energy_kwh_per_m3": s.get(
                "observed_specific_energy_kwh_per_m3"
            ),
            "observed_efficient_speed_min_hz": s.get("observed_efficient_speed_min_hz"),
            "observed_efficient_speed_max_hz": s.get("observed_efficient_speed_max_hz"),
            "se_p25": s.get("se_p25"),
            "se_p10": s.get("se_p10"),
            "counterfactual_energy_kwh_p25": s.get("counterfactual_energy_kwh_p25"),
            "counterfactual_energy_kwh_p10": s.get("counterfactual_energy_kwh_p10"),
            "opportunity_kwh_p25": s.get("opportunity_kwh_p25"),
            "opportunity_kwh_p10": s.get("opportunity_kwh_p10"),
            "advisory_only": True,
            "is_evidence_not_setpoint": True,
        })

    return {
        "metadata": {
            "pillar": "B_efficiency",
            "schema": "sprint34.efficiency_advisory_export.v1",
            "safety_banner": SAFETY_BANNER,
            "advisory_only": True,
            "evaluation_mode": "offline_only",
            "is_evidence_not_setpoint": True,
            "claim_discipline": "counterfactual_offline_opportunity_on_supported_intervals_only",
            "cannot_claim": list(CANNOT_CLAIM_STATEMENTS),
            "allowed_language": list(ALLOWED_PILLAR_B_LANGUAGE),
            "source_scorecard": "data/eval/pillarB/sprint33_locked_march_scorecard.json",
            "holdout_window": pillar_b_scorecard.get("holdout_window"),
            "coverage_waterfall": dict(waterfall),
            "frozen_gate_sha256": (
                pillar_b_scorecard.get("frozen_gate") or {}
            ).get("gate_file_sha256_at_eval"),
            "n_supported_advisories": len(rows),
            "n_unsupported_intervals_excluded": int(waterfall.get("unsupported", 0) or 0),
            "n_unsupported_head_samples_preserved": len(unsupported_head),
        },
        "advisories": rows,
    }


def efficiency_advisory_export_to_csv(export: Mapping[str, Any]) -> str:
    """Render the advisory export as a CSV string with a banner header."""
    rows: Sequence[Mapping[str, Any]] = export.get("advisories", []) or []
    columns = [
        "window_start",
        "window_end",
        "window_minutes",
        "supported",
        "comparable_count",
        "demand_m3_per_h",
        "level_m",
        "pressure_m_head",
        "flow_m3_per_h",
        "observed_specific_energy_kwh_per_m3",
        "observed_efficient_speed_min_hz",
        "observed_efficient_speed_max_hz",
        "se_p25",
        "se_p10",
        "counterfactual_energy_kwh_p25",
        "counterfactual_energy_kwh_p10",
        "opportunity_kwh_p25",
        "opportunity_kwh_p10",
        "advisory_only",
        "is_evidence_not_setpoint",
    ]
    buf = io.StringIO()
    buf.write(f"# {SAFETY_BANNER}\n")
    buf.write("# schema=sprint34.efficiency_advisory_export.v1\n")
    buf.write("# advisory_only=true; evaluation_mode=offline_only\n")
    buf.write("# claim_discipline=counterfactual_offline_opportunity_on_supported_intervals_only\n")
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k) for k in columns})
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Artifact manifest (contracts-SDK ModelArtifactRecord shape)
# --------------------------------------------------------------------------- #
def _checksum_pair(path: Path | None) -> tuple[str, int]:
    """Return (sha256_hex, size_bytes) for a real file; for a missing file
    return the sha256 of the empty byte string and zero size.

    This is the right behaviour for Sprint 34: there is NO ONNX export in
    this sprint, so the artifact records refer to evidence (scorecards) that
    DO exist on disk, never to model-weight blobs that don't."""
    if path is None or not path.is_file():
        return hashlib.sha256(b"").hexdigest(), 0
    return _file_sha256(path)


def build_artifact_manifest_records(
    *,
    repo_root: Path,
    pillar_a_scorecard_path: Path,
    pillar_b_scorecard_path: Path,
    pillar_a_verdict: str,
    pillar_b_verdict: str,
    build_id: str = "sprint34-unified-ab",
) -> list[ModelArtifactRecord]:
    """Build the two ModelArtifactRecords (one per pillar).

    Each record wraps the upstream pillar SCORECARD JSON as the audit
    artifact (NOT a model-weights blob, which we deliberately do not export
    in this sprint). The artifact reference's checksum is the real sha256
    of the scorecard file. The safety flag set is the canonical all-True
    set; the framework is ``onnx`` (the AMAX edge profile's advertised
    framework — we are recording an artifact REFERENCE, not exporting one).
    """
    a_hex, a_size = _checksum_pair(pillar_a_scorecard_path)
    b_hex, b_size = _checksum_pair(pillar_b_scorecard_path)

    a_record = build_health_artifact_record(
        model_id="yilan-health-detector-sprint30b",
        model_version="0.1.0",
        checksum_hex=a_hex,
        checksum_size_bytes=a_size,
        producer_component="ai_server",
        producer_version="0.1.0",
        build_id=build_id,
        artifact_uri_id="sprint30b_fullyear_holdout_scorecard.json",
        parameter_count=0,
        summary_extra={
            "sprint": "30b",
            "verdict": str(pillar_a_verdict).upper(),
            "safety_banner": SAFETY_BANNER,
            "artifact_kind": "evidence_scorecard_only_no_weights",
            "edge_export": "BLOCKED_in_sprint34",
        },
    )
    b_record = build_efficiency_artifact_record(
        model_id="yilan-efficiency-envelope-sprint32",
        model_version="0.1.0",
        checksum_hex=b_hex,
        checksum_size_bytes=b_size,
        producer_component="ai_server",
        producer_version="0.1.0",
        build_id=build_id,
        artifact_uri_id="sprint33_locked_march_scorecard.json",
        parameter_count=0,
        summary_extra={
            "sprint": "33",
            "verdict": str(pillar_b_verdict).upper(),
            "safety_banner": SAFETY_BANNER,
            "artifact_kind": "evidence_scorecard_only_no_weights",
            "edge_export": "BLOCKED_in_sprint34",
        },
    )
    return [a_record, b_record]


def build_artifact_manifest_json(
    records: Sequence[ModelArtifactRecord],
    *,
    governance: GovernanceScanResult,
) -> dict[str, Any]:
    """Wrap the records into a JSON-serialisable manifest with banner metadata."""
    return {
        "schema": "sprint34.artifact_manifest.v1",
        "sprint": SPRINT,
        "safety_banner": SAFETY_BANNER,
        "advisory_only": True,
        "evaluation_mode": "offline_only",
        "edge_export": "BLOCKED",
        "site_integration_allowed": False,
        "governance_scan": {
            "clean": bool(governance.clean),
            "files_scanned": int(governance.files_scanned),
            "violations": list(governance.violations),
            "safety_status": governance.safety_status,
        },
        "records": [r.to_dict() for r in records],
        "cannot_claim": list(CANNOT_CLAIM_STATEMENTS),
        "packaging_blocks": dict(PACKAGING_BLOCKS),
    }


# --------------------------------------------------------------------------- #
# Unified scorecard
# --------------------------------------------------------------------------- #
def _packaging_gate(
    *,
    governance: GovernanceScanResult,
    dashboard_html: str,
    package_surfaces: Sequence[tuple[str, str]],
    report_surfaces: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    """Apply the Sprint 34 packaging acceptance gate.

    Sprint 34 PASS iff ALL hold:
      P1. Banner appears in every surface (scorecard, dashboard, every report,
          every export metadata).
      P2. No control endpoint or UI control that SETS anything exists in the
          dashboard HTML (no <form>, <input>, <button>, no method=post, no
          onclick/onsubmit handler).
      P3. Leakage / safety governance scan over the modeling source is clean
          (no forbidden edge import, no write-connector token).
      P4. Reports include the explicit cannot-claim statements. (Tabular
          exports -- CSVs -- carry the banner and an advisory-only flag, but
          the prose cannot-claim block lives in the prose reports.)
      P5. Edge / site / control packaging remains blocked (no onnx export, no
          edge import).
    """
    # P1: every surface contains the banner verbatim.
    missing_banner = [name for (name, text) in package_surfaces if SAFETY_BANNER not in text]
    p1 = not missing_banner

    # P2: dashboard HTML contains nothing that posts or sets.
    controls = _dashboard_control_tokens(dashboard_html)
    p2 = not controls

    # P3: modeling source is clean.
    p3 = bool(governance.clean)

    # P4: every prose report surface contains every cannot-claim line.
    missing_cannot_claim: list[tuple[str, str]] = []
    for name, text in report_surfaces:
        for claim in CANNOT_CLAIM_STATEMENTS:
            if claim not in text:
                missing_cannot_claim.append((name, claim))
                break
    p4 = not missing_cannot_claim

    # P5: blocked surfaces are still blocked. The packager never produces an
    # ONNX export and never imports the edge SDK; we assert that by repeating
    # the negative inventory in PACKAGING_BLOCKS and checking it against the
    # governance scan's import_connector findings.
    p5 = bool(governance.clean)

    criteria = [
        {
            "name": "safety_banner_on_every_surface",
            "passed": bool(p1),
            "detail": {
                "n_surfaces": len(package_surfaces),
                "missing_banner_surfaces": missing_banner,
            },
        },
        {
            "name": "no_control_endpoint_or_ui_control_in_dashboard",
            "passed": bool(p2),
            "detail": {
                "forbidden_html_tokens_found": controls,
            },
        },
        {
            "name": "leakage_and_safety_checks_pass",
            "passed": bool(p3),
            "detail": {
                "files_scanned": int(governance.files_scanned),
                "violations": list(governance.violations),
            },
        },
        {
            "name": "reports_include_cannot_claim_statements",
            "passed": bool(p4),
            "detail": {
                "missing": missing_cannot_claim,
                "expected_cannot_claim": list(CANNOT_CLAIM_STATEMENTS),
            },
        },
        {
            "name": "edge_site_control_packaging_remains_blocked",
            "passed": bool(p5),
            "detail": dict(PACKAGING_BLOCKS),
        },
    ]
    passed = all(c["passed"] for c in criteria)
    return {
        "report_version": REPORT_VERSION,
        "verdict": "PASS" if passed else "FAIL",
        "passed": bool(passed),
        "rule": (
            "Sprint 34 packaging PASS iff: safety_banner_on_every_surface AND "
            "no_control_endpoint_or_ui_control_in_dashboard AND "
            "leakage_and_safety_checks_pass AND "
            "reports_include_cannot_claim_statements AND "
            "edge_site_control_packaging_remains_blocked."
        ),
        "criteria": criteria,
    }


# Tokens in HTML that would indicate a control that SETS something on the
# server / a remote system, or that posts a value. These are checked
# case-insensitively. Plain ``<a href>`` anchors and read-only ``<details>``
# are NOT in this list -- they don't set anything.
_FORBIDDEN_DASHBOARD_HTML_TOKENS: tuple[str, ...] = (
    "<form",
    "<input",
    "<button",
    "<textarea",
    "<select",
    "method=\"post\"",
    "method='post'",
    "method=post",
    "onclick=",
    "onsubmit=",
    "onchange=",
    "fetch(",
    "xmlhttprequest",
    "websocket",
    "<script",
)


def _dashboard_control_tokens(html: str) -> list[str]:
    low = html.lower()
    found = [tok for tok in _FORBIDDEN_DASHBOARD_HTML_TOKENS if tok in low]
    return found


# --------------------------------------------------------------------------- #
# Dashboard HTML (static, read-only, no controls that set anything)
# --------------------------------------------------------------------------- #
def _esc(text: Any) -> str:
    """Minimal HTML escaper for user-facing values."""
    s = "" if text is None else str(text)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_dashboard_html(
    *,
    product_status: str,
    pillar_a: Mapping[str, Any],
    pillar_b: Mapping[str, Any],
    health_export: Mapping[str, Any],
    advisory_export: Mapping[str, Any],
    generated_at_utc: str,
) -> str:
    """Render the static read-only dashboard HTML.

    No <form>, no <input>, no <button>, no <script>, no fetch / XHR. Every
    interactive affordance is read-only: links to evidence files, <details>
    blocks that collapse text. The persistent banner is in the header AND
    repeated as a banner DIV inside every section.
    """
    a_metrics = pillar_a.get("metrics") or {}
    b_opp = pillar_b.get("opportunity") or {}
    b_water = pillar_b.get("coverage_waterfall") or {}
    a_v = _esc(pillar_a.get("verdict"))
    b_v = _esc(pillar_b.get("verdict"))

    cannot_claim_html = "".join(
        f"<li>{_esc(line)}</li>" for line in CANNOT_CLAIM_STATEMENTS
    )

    a_metric_rows = "".join(
        f"<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>"
        for k, v in sorted(a_metrics.items())
    )

    b_metric_rows = (
        f"<tr><td>kwh_p25 (conservative)</td><td>{_esc(b_opp.get('kwh_p25'))}</td></tr>"
        f"<tr><td>kwh_p10 (aggressive)</td><td>{_esc(b_opp.get('kwh_p10'))}</td></tr>"
        f"<tr><td>n_supported_intervals</td><td>{_esc(b_opp.get('n_supported_intervals'))}</td></tr>"
        f"<tr><td>robust_under_conservative</td>"
        f"<td>{_esc(b_opp.get('robust_under_conservative'))}</td></tr>"
        f"<tr><td>march_observed_energy_kwh (supported)</td>"
        f"<td>{_esc(b_opp.get('march_observed_energy_kwh_supported'))}</td></tr>"
        f"<tr><td>march_volume_m3 (supported)</td>"
        f"<td>{_esc(b_opp.get('march_volume_m3_supported'))}</td></tr>"
    )

    waterfall_rows = "".join(
        f"<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>"
        for k, v in [
            ("total", b_water.get("total")),
            ("valid", b_water.get("valid")),
            ("supported", b_water.get("supported")),
            ("unsupported", b_water.get("unsupported")),
        ]
    )

    n_episodes = len((health_export.get("events") or []))
    n_advisories = len((advisory_export.get("advisories") or []))

    # NOTE: this template contains NO <script>, NO <form>, NO <input>, NO
    # <button>, NO event-handler attributes. It is intentionally STATIC. The
    # safety banner appears at top-of-page and again inside each section.
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>AOPSO Sprint 34 - Unified A+B Offline Evidence</title>
<style>
body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 1100px;
  margin: 1em auto; padding: 0 1em; color: #222; line-height: 1.45; }}
h1, h2, h3 {{ color: #1a1a1a; }}
.banner {{ background: #fff3cd; border: 2px solid #b58900; color: #5a3e00;
  padding: 0.75em 1em; margin: 0.75em 0; font-weight: 700; }}
.verdict-pass {{ background: #d4edda; color: #155724; padding: 0.25em 0.5em;
  border-radius: 4px; font-weight: 700; }}
.verdict-fail {{ background: #f8d7da; color: #721c24; padding: 0.25em 0.5em;
  border-radius: 4px; font-weight: 700; }}
table {{ border-collapse: collapse; margin: 0.5em 0; }}
td, th {{ padding: 0.25em 0.75em; border-bottom: 1px solid #ddd; vertical-align: top; }}
section {{ border-top: 1px solid #ccc; padding-top: 1em; margin-top: 1.5em; }}
ul.cannot-claim li {{ color: #721c24; }}
code {{ background: #f5f5f5; padding: 0.1em 0.3em; border-radius: 3px; }}
.meta {{ color: #555; font-size: 0.9em; }}
</style>
</head>
<body>
<div class="banner">{_esc(SAFETY_BANNER)}</div>
<h1>AOPSO Sprint 34 - Unified A+B Offline Evidence</h1>
<p class="meta">Generated: <code>{_esc(generated_at_utc)}</code> &middot;
  Report version: <code>{_esc(REPORT_VERSION)}</code></p>
<p><strong>Product status:</strong> {_esc(product_status)}</p>

<section>
<div class="banner">{_esc(SAFETY_BANNER)}</div>
<h2>Pillar A - Health / Anomaly Detection</h2>
<p>Verdict:
<span class="{'verdict-pass' if a_v == 'PASS' else 'verdict-fail'}">{a_v}</span>
&middot; Benchmark: <em>{_esc(pillar_a.get("benchmark"))}</em>
</p>
<p>Holdout: <code>{_esc((pillar_a.get('holdout_window') or {}).get('first_timestamp'))}</code>
to <code>{_esc((pillar_a.get('holdout_window') or {}).get('last_timestamp'))}</code>
(<code>{_esc((pillar_a.get('holdout_window') or {}).get('n_rows'))}</code> rows).
</p>
<table>
<tr><th>Metric</th><th>Value</th></tr>
{a_metric_rows}
</table>
<p>Evidence: <code>data/eval/unified/health_event_export.csv</code>
&middot; <code>data/eval/unified/health_event_export.json</code>
(<strong>{n_episodes}</strong> injected-fault episodes; advisory-only evidence).</p>
</section>

<section>
<div class="banner">{_esc(SAFETY_BANNER)}</div>
<h2>Pillar B - Efficiency / Counterfactual Opportunity</h2>
<p>Verdict:
<span class="{'verdict-pass' if b_v == 'PASS' else 'verdict-fail'}">{b_v}</span>
&middot; Frozen gate: <code>{_esc(pillar_b.get("gate_version"))}</code>
</p>
<p>Holdout: <code>{_esc((pillar_b.get('holdout_window') or {}).get('first_timestamp'))}</code>
to <code>{_esc((pillar_b.get('holdout_window') or {}).get('last_timestamp'))}</code>
(<code>{_esc((pillar_b.get('holdout_window') or {}).get('n_rows'))}</code> rows,
<code>{_esc((pillar_b.get('holdout_window') or {}).get('n_operating_points'))}</code>
OperatingPoints).</p>
<h3>Coverage waterfall</h3>
<table>
<tr><th>Bucket</th><th>Intervals</th></tr>
{waterfall_rows}
</table>
<h3>Opportunity (counterfactual, supported intervals only)</h3>
<table>
<tr><th>Metric</th><th>Value</th></tr>
{b_metric_rows}
</table>
<p><em>{_esc(pillar_b.get('coverage_explanation'))}</em></p>
<p>Evidence: <code>data/eval/unified/efficiency_advisory_export.csv</code>
&middot; <code>data/eval/unified/efficiency_advisory_export.json</code>
(<strong>{n_advisories}</strong> supported advisories; advisory-only evidence).</p>
</section>

<section>
<div class="banner">{_esc(SAFETY_BANNER)}</div>
<h2>Cannot-Claim Statements</h2>
<ul class="cannot-claim">
{cannot_claim_html}
</ul>
</section>

<section>
<div class="banner">{_esc(SAFETY_BANNER)}</div>
<h2>Packaging boundary</h2>
<table>
<tr><th>Surface</th><th>Status</th></tr>
{''.join(f'<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>' for k, v in PACKAGING_BLOCKS.items())}
</table>
</section>

</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Reports (Markdown)
# --------------------------------------------------------------------------- #
def render_executive_report(
    *,
    product_status: str,
    pillar_a: Mapping[str, Any],
    pillar_b: Mapping[str, Any],
    generated_at_utc: str,
) -> str:
    """Plant-manager-readable executive report (Markdown)."""
    a_metrics = pillar_a.get("metrics") or {}
    b_opp = pillar_b.get("opportunity") or {}
    b_water = pillar_b.get("coverage_waterfall") or {}

    cannot_claim_md = "\n".join(f"- {line}" for line in CANNOT_CLAIM_STATEMENTS)
    allowed_lang_md = "\n".join(f"- {line}" for line in ALLOWED_PILLAR_B_LANGUAGE)

    return f"""# AOPSO Sprint 34 - Unified A+B Executive Report

> **SAFETY:** {SAFETY_BANNER}

Generated (UTC): `{generated_at_utc}`
Report version: `{REPORT_VERSION}`

## What this product does

AquaOptima Pump Station Optimizer Lite is an **offline advisory evidence
product**. It evaluates two independent pillars on a locked, out-of-sample
March 2026 holdout from the Yilan site, and emits a unified evidence
bundle for review.

- **Pillar A** (Health / Anomaly Detection): observe how an anomaly
  detector responds to canonical injected faults overlaid on real,
  unseen March 2026 normal-mode telemetry.
- **Pillar B** (Efficiency / Counterfactual Opportunity): score real
  March 2026 OperatingPoints against a 2025-derived matched-condition
  efficient envelope, and report only the **counterfactual offline
  opportunity** on supported intervals.

## Product status

**{product_status}**

## What each pillar proved on the locked holdout

### Pillar A - verdict: **{pillar_a.get("verdict")}**

- Benchmark: {pillar_a.get("benchmark")}
- Gate: `{pillar_a.get("gate_version")}` (pre-registered v2 product-grounded
  gate; rule: {pillar_a.get("rule")})
- Detector AUROC: `{a_metrics.get("detector_auroc")}` vs baseline
  `{a_metrics.get("baseline_auroc")}`
- Detector false-alarm rate: `{a_metrics.get("detector_false_alarm_rate")}`
  vs baseline `{a_metrics.get("baseline_false_alarm_rate")}`
- Detector mean lead-time: `{a_metrics.get("detector_mean_lead_time")}` rows
  vs baseline `{a_metrics.get("baseline_mean_lead_time")}` rows
- Holdout window: `{(pillar_a.get('holdout_window') or {}).get('first_timestamp')}`
  to `{(pillar_a.get('holdout_window') or {}).get('last_timestamp')}`

### Pillar B - verdict: **{pillar_b.get("verdict")}**

- Frozen gate: `{pillar_b.get("gate_version")}` (rule:
  {pillar_b.get("rule")})
- Coverage waterfall: total=`{b_water.get('total')}`,
  valid=`{b_water.get('valid')}`, supported=`{b_water.get('supported')}`,
  unsupported=`{b_water.get('unsupported')}`
- Counterfactual opportunity on supported intervals:
  p25=`{b_opp.get('kwh_p25')}` kWh, p10=`{b_opp.get('kwh_p10')}` kWh
- Robust under conservative quantile?
  `{b_opp.get('robust_under_conservative')}`
- March-observed energy on supported intervals:
  `{b_opp.get('march_observed_energy_kwh_supported')}` kWh
- Holdout window: `{(pillar_b.get('holdout_window') or {}).get('first_timestamp')}`
  to `{(pillar_b.get('holdout_window') or {}).get('last_timestamp')}`

> {pillar_b.get('coverage_explanation')}

## Honest limitations

- Pillar A injected faults are SYNTHETIC. AUROC / lead-time / false-alarm
  measure how the 2025-fit detector responds to canonical faults on top of
  unseen March 2026 normal data. They do **not** measure how the detector
  would score real March faults (March 2026 has no ground-truth labels).
- Pillar B reports a **counterfactual offline opportunity** only, on
  intervals with sufficient historical neighbours under the FROZEN
  matching tolerances. Realising the opportunity in operation would
  require future operational validation under the same hydraulic
  constraints.
- Unsupported intervals (insufficient historical neighbours, or no
  efficient sub-bucket) carry **zero** claim by construction.
- MVPv1 control-log comparison is produced only where the FROZEN
  alignment diagnostic passes; otherwise the comparison is marked **not
  available**, never approximated.
- Offline only. **No setpoints, no actuation, no live integration, no
  site write path of any kind.**

## Cannot claim

{cannot_claim_md}

## Allowed Pillar-B language (verbatim)

{allowed_lang_md}

## What this report is, and is not

- This is an **offline evidence report**. It is **not** a deployment
  artifact, a control policy, an operating procedure, or a maintenance
  schedule.
- This report does **not** unblock edge deployment or control
  integration.
- A future, separate qualification would be required to authorize any
  deployment discussion. See PRD §9 packaging-unblock policy.
"""


def render_plant_manager_summary(
    *,
    product_status: str,
    pillar_a: Mapping[str, Any],
    pillar_b: Mapping[str, Any],
) -> str:
    """One-page plant-manager summary (Markdown)."""
    a_metrics = pillar_a.get("metrics") or {}
    b_opp = pillar_b.get("opportunity") or {}
    b_water = pillar_b.get("coverage_waterfall") or {}
    cannot_claim_md = "\n".join(f"- {line}" for line in CANNOT_CLAIM_STATEMENTS)

    return f"""# AOPSO Sprint 34 - One-Page Plant-Manager Summary

> **SAFETY:** {SAFETY_BANNER}

## Product status

**{product_status}**

## Pillar A - Health detection (Sprint 30b verdict: {pillar_a.get("verdict")})

- AUROC: detector `{a_metrics.get("detector_auroc")}` vs baseline `{a_metrics.get("baseline_auroc")}`
- False-alarm rate: detector `{a_metrics.get("detector_false_alarm_rate")}` vs baseline `{a_metrics.get("baseline_false_alarm_rate")}`
- Mean lead-time (rows): detector `{a_metrics.get("detector_mean_lead_time")}` vs baseline `{a_metrics.get("baseline_mean_lead_time")}`

## Pillar B - Efficiency advisory (Sprint 33 verdict: {pillar_b.get("verdict")})

- Coverage: `{b_water.get('supported')}` supported / `{b_water.get('total')}` total OperatingPoints
- Counterfactual opportunity (supported intervals only): p25 = `{b_opp.get('kwh_p25')}` kWh, p10 = `{b_opp.get('kwh_p10')}` kWh
- Robust under conservative p25 quantile? `{b_opp.get('robust_under_conservative')}`
- March-observed energy on supported intervals: `{b_opp.get('march_observed_energy_kwh_supported')}` kWh

## What we **cannot** claim

{cannot_claim_md}

## Next step

This is offline evidence only. Any operational change requires future
validation under the same hydraulic constraints and a separate
qualification step. Site integration, actuation, and write-path
deployment are **not authorized** in this version.
"""


def render_ml_audit_appendix(
    *,
    pillar_a: Mapping[str, Any],
    pillar_b: Mapping[str, Any],
    pillar_a_scorecard: Mapping[str, Any],
    pillar_b_scorecard: Mapping[str, Any],
    governance: GovernanceScanResult,
    generated_at_utc: str,
) -> str:
    """ML audit appendix (Markdown). Full honest methodology."""
    cannot_claim_md = "\n".join(f"- {line}" for line in CANNOT_CLAIM_STATEMENTS)
    frozen_a = pillar_a_scorecard.get("frozen_gate_v2") or {}
    frozen_b = pillar_b_scorecard.get("frozen_gate") or {}

    return f"""# AOPSO Sprint 34 - ML Audit Appendix

> **SAFETY:** {SAFETY_BANNER}

Generated (UTC): `{generated_at_utc}`
Report version: `{REPORT_VERSION}`

## 1. Methodology overview

The Sprint 34 unified package is an OFFLINE EVIDENCE bundle assembled
from two independent pillar evaluations, each pre-registered against a
locked March 2026 holdout from the Yilan site:

- **Pillar A** (Sprint 30b): full-year-2025 stratified fit + locked
  March 2026 evaluation under pre-registered acceptance gate v2.
- **Pillar B** (Sprint 33): locked March 2026 scored against a frozen
  matched-condition efficient envelope built from 2025 OperatingPoints,
  under a pre-registered Sprint-32 frozen gate.

No model retraining, no parameter tuning, and no fresh data ingestion
were performed in this sprint. The pre-existing pillar artefacts were
loaded and projected into the unified package format.

## 2. Pre-registration & frozen gates

### Pillar A (gate v2)

| Key | Value |
|---|---|
| gate_version | `{frozen_a.get('imported_from') or 'health_acceptance_gate_v2'}` |
| auroc_noninferiority_tol | `{frozen_a.get('auroc_noninferiority_tol')}` |
| far_improvement_factor | `{frozen_a.get('far_improvement_factor')}` |
| min_detector_auroc | `{frozen_a.get('min_detector_auroc')}` |
| lead_time_tol | `{frozen_a.get('lead_time_tol')}` |
| preregistered_before_evaluation | `{frozen_a.get('preregistered_before_evaluation')}` |
| tuned_to_outcome | `{frozen_a.get('tuned_to_outcome')}` |
| rule | `{frozen_a.get('rule_text')}` |

### Pillar B (Sprint-32 envelope, locked at Sprint 33 eval)

| Key | Value |
|---|---|
| gate_version | `{frozen_b.get('gate_version')}` |
| gate_file_sha256_at_eval | `{frozen_b.get('gate_file_sha256_at_eval')}` |
| gate_file_sha256_post_eval | `{frozen_b.get('gate_file_sha256_post_eval')}` |
| pre_eq_post | `{frozen_b.get('pre_eq_post')}` |
| frozen_params_sha256 | `{frozen_b.get('frozen_params_sha256')}` |
| march_used_for_tuning | `{frozen_b.get('march_used_for_tuning')}` |
| se_quantiles | `{frozen_b.get('se_quantiles')}` |
| matching_tolerances | `{frozen_b.get('matching_tolerances')}` |
| min_support | `{frozen_b.get('min_support')}` |

## 3. Holdout protocol

### Pillar A

- Holdout window: `{(pillar_a.get('holdout_window') or {}).get('first_timestamp')}`
  to `{(pillar_a.get('holdout_window') or {}).get('last_timestamp')}`,
  `{(pillar_a.get('holdout_window') or {}).get('n_rows')}` rows.
- Labeled eval set: {pillar_a.get('out_of_sample_protocol_summary', {}).get('labeled_eval_set')}
- Labeled eval limitation: {pillar_a.get('out_of_sample_protocol_summary', {}).get('labeled_eval_limitation')}
- Unsupervised eval set: {pillar_a.get('out_of_sample_protocol_summary', {}).get('unsupervised_eval_set')}
- Leakage isolation: {pillar_a.get('out_of_sample_protocol_summary', {}).get('leakage_isolation')}
- Seasonal-confound fix: {pillar_a.get('out_of_sample_protocol_summary', {}).get('seasonal_confound_fix')}

### Pillar B

- Holdout window: `{(pillar_b.get('holdout_window') or {}).get('first_timestamp')}`
  to `{(pillar_b.get('holdout_window') or {}).get('last_timestamp')}`,
  `{(pillar_b.get('holdout_window') or {}).get('n_rows')}` rows,
  `{(pillar_b.get('holdout_window') or {}).get('n_operating_points')}`
  OperatingPoints.
- {pillar_b.get('out_of_sample_protocol_summary', {}).get('description')}
- Pre-registration: {pillar_b.get('out_of_sample_protocol_summary', {}).get('pre_registration')}

## 4. Honest limitations

### Pillar A
- Synthetic injected faults; no real March-2026 fault labels exist.
- AUROC / lead-time / false-alarm measure response to canonical faults
  overlaid on unseen normal data, not real fault recall.

### Pillar B

{chr(10).join(f"- {line}" for line in (pillar_b.get('out_of_sample_protocol_summary', {}).get('honest_limitations') or []))}

## 5. Both verdicts (verbatim from pillar scorecards)

- Pillar A verdict: **{pillar_a.get('verdict')}** (Sprint 30b locked-March holdout under gate v2)
- Pillar B verdict: **{pillar_b.get('verdict')}** (Sprint 33 locked-March holdout under Sprint-32 frozen envelope)

## 6. Sprint 34 packaging governance

- Modeling-source governance scan:
  - files_scanned: `{governance.files_scanned}`
  - clean: `{governance.clean}`
  - safety_status: `{governance.safety_status}`
  - violations: `{list(governance.violations)}`
- Edge / site / control packaging remains BLOCKED:
{chr(10).join(f"  - `{k}` -- {v}" for k, v in PACKAGING_BLOCKS.items())}

## 7. Cannot claim

{cannot_claim_md}
"""


# --------------------------------------------------------------------------- #
# Top-level builder
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class UnifiedPackage:
    """In-memory representation of every Sprint-34 unified-package surface."""
    scorecard: dict[str, Any]
    dashboard_html: str
    executive_report_md: str
    ml_audit_md: str
    plant_manager_summary_md: str
    health_event_export: dict[str, Any]
    health_event_csv: str
    efficiency_advisory_export: dict[str, Any]
    efficiency_advisory_csv: str
    artifact_manifest: dict[str, Any]
    governance: GovernanceScanResult
    packaging_gate: dict[str, Any]


def build_unified_package(
    *,
    repo_root: Path,
    pillar_a_scorecard_path: Path,
    pillar_b_scorecard_path: Path,
    generated_at_utc: str | None = None,
) -> UnifiedPackage:
    """Build the entire unified package in memory.

    No filesystem writes happen here. The runner script writes the
    resulting surfaces to disk; tests use the in-memory result directly.
    """
    pa = _read_json(pillar_a_scorecard_path)
    pb = _read_json(pillar_b_scorecard_path)
    a_view = _read_pillar_a(pa)
    b_view = _read_pillar_b(pb)
    a_verdict = a_view["verdict"]
    b_verdict = b_view["verdict"]
    status = _product_status_line(a_verdict, b_verdict)
    generated = generated_at_utc or _utcnow_iso()

    governance = _govern_modeling_source(repo_root)
    health_export = build_health_event_export(pa)
    health_csv = health_event_export_to_csv(health_export)
    advisory_export = build_efficiency_advisory_export(pb)
    advisory_csv = efficiency_advisory_export_to_csv(advisory_export)

    records = build_artifact_manifest_records(
        repo_root=repo_root,
        pillar_a_scorecard_path=pillar_a_scorecard_path,
        pillar_b_scorecard_path=pillar_b_scorecard_path,
        pillar_a_verdict=a_verdict,
        pillar_b_verdict=b_verdict,
    )
    manifest = build_artifact_manifest_json(records, governance=governance)

    exec_md = render_executive_report(
        product_status=status,
        pillar_a=a_view,
        pillar_b=b_view,
        generated_at_utc=generated,
    )
    ml_audit_md = render_ml_audit_appendix(
        pillar_a=a_view,
        pillar_b=b_view,
        pillar_a_scorecard=pa,
        pillar_b_scorecard=pb,
        governance=governance,
        generated_at_utc=generated,
    )
    pm_summary_md = render_plant_manager_summary(
        product_status=status, pillar_a=a_view, pillar_b=b_view
    )
    dashboard_html = render_dashboard_html(
        product_status=status,
        pillar_a=a_view,
        pillar_b=b_view,
        health_export=health_export,
        advisory_export=advisory_export,
        generated_at_utc=generated,
    )

    surfaces: list[tuple[str, str]] = [
        ("dashboard_html", dashboard_html),
        ("executive_report_md", exec_md),
        ("ml_audit_md", ml_audit_md),
        ("plant_manager_summary_md", pm_summary_md),
        ("health_event_csv", health_csv),
        ("efficiency_advisory_csv", advisory_csv),
        ("health_event_export_json", json.dumps(health_export, default=str)),
        ("efficiency_advisory_export_json", json.dumps(advisory_export, default=str)),
        ("artifact_manifest_json", json.dumps(manifest, default=str)),
    ]
    report_surfaces: list[tuple[str, str]] = [
        ("dashboard_html", dashboard_html),
        ("executive_report_md", exec_md),
        ("ml_audit_md", ml_audit_md),
        ("plant_manager_summary_md", pm_summary_md),
        ("health_event_export_json", json.dumps(health_export, default=str)),
        ("efficiency_advisory_export_json", json.dumps(advisory_export, default=str)),
        ("artifact_manifest_json", json.dumps(manifest, default=str)),
    ]
    gate = _packaging_gate(
        governance=governance,
        dashboard_html=dashboard_html,
        package_surfaces=surfaces,
        report_surfaces=report_surfaces,
    )

    scorecard = {
        "schema": "sprint34.unified_scorecard.v1",
        "sprint": SPRINT,
        "report_version": REPORT_VERSION,
        "generated_at_utc": generated,
        "safety_banner": SAFETY_BANNER,
        "advisory_only": True,
        "evaluation_mode": "offline_only",
        "site_integration_allowed": False,
        "influences_control": False,
        "scorecard_role": "advisory_evidence_only",
        "write_path": "scorecard_and_evidence_files_only",
        "is_evidence_not_setpoint": True,
        "pillar_a_verdict": a_verdict,
        "pillar_b_verdict": b_verdict,
        "product_status": status,
        "pillar_a": a_view,
        "pillar_b": b_view,
        "source_scorecards": {
            "pillar_a": str(pillar_a_scorecard_path.as_posix()),
            "pillar_b": str(pillar_b_scorecard_path.as_posix()),
        },
        "packaging_gate": gate,
        "governance_scan": {
            "clean": bool(governance.clean),
            "files_scanned": int(governance.files_scanned),
            "violations": list(governance.violations),
            "safety_status": governance.safety_status,
        },
        "packaging_blocks": dict(PACKAGING_BLOCKS),
        "cannot_claim": list(CANNOT_CLAIM_STATEMENTS),
        "allowed_pillar_b_language": list(ALLOWED_PILLAR_B_LANGUAGE),
    }

    return UnifiedPackage(
        scorecard=scorecard,
        dashboard_html=dashboard_html,
        executive_report_md=exec_md,
        ml_audit_md=ml_audit_md,
        plant_manager_summary_md=pm_summary_md,
        health_event_export=health_export,
        health_event_csv=health_csv,
        efficiency_advisory_export=advisory_export,
        efficiency_advisory_csv=advisory_csv,
        artifact_manifest=manifest,
        governance=governance,
        packaging_gate=gate,
    )


def write_unified_package(
    package: UnifiedPackage, *, out_dir: Path
) -> dict[str, Path]:
    """Write every surface in ``package`` to ``out_dir`` and return the paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "scorecard": out_dir / "sprint34_unified_scorecard.json",
        "dashboard": out_dir / "sprint34_dashboard.html",
        "executive_report": out_dir / "sprint34_executive_report.md",
        "ml_audit": out_dir / "sprint34_ml_audit_appendix.md",
        "plant_manager_summary": out_dir / "sprint34_plant_manager_summary.md",
        "health_event_csv": out_dir / "health_event_export.csv",
        "health_event_json": out_dir / "health_event_export.json",
        "efficiency_advisory_csv": out_dir / "efficiency_advisory_export.csv",
        "efficiency_advisory_json": out_dir / "efficiency_advisory_export.json",
        "artifact_manifest": out_dir / "sprint34_artifact_manifest.json",
    }
    paths["scorecard"].write_text(
        json.dumps(package.scorecard, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    paths["dashboard"].write_text(package.dashboard_html, encoding="utf-8")
    paths["executive_report"].write_text(package.executive_report_md, encoding="utf-8")
    paths["ml_audit"].write_text(package.ml_audit_md, encoding="utf-8")
    paths["plant_manager_summary"].write_text(
        package.plant_manager_summary_md, encoding="utf-8"
    )
    paths["health_event_csv"].write_text(package.health_event_csv, encoding="utf-8")
    paths["health_event_json"].write_text(
        json.dumps(package.health_event_export, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    paths["efficiency_advisory_csv"].write_text(
        package.efficiency_advisory_csv, encoding="utf-8"
    )
    paths["efficiency_advisory_json"].write_text(
        json.dumps(
            package.efficiency_advisory_export, indent=2, sort_keys=True, default=str
        ),
        encoding="utf-8",
    )
    paths["artifact_manifest"].write_text(
        json.dumps(package.artifact_manifest, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return paths


__all__ = [
    "SPRINT",
    "REPORT_VERSION",
    "SAFETY_BANNER",
    "CANNOT_CLAIM_STATEMENTS",
    "ALLOWED_PILLAR_B_LANGUAGE",
    "PACKAGING_BLOCKS",
    "DEFAULT_PILLAR_A_SCORECARD",
    "DEFAULT_PILLAR_B_SCORECARD",
    "DEFAULT_UNIFIED_DIR",
    "UnifiedPackage",
    "build_health_event_export",
    "health_event_export_to_csv",
    "build_efficiency_advisory_export",
    "efficiency_advisory_export_to_csv",
    "build_artifact_manifest_records",
    "build_artifact_manifest_json",
    "render_dashboard_html",
    "render_executive_report",
    "render_plant_manager_summary",
    "render_ml_audit_appendix",
    "build_unified_package",
    "write_unified_package",
]
