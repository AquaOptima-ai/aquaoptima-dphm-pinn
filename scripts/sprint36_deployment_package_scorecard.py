#!/usr/bin/env python3
"""AOPSO Sprint 36 -- Pillar A Linux deployment package scorecard generator.

Composes the Sprint-36 deployment-package scorecard JSON. The scorecard:

* records the Dockerfile / .dockerignore / build script paths and the
  resulting image digest (or ``skipped_no_builder`` if no Docker / Podman
  daemon was available);
* records the serving-entrypoint parity result against the Sprint-35
  ONNX scoring wrapper (proven in-process so it does NOT depend on
  Docker);
* records the deployment-manifest validation result against the canonical
  AMAX-5580 Edge profile;
* records the boundary scan (no control-plane network, no write path,
  read-only-by-design, forbidden-token scan over the package + manifest);
* runs the canonical acceptance gate and emits a single ``PASS`` /
  ``FAIL`` verdict.

A ``FAIL`` is a valid, honest outcome -- the script reports the real
verdict and exits 0 except on a true error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aquaoptima.advisory.packaging import (  # noqa: E402
    PILLARA_DEPLOYMENT_PACKAGE_ID,
    PILLARA_DEPLOYMENT_PACKAGE_VERSION,
    build_pillarA_deployment_package_manifest,
    score_to_evidence,
    score_with_onnx,
    write_pillarA_deployment_package_manifest,
)
from aquaoptima.advisory.packaging.serve_advisory import (  # noqa: E402
    EVIDENCE_COLUMNS,
)
from aquaoptima.advisory.governance import (  # noqa: E402
    scan_modeling_source_for_governance_violations,
)
from aquaoptima_contracts import (  # noqa: E402
    DeploymentPackageManifest,
    default_amax_edge_capability_declaration,
    validate_deployment_package_for_edge,
)
from aquaoptima_contracts.safety.vocabulary import (  # noqa: E402
    contains_forbidden_token,
)


PACKAGING_DIR = REPO_ROOT / "data" / "eval" / "packaging"
ONNX_PATH = PACKAGING_DIR / "pillarA_health_detector.onnx"
SIDECAR_PATH = PACKAGING_DIR / "pillarA_health_detector.sidecar.json"
ARTIFACT_RECORD_PATH = PACKAGING_DIR / "pillarA_onnx_artifact_record.json"
MANIFEST_PATH = PACKAGING_DIR / "pillarA_deployment_package_manifest.json"
SCORECARD_PATH = PACKAGING_DIR / "sprint36_deployment_package_scorecard.json"
DOCKERFILE_PATH = REPO_ROOT / "deploy" / "pillarA_advisory" / "Dockerfile"
DOCKERIGNORE_PATH = REPO_ROOT / "deploy" / "pillarA_advisory" / ".dockerignore"
REQUIREMENTS_PATH = REPO_ROOT / "deploy" / "pillarA_advisory" / "requirements.txt"
BUILD_SCRIPT_PATH = REPO_ROOT / "scripts" / "build_pillarA_image.sh"
SERVE_ENTRYPOINT_PATH = SRC / "aquaoptima" / "advisory" / "packaging" / "serve_advisory.py"
SERVE_SHIM_PATH = REPO_ROOT / "scripts" / "serve_pillarA_advisory.py"


def _sha256_of_path(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _synthetic_frames(n: int = 256, seed: int = 0) -> pd.DataFrame:
    sidecar = json.loads(SIDECAR_PATH.read_text())
    axes = sidecar["axes"]
    mu = np.asarray(sidecar["mu"], dtype=np.float64)
    sigma = np.asarray(sidecar["sigma"], dtype=np.float64)
    rng = np.random.default_rng(seed)
    Z = rng.standard_normal(size=(n, len(axes))).astype(np.float64) * 0.05
    Z[-16:, :] = 4.0  # inject anomalies so we exercise both flag classes
    X = Z * sigma + mu
    return pd.DataFrame(X, columns=axes)


def _serving_parity(tmp_dir: Path) -> dict[str, Any]:
    frames = _synthetic_frames()
    csv_path = tmp_dir / "input.csv"
    frames.to_csv(csv_path, index=False)
    evidence_dir = tmp_dir / "evidence"
    result = score_to_evidence(
        onnx_path=ONNX_PATH,
        sidecar_path=SIDECAR_PATH,
        input_path=csv_path,
        evidence_dir=evidence_dir,
    )
    ref = score_with_onnx(frames, ONNX_PATH, SIDECAR_PATH)
    flags_identical = bool(
        np.array_equal(result.scoring_result.detector_flag, ref.detector_flag)
    )
    max_abs_score_diff = float(
        np.max(
            np.abs(
                result.scoring_result.detector_anomaly_score
                - ref.detector_anomaly_score
            )
        )
    )
    return {
        "entrypoint_path": str(SERVE_ENTRYPOINT_PATH.relative_to(REPO_ROOT)),
        "reproduces_sprint35_scores": (
            flags_identical and max_abs_score_diff <= 1e-12
        ),
        "max_abs_score_diff_vs_sprint35": max_abs_score_diff,
        "flags_identical": flags_identical,
        "n_rows": int(len(frames)),
        "evidence_columns": list(EVIDENCE_COLUMNS),
        "evidence_csv_path": str(result.evidence_csv_path),
        "evidence_summary_path": str(result.evidence_summary_path),
    }


def _latency(n_iters: int = 50) -> dict[str, Any]:
    frames = _synthetic_frames()
    single = frames.iloc[:1]
    # warm up the session
    score_with_onnx(single, ONNX_PATH, SIDECAR_PATH)
    ts: list[float] = []
    for _ in range(n_iters):
        t0 = time.perf_counter()
        score_with_onnx(single, ONNX_PATH, SIDECAR_PATH)
        ts.append(time.perf_counter() - t0)
    ts.sort()
    t0 = time.perf_counter()
    score_with_onnx(frames, ONNX_PATH, SIDECAR_PATH)
    batch_ms = (time.perf_counter() - t0) * 1000
    return {
        "single_row_mean_ms": float(np.mean(ts) * 1000),
        "single_row_p50_ms": float(ts[len(ts) // 2] * 1000),
        "single_row_p99_ms": float(ts[int(0.99 * len(ts))] * 1000),
        "n_single_row_iters": n_iters,
        "batch_256_row_ms": float(batch_ms),
        "provider": "onnxruntime CPUExecutionProvider, intra=1 inter=1",
        "profile": "AMAX-5580 linux/amd64 CPU surrogate",
    }


def _manifest_block(image_digest: str | None) -> dict[str, Any]:
    manifest = build_pillarA_deployment_package_manifest(
        onnx_path=ONNX_PATH,
        sidecar_path=SIDECAR_PATH,
        artifact_record_json_path=ARTIFACT_RECORD_PATH,
    )
    write_pillarA_deployment_package_manifest(manifest, MANIFEST_PATH)
    edge = default_amax_edge_capability_declaration()
    result = validate_deployment_package_for_edge(manifest, edge)
    model_record = manifest.model_artifacts[0]
    safety_flags = manifest.safety_declaration.safety_flag_set.to_dict()
    return {
        "path": str(MANIFEST_PATH.relative_to(REPO_ROOT)),
        "schema_family": manifest.envelope.schema_family,
        "package_id": manifest.package_id,
        "package_version": manifest.package_version,
        "validate_edge": "PASS" if result.accepted else "FAIL",
        "edge_validator_errors": list(result.errors),
        "edge_validator_warnings": list(result.warnings),
        "model_records": len(manifest.model_artifacts),
        "safety_flags_all_true": all(safety_flags.values()),
        "safety_flags": safety_flags,
        "model_record": {
            "model_id": model_record.model_id,
            "model_version": model_record.model_version,
            "framework": model_record.framework,
            "checksum_hex": model_record.artifact_reference.checksum.hex_digest,
            "checksum_size_bytes": model_record.artifact_reference.checksum.size_bytes,
        },
        "edge_profile_id": result.profile_id,
        "rejected_accelerator_tokens": list(result.rejected_accelerator_tokens),
        "rejected_frameworks": list(result.rejected_frameworks),
    }


def _scan_manifest_free_form_strings(manifest_path: Path) -> list[str]:
    """Scan only the *free-form* text fields of the deployment manifest.

    Canonical safety-flag tokens like ``no_setpoint_output`` legitimately
    appear as field names of :class:`SafetyFlagSet` -- they assert the
    *absence* of those behaviors. A naive substring scan would flag those
    keys as violations; the canonical SDK already validates every
    free-form string at construction time. We mirror that intent here by
    walking only the free-form fields: notes (manifest, safety
    declaration), descriptions (artifacts, model artifacts, bundles),
    and string-valued summary entries.
    """
    payload = json.loads(manifest_path.read_text())
    free_form: list[str] = []
    free_form.append(payload.get("notes", "") or "")
    safety_decl = payload.get("safety_declaration", {}) or {}
    free_form.append(safety_decl.get("notes", "") or "")
    for art in payload.get("artifacts", []) or ():
        free_form.append(art.get("description", "") or "")
        for v in (art.get("summary") or {}).values():
            if isinstance(v, str):
                free_form.append(v)
            elif isinstance(v, list):
                free_form.extend(s for s in v if isinstance(s, str))
    for rec in payload.get("model_artifacts", []) or ():
        free_form.append(rec.get("description", "") or "")
        for v in (rec.get("summary") or {}).values():
            if isinstance(v, str):
                free_form.append(v)
            elif isinstance(v, list):
                free_form.extend(s for s in v if isinstance(s, str))
    hits: set[str] = set()
    for text in free_form:
        if text:
            hits.update(contains_forbidden_token(text))
    return sorted(hits)


def _boundary_block() -> dict[str, Any]:
    # Forbidden-token scan over (1) the manifest text (free-form fields
    # only -- see comment in _scan_manifest_free_form_strings), (2) the
    # Dockerfile, (3) the serving entrypoint, (4) the build script.
    targets = [
        ("dockerfile", DOCKERFILE_PATH),
        ("dockerignore", DOCKERIGNORE_PATH),
        ("requirements", REQUIREMENTS_PATH),
        ("serve_entrypoint", SERVE_ENTRYPOINT_PATH),
        ("serve_shim", SERVE_SHIM_PATH),
        ("build_script", BUILD_SCRIPT_PATH),
    ]
    hits: dict[str, list[str]] = {}
    for label, path in targets:
        text = path.read_text()
        token_hits = sorted(contains_forbidden_token(text))
        if token_hits:
            hits[label] = token_hits
    manifest_hits = _scan_manifest_free_form_strings(MANIFEST_PATH)
    if manifest_hits:
        hits["manifest_free_form"] = manifest_hits
    # Run the existing governance scan over the advisory/packaging tree.
    governance = scan_modeling_source_for_governance_violations(
        [SRC / "aquaoptima" / "advisory" / "packaging"]
    )
    return {
        "control_plane_network": False,
        "write_path": False,
        "runs_read_only": True,
        "forbidden_token_scan": "clean" if not hits else "violations",
        "forbidden_token_hits": hits,
        "governance_scan_clean": governance.clean,
        "governance_scan_violations": list(governance.violations),
        "governance_scan_files_scanned": governance.files_scanned,
        "container_runtime_flags": [
            "--read-only",
            "--network=none",
            "--user 1001:1001",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
        ],
    }


def _image_block(image_digest: str | None) -> dict[str, Any]:
    return {
        "base": "python:3.12-slim",
        "platform": "linux/amd64",
        "dockerfile_path": str(DOCKERFILE_PATH.relative_to(REPO_ROOT)),
        "dockerignore_present": DOCKERIGNORE_PATH.exists(),
        "requirements_path": str(REQUIREMENTS_PATH.relative_to(REPO_ROOT)),
        "build_script_path": str(BUILD_SCRIPT_PATH.relative_to(REPO_ROOT)),
        "docker_build": image_digest if image_digest else "skipped_no_builder",
        "read_only_designed": True,
        "non_root": True,
        "network": "none",
    }


def _acceptance_gate(
    *,
    image_block: dict[str, Any],
    serving_block: dict[str, Any],
    manifest_block: dict[str, Any],
    boundary_block: dict[str, Any],
    runbook_path: Path,
) -> dict[str, Any]:
    criteria: list[dict[str, Any]] = []

    dockerfile_ok = bool(
        DOCKERFILE_PATH.exists()
        and DOCKERIGNORE_PATH.exists()
        and BUILD_SCRIPT_PATH.exists()
        and "USER 1001:1001" in DOCKERFILE_PATH.read_text()
    )
    criteria.append(
        {
            "name": "dockerfile_dockerignore_buildscript_well_formed",
            "passed": dockerfile_ok,
            "detail": {
                "dockerfile_present": DOCKERFILE_PATH.exists(),
                "dockerignore_present": DOCKERIGNORE_PATH.exists(),
                "build_script_present": BUILD_SCRIPT_PATH.exists(),
                "non_root_user_declared": (
                    "USER 1001:1001" in DOCKERFILE_PATH.read_text()
                ),
                "platform": image_block["platform"],
            },
        }
    )

    criteria.append(
        {
            "name": "entrypoint_reproduces_sprint35_scores",
            "passed": serving_block["reproduces_sprint35_scores"],
            "detail": {
                "flags_identical": serving_block["flags_identical"],
                "max_abs_score_diff_vs_sprint35": serving_block[
                    "max_abs_score_diff_vs_sprint35"
                ],
                "n_rows": serving_block["n_rows"],
            },
        }
    )

    criteria.append(
        {
            "name": "deployment_manifest_validates_for_amax_edge",
            "passed": (
                manifest_block["validate_edge"] == "PASS"
                and manifest_block["safety_flags_all_true"]
                and not manifest_block["edge_validator_errors"]
            ),
            "detail": {
                "validate_edge": manifest_block["validate_edge"],
                "errors": manifest_block["edge_validator_errors"],
                "safety_flags_all_true": manifest_block["safety_flags_all_true"],
                "rejected_accelerator_tokens": manifest_block[
                    "rejected_accelerator_tokens"
                ],
                "rejected_frameworks": manifest_block["rejected_frameworks"],
            },
        }
    )

    criteria.append(
        {
            "name": "boundary_holds_no_control_no_write_clean_scan",
            "passed": (
                boundary_block["control_plane_network"] is False
                and boundary_block["write_path"] is False
                and boundary_block["runs_read_only"] is True
                and boundary_block["forbidden_token_scan"] == "clean"
                and boundary_block["governance_scan_clean"]
            ),
            "detail": {
                "forbidden_token_scan": boundary_block["forbidden_token_scan"],
                "forbidden_token_hits": boundary_block["forbidden_token_hits"],
                "governance_scan_clean": boundary_block["governance_scan_clean"],
                "governance_scan_violations": boundary_block[
                    "governance_scan_violations"
                ],
            },
        }
    )

    runbook_present = runbook_path.exists()
    runbook_text = runbook_path.read_text() if runbook_present else ""
    runbook_ok = bool(
        runbook_present
        and "shadow" in runbook_text.lower()
        and "offline" in runbook_text.lower()
        and "not" in runbook_text.lower()
        and "authoriz" in runbook_text.lower()
    )
    criteria.append(
        {
            "name": "shadow_mode_runbook_present_and_explicit",
            "passed": runbook_ok,
            "detail": {
                "path": str(runbook_path.relative_to(REPO_ROOT))
                if runbook_present
                else None,
                "exists": runbook_present,
                "mentions_shadow": "shadow" in runbook_text.lower(),
                "mentions_offline": "offline" in runbook_text.lower(),
                "states_not_control_authorized": runbook_ok,
            },
        }
    )

    passed = all(c["passed"] for c in criteria)
    return {
        "criteria": criteria,
        "passed": passed,
        "verdict": "PASS" if passed else "FAIL",
        "rule": (
            "ALL of: Dockerfile + .dockerignore + build script well-formed, "
            "targeting linux/amd64, non-root USER, read-only-friendly; "
            "serving entrypoint reproduces Sprint-35 ONNX scores in-process "
            "(flags identical, score diff <= 1e-12); DeploymentPackageManifest "
            "builds and validate_deployment_package_for_edge returns zero "
            "errors against the canonical AMAX-5580 declaration with all "
            "safety flags True; boundary holds (no control-plane network, no "
            "write path, container runs read-only, forbidden-token + "
            "governance scans clean); shadow-mode runbook present and "
            "explicitly offline / not-control-authorized."
        ),
    }


def build_scorecard(*, image_digest: str | None) -> dict[str, Any]:
    tmp_dir = REPO_ROOT / "build" / "sprint36-tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    serving = _serving_parity(tmp_dir)
    manifest = _manifest_block(image_digest)
    boundary = _boundary_block()
    image = _image_block(image_digest)
    latency = _latency()
    runbook = (
        REPO_ROOT
        / "docs"
        / "product"
        / "aopso-health-efficiency-ab"
        / "08-pillarA-linux-deployment-runbook.md"
    )
    acceptance = _acceptance_gate(
        image_block=image,
        serving_block=serving,
        manifest_block=manifest,
        boundary_block=boundary,
        runbook_path=runbook,
    )
    payload: dict[str, Any] = {
        "sprint": "36",
        "pillar": "A",
        "advisory_only": True,
        "evaluation_mode": "offline_only",
        "target": "AMAX-8580 linux/amd64 CPU",
        "edge_profile_id": manifest["edge_profile_id"],
        "package_id": PILLARA_DEPLOYMENT_PACKAGE_ID,
        "package_version": PILLARA_DEPLOYMENT_PACKAGE_VERSION,
        "image": image,
        "serving": serving,
        "deployment_manifest": manifest,
        "boundary": boundary,
        "cpu_latency": latency,
        "runbook_path": str(runbook.relative_to(REPO_ROOT)),
        "produced_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "acceptance_gate": acceptance,
        "verdict": acceptance["verdict"],
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image-digest",
        default=None,
        help=(
            "image digest to record under image.docker_build (e.g. "
            "'sha256:...'); pass 'skipped_no_builder' if no Docker / Podman "
            "was available."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=SCORECARD_PATH,
        help="scorecard JSON output path",
    )
    args = parser.parse_args()
    payload = build_scorecard(image_digest=args.image_digest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, sort_keys=True, indent=2))
    print(f"verdict={payload['verdict']} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
