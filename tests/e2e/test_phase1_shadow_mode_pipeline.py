"""Phase 1 shadow-mode MVP end-to-end pipeline validation.

This test wires the Sprint 11–39 public surfaces into a single
deterministic offline chain:

    EPANET-style ``.inp`` topology fixture
        → import diagnostics + import-quality report (Sprint 23–33)
        → telemetry tag map (Sprint 34)
        → shadow replay dataset (Sprint 35)
        → dPL calibration loss report (Sprint 36)
        → advisory safety contract audit (Sprint 37)
        → shadow runtime report (Sprint 38)
        → shadow deployment manifest JSON (Sprint 39)

The test is a Phase 1 **validation checkpoint** — it does not introduce
any Phase 2 / Sprint 40 product feature. The pipeline runs
**offline / read-only / no-write / no-control / no live OT binding / no
setpoint output / packaging audit only**: the only filesystem write is
the existing Sprint 39 manifest JSON, into a caller-supplied
``pytest`` ``tmp_path``.

Expected-value assertions exercised here:

* deterministic frame count, residual count, and per-axis MSE;
* deterministic advisory decision counts (accepted vs rejected);
* deterministic manifest artifact set;
* deterministic manifest JSON bytes across two independent runs
  (sha256 byte-equality).

Safety boundary asserted at the end of the test: the rendered manifest
JSON carries the Sprint 39 safety boundary phrases verbatim and does
not embed any live-OT / PLC / OPC-UA / MQTT / actuator / setpoint-write
strings.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from aquaoptima.dphm import (
    ADVISORY_AXIS_EDGE_FLOW,
    ADVISORY_AXIS_NODE_PRESSURE,
    ADVISORY_STATUS_ACCEPTED,
    ADVISORY_STATUS_REJECTED,
    ARTIFACT_KIND_ADVISORY_CONTRACT,
    ARTIFACT_KIND_DPL_LOSS_REPORT,
    ARTIFACT_KIND_SHADOW_REPLAY,
    ARTIFACT_KIND_SHADOW_RUNTIME_REPORT,
    DPLCalibrationLossReport,
    EpanetImportQualityReport,
    Network,
    SAFETY_BOUNDARY_PHRASES,
    ShadowDeploymentManifest,
    ShadowReplayDataset,
    ShadowRuntimeReport,
    TELEMETRY_AXIS_EDGE_FLOW,
    TELEMETRY_AXIS_NODE_PRESSURE,
    AdvisoryProposal,
    AdvisoryRule,
    TelemetryTagMap,
    build_advisory_contract,
    build_dpl_calibration_loss_report,
    build_import_quality_report,
    build_shadow_deployment_manifest,
    build_shadow_replay_dataset,  # noqa: F401  (covered transitively via CSV loader)
    load_network_from_inp,
    load_shadow_replay_csv,
    load_telemetry_tag_map_json,
    run_shadow_runtime,
    write_shadow_deployment_manifest_json,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
INP_FIXTURE_PATH = REPO_ROOT / "docs" / "examples" / "epanet_reference_loop.inp"
PHASE1_FIXTURE_DIR = (
    Path(__file__).resolve().parents[1] / "fixtures" / "shadow_phase1"
)
TAG_MAP_JSON_PATH = PHASE1_FIXTURE_DIR / "tag_map.json"
TELEMETRY_CSV_PATH = PHASE1_FIXTURE_DIR / "telemetry.csv"


# Deterministic prediction bias (small, constant, signed). The replay's
# observed values are biased uniformly so the per-axis MSE is exactly
# the square of the bias.
_PRESSURE_PREDICTION_BIAS_M: float = 0.5
_FLOW_PREDICTION_BIAS_M3_S: float = 0.001


def _predictions_from_replay(
    replay: ShadowReplayDataset,
) -> list[dict[str, dict[int, float]]]:
    """Build a per-frame predictions sequence biased uniformly per axis.

    Sprint 36 takes ``predicted - observed`` as the residual; with a
    constant bias per axis, the per-axis MSE collapses to the square of
    that bias, which is what the expected-value assertions key on.
    """
    predictions: list[dict[str, dict[int, float]]] = []
    for frame in replay.frames:
        entry: dict[str, dict[int, float]] = {}
        if frame.node_pressure:
            entry[TELEMETRY_AXIS_NODE_PRESSURE] = {
                target_id: observed + _PRESSURE_PREDICTION_BIAS_M
                for target_id, observed in frame.node_pressure.items()
            }
        if frame.edge_flow:
            entry[TELEMETRY_AXIS_EDGE_FLOW] = {
                target_id: observed + _FLOW_PREDICTION_BIAS_M3_S
                for target_id, observed in frame.edge_flow.items()
            }
        predictions.append(entry)
    return predictions


def _phase1_proposals_by_frame() -> list[list[AdvisoryProposal]]:
    """Three deterministic hypothetical proposals on frame 0.

    Phase 1 is *advisory proposal audit only* — no proposal is ever
    transformed into a setpoint write here. The three proposals exist
    so the audit covers at least one accepted and at least one
    rejected decision per the validation checkpoint requirements.
    """
    frame0 = [
        # Hits the (node_pressure, J1) allow rule in-bounds → accepted.
        AdvisoryProposal(
            proposal_id="ACCEPT_PRESSURE_J1",
            axis=ADVISORY_AXIS_NODE_PRESSURE,
            target_id=0,
            proposed_value=50.0,
            current_value=35.0,
        ),
        # Above the (edge_flow, P2) allow rule's max_value → rejected.
        AdvisoryProposal(
            proposal_id="REJECT_FLOW_BOUNDS",
            axis=ADVISORY_AXIS_EDGE_FLOW,
            target_id=1,
            proposed_value=0.060,
            current_value=0.025,
        ),
        # Hits the (node_pressure, J2) deny rule → rejected
        # unconditionally (and also misses the allow list, so the
        # rejection is overdetermined; the count assertion only cares
        # that the final status is rejected).
        AdvisoryProposal(
            proposal_id="REJECT_DENY_PRESSURE_J2",
            axis=ADVISORY_AXIS_NODE_PRESSURE,
            target_id=1,
            proposed_value=25.0,
            current_value=28.0,
        ),
    ]
    return [frame0, [], []]


def _build_phase1_contract():
    return build_advisory_contract(
        name="phase1-shadow-mvp",
        allow_rules=[
            AdvisoryRule(
                axis=ADVISORY_AXIS_NODE_PRESSURE,
                target_id=0,
                min_value=10.0,
                max_value=80.0,
                note="J1 discharge pressure envelope",
            ),
            AdvisoryRule(
                axis=ADVISORY_AXIS_EDGE_FLOW,
                target_id=1,
                min_value=0.001,
                max_value=0.040,
                note="P2 flow envelope",
            ),
        ],
        deny_rules=[
            AdvisoryRule(
                axis=ADVISORY_AXIS_NODE_PRESSURE,
                target_id=1,
                note="J2 discharge pressure is operator-locked",
            )
        ],
    )


def _build_pipeline(
    tmp_path: Path,
    *,
    manifest_filename: str = "shadow_phase1_manifest.json",
) -> tuple[
    Network,
    EpanetImportQualityReport,
    TelemetryTagMap,
    ShadowReplayDataset,
    DPLCalibrationLossReport,
    ShadowRuntimeReport,
    ShadowDeploymentManifest,
    Path,
]:
    """Run the full Phase 1 offline shadow-mode chain.

    Every call site uses the same shipped EPANET fixture, the same
    JSON tag map, the same CSV replay rows, and a deterministic
    prediction bias / proposal set — so two invocations on different
    ``tmp_path`` directories must produce byte-equal manifest JSON.
    """
    network, import_diagnostics = load_network_from_inp(
        INP_FIXTURE_PATH,
        parser="fallback",
        return_diagnostics=True,
    )
    quality_report = build_import_quality_report(
        import_diagnostics, network, parser="fallback"
    )
    tag_map = load_telemetry_tag_map_json(TAG_MAP_JSON_PATH, network)
    replay = load_shadow_replay_csv(TELEMETRY_CSV_PATH, tag_map)
    predictions = _predictions_from_replay(replay)
    loss_report = build_dpl_calibration_loss_report(
        replay, predictions, strict=True
    )
    contract = _build_phase1_contract()
    proposals_by_frame = _phase1_proposals_by_frame()
    runtime_report = run_shadow_runtime(
        replay,
        predictions,
        advisory_contract=contract,
        proposals_by_frame=proposals_by_frame,
        strict=True,
    )
    manifest = build_shadow_deployment_manifest(
        "aquaoptima-dphm-shadow-mvp",
        package_version="phase1-e2e",
        build_id="phase1-shadow-e2e",
        code_version="phase1-shadow-e2e-validation",
        summary_objects=[replay, loss_report, contract, runtime_report],
        references={
            "epanet_import_quality": {
                "parser": quality_report.parser,
                "total_diagnostic_rows": quality_report.total_diagnostic_rows,
                "ignored_section_count": quality_report.ignored_section_count,
                "section_count": len(quality_report.sections),
                "surrogate_count": len(quality_report.surrogates),
            },
            "phase": {"name": "phase1-shadow-mvp"},
        },
        notes=(
            "Phase 1 offline shadow-mode validation checkpoint. "
            "Packaging audit only — no live OT binding, no setpoint "
            "output, no control surface."
        ),
        strict=True,
    )
    manifest_path = tmp_path / manifest_filename
    written_path = write_shadow_deployment_manifest_json(
        manifest, manifest_path
    )
    return (
        network,
        quality_report,
        tag_map,
        replay,
        loss_report,
        runtime_report,
        manifest,
        written_path,
    )


def test_phase1_shadow_mode_pipeline(tmp_path: Path) -> None:
    """End-to-end: EPANET INP → ... → shadow deployment manifest JSON."""
    (
        network,
        quality_report,
        tag_map,
        replay,
        loss_report,
        runtime_report,
        manifest,
        manifest_path,
    ) = _build_pipeline(tmp_path)

    # ------------------------------------------------------------------
    # Stage 1 — topology fixture.
    # ------------------------------------------------------------------
    assert isinstance(network, Network)
    assert network.num_nodes == 5
    assert network.num_edges == 5
    assert int(network.num_fixed_heads) == 1

    # ------------------------------------------------------------------
    # Stage 2 — import-quality report (Sprint 23–33).
    # ------------------------------------------------------------------
    assert quality_report.parser == "fallback"
    assert quality_report.total_diagnostic_rows >= 0
    assert isinstance(quality_report.limitations, tuple)
    # The Sprint 33 report always carries at least the STATUS-open-only
    # and ignored-sections-dropped limitations.
    assert len(quality_report.limitations) >= 2

    # ------------------------------------------------------------------
    # Stage 3 — telemetry tag map (Sprint 34).
    # ------------------------------------------------------------------
    assert len(tag_map.tags) == 4
    assert tag_map.diagnostics.errors == ()
    assert {tag.tag for tag in tag_map.tags} == {
        "PT_J1",
        "PT_J2",
        "FT_P1",
        "FT_P2",
    }

    # ------------------------------------------------------------------
    # Stage 4 — shadow replay dataset (Sprint 35).
    # ------------------------------------------------------------------
    assert len(replay.frames) == 3
    assert replay.diagnostics.errors == ()
    for frame in replay.frames:
        # Two pressure tags + two flow tags per frame.
        assert len(frame.node_pressure) == 2
        assert len(frame.edge_flow) == 2
    assert replay.frames[0].node_pressure[0] == pytest.approx(35.0)
    assert replay.frames[2].edge_flow[1] == pytest.approx(0.027)

    # ------------------------------------------------------------------
    # Stage 5 — dPL calibration loss report (Sprint 36).
    # ------------------------------------------------------------------
    expected_residual_count = (
        len(replay.frames) * (2 + 2)
    )  # 3 frames × (2 pressure + 2 flow)
    assert loss_report.observation_count == expected_residual_count
    assert len(loss_report.residuals) == expected_residual_count
    pressure_mse = loss_report.mse_by_axis[TELEMETRY_AXIS_NODE_PRESSURE]
    flow_mse = loss_report.mse_by_axis[TELEMETRY_AXIS_EDGE_FLOW]
    assert pressure_mse == pytest.approx(
        _PRESSURE_PREDICTION_BIAS_M ** 2, abs=1e-12
    )
    assert flow_mse == pytest.approx(
        _FLOW_PREDICTION_BIAS_M3_S ** 2, abs=1e-15
    )
    assert loss_report.diagnostics.errors == ()

    # ------------------------------------------------------------------
    # Stage 6 — advisory contract audit (Sprint 37) via Stage 7 runtime.
    # ------------------------------------------------------------------
    assert runtime_report.frame_count == len(replay.frames)
    assert runtime_report.observation_count == expected_residual_count
    assert runtime_report.proposal_count == 3
    assert runtime_report.accepted_count == 1
    assert runtime_report.rejected_count == 2
    statuses = [d.status for d in runtime_report.advisory_decisions]
    assert statuses.count(ADVISORY_STATUS_ACCEPTED) == 1
    assert statuses.count(ADVISORY_STATUS_REJECTED) == 2

    accepted_ids = {
        d.proposal.proposal_id
        for d in runtime_report.advisory_decisions
        if d.status == ADVISORY_STATUS_ACCEPTED
    }
    rejected_ids = {
        d.proposal.proposal_id
        for d in runtime_report.advisory_decisions
        if d.status == ADVISORY_STATUS_REJECTED
    }
    assert accepted_ids == {"ACCEPT_PRESSURE_J1"}
    assert rejected_ids == {
        "REJECT_FLOW_BOUNDS",
        "REJECT_DENY_PRESSURE_J2",
    }

    # Per-step report: only frame 0 carries advisory decisions.
    assert len(runtime_report.steps) == 3
    assert len(runtime_report.steps[0].advisory_decisions) == 3
    assert runtime_report.steps[1].advisory_decisions == ()
    assert runtime_report.steps[2].advisory_decisions == ()
    assert runtime_report.diagnostics.errors == ()

    # ------------------------------------------------------------------
    # Stage 8 — shadow deployment manifest (Sprint 39).
    # ------------------------------------------------------------------
    assert isinstance(manifest, ShadowDeploymentManifest)
    assert manifest.package_name == "aquaoptima-dphm-shadow-mvp"
    assert manifest.code_version == "phase1-shadow-e2e-validation"
    assert manifest.diagnostics.errors == ()
    assert manifest.safety_boundary == SAFETY_BOUNDARY_PHRASES
    for flag_name in (
        "offline",
        "read_only",
        "no_write",
        "no_control",
        "no_live_ot_binding",
        "no_setpoint_output",
        "packaging_audit_only",
    ):
        assert manifest.safety_flags[flag_name] is True

    # Summary-object artifacts arrive in deterministic builder-input
    # order: replay, loss report, contract, runtime report.
    assert len(manifest.artifacts) == 4
    artifact_kinds = [artifact.kind for artifact in manifest.artifacts]
    assert artifact_kinds == [
        ARTIFACT_KIND_SHADOW_REPLAY,
        ARTIFACT_KIND_DPL_LOSS_REPORT,
        ARTIFACT_KIND_ADVISORY_CONTRACT,
        ARTIFACT_KIND_SHADOW_RUNTIME_REPORT,
    ]
    # Cross-check the summary scalars carried by the runtime artifact.
    runtime_artifact = manifest.artifacts[3]
    assert runtime_artifact.summary["frame_count"] == 3
    assert runtime_artifact.summary["proposal_count"] == 3
    assert runtime_artifact.summary["accepted_count"] == 1
    assert runtime_artifact.summary["rejected_count"] == 2

    # ------------------------------------------------------------------
    # Manifest JSON on disk — the *only* filesystem write performed by
    # the Phase 1 chain.
    # ------------------------------------------------------------------
    assert manifest_path == tmp_path / "shadow_phase1_manifest.json"
    written_files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    assert written_files == [manifest_path]

    raw_bytes = manifest_path.read_bytes()
    first_digest = hashlib.sha256(raw_bytes).hexdigest()

    payload = json.loads(raw_bytes.decode("utf-8"))
    assert payload["schema"] == (
        "aquaoptima.dphm.shadow_deployment_manifest/v1"
    )
    assert payload["package_name"] == "aquaoptima-dphm-shadow-mvp"
    assert payload["code_version"] == "phase1-shadow-e2e-validation"
    assert payload["safety_boundary"] == list(SAFETY_BOUNDARY_PHRASES)
    assert len(payload["artifacts"]) == 4
    payload_references = payload["references"]
    assert payload_references["phase"]["name"] == "phase1-shadow-mvp"
    assert (
        payload_references["epanet_import_quality"]["parser"]
        == "fallback"
    )

    # ------------------------------------------------------------------
    # Determinism: rebuild the pipeline from scratch into a sibling
    # tmp directory and assert byte-equality of the manifest JSON.
    # ------------------------------------------------------------------
    rerun_dir = tmp_path / "rerun"
    rerun_dir.mkdir()
    (
        _,
        _,
        _,
        _,
        _,
        _,
        _,
        rerun_manifest_path,
    ) = _build_pipeline(rerun_dir)
    rerun_bytes = rerun_manifest_path.read_bytes()
    assert rerun_bytes == raw_bytes
    assert hashlib.sha256(rerun_bytes).hexdigest() == first_digest

    # ------------------------------------------------------------------
    # Safety boundary in the rendered JSON. The manifest's
    # ``safety_boundary`` list contains the negation phrases verbatim
    # (e.g. ``"no live OT binding"``); the forbidden-substring check
    # below is therefore restricted to tokens that would only appear
    # in a *live* OT / actuator / write surface and that never appear
    # in the safety-boundary phrases themselves.
    # ------------------------------------------------------------------
    rendered_text = manifest_path.read_text(encoding="utf-8")
    # Word-bounded matches — bare substrings collide with legitimate
    # tokens (e.g. "PLC" inside "DPLCalibrationLossReport"). The
    # patterns below are restricted to tokens that would only appear
    # in a *live* OT / actuator / write surface and never in the
    # safety-boundary phrases themselves. The credential-marker
    # patterns are assembled from fragments so this file does not
    # itself embed a raw secret-scan trigger string.
    pem_marker_pattern = (
        r"-----" + "BEGIN" + r" (?:RSA|DSA|EC|OPENSSH|PRIVATE) "
        + "PRIVATE" + r" KEY-----"
    )
    aws_key_pattern = r"\b" + "AKIA" + r"[0-9A-Z]{16}\b"
    forbidden_patterns = (
        r"\bPLC\b",
        r"\bOPC-UA\b",
        r"\bMQTT\b",
        r"live SCADA",
        r"\bactuator\b",
        r"writeSetpoint",
        r"setpoint_write",
        r"setpoint_emit",
        pem_marker_pattern,
        aws_key_pattern,
    )
    for pattern in forbidden_patterns:
        assert re.search(pattern, rendered_text) is None, (
            f"forbidden pattern {pattern!r} unexpectedly matched in "
            f"manifest JSON"
        )


def test_phase1_shadow_mode_pipeline_writes_only_the_manifest(
    tmp_path: Path,
) -> None:
    """Safety: the Phase 1 chain writes *only* the manifest JSON.

    Reaffirms the offline / read-only / no-write / no-control /
    no live OT binding / no setpoint output boundary by listing every
    file under ``tmp_path`` after the chain runs and asserting it is
    exactly the caller-supplied manifest path.
    """
    (_, _, _, _, _, _, _, manifest_path) = _build_pipeline(tmp_path)
    written_files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    assert written_files == [manifest_path]
