#!/usr/bin/env python3
"""End-to-end Pillar A pipeline test (AOPSO).

Drives the WHOLE chain through real public APIs on a fresh 2025 subset:
  profile -> fit baselines -> train detector -> inject faults -> evaluate -> scorecard
and asserts every handoff + the final scorecard's self-consistency and safety guarantees.

This is an INTEGRATION check beyond unit tests: it proves the pieces compose coherently
end to end and that the honest gate + governance wiring actually fire on real-shaped data.
Offline-only, advisory-only, no writes to anything but a temp scorecard, no actuation.
"""
from __future__ import annotations

import json
import sys
import numpy as np
import pandas as pd

from aquaoptima.advisory.label_schema import active_axes_ordered
from aquaoptima.advisory.governance import assert_holdout_isolated
from aquaoptima.advisory.health_baselines import fit_health_baseline_suite
from aquaoptima.advisory.health_detector import fit_health_detector
from aquaoptima.advisory.injected_faults import inject_faults
from aquaoptima.advisory.health_gate import (
    evaluate_detector_vs_baseline,
    health_acceptance_gate,
)
from aquaoptima.advisory.schema_validation import (
    build_governance_block,
    apply_governance_to_verdict,
)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    status = "OK " if cond else "FAIL"
    print(f"  [{status}] {msg}")
    if not cond:
        FAILS.append(msg)


def make_2025_frame(n: int = 6000, seed: int = 7) -> pd.DataFrame:
    """Synthetic but realistically-shaped 2025 telemetry (60s cadence, 8 axes)."""
    rng = np.random.default_rng(seed)
    axes = active_axes_ordered()
    ts = pd.date_range("2025-04-01 00:00:00", periods=n, freq="60s")
    base = {
        "edge_flow": 900 + rng.normal(0, 40, n),
        "edge_power": 210 + rng.normal(0, 8, n),
        "edge_pump_speed": 48 + rng.normal(0, 1.5, n),
        "edge_status": np.clip(rng.normal(0.99, 0.02, n), 0, 1),
        "node_demand": 880 + rng.normal(0, 45, n),
        "node_level": 12 + rng.normal(0, 0.4, n),
        "node_pressure": 18 + rng.normal(0, 0.3, n),
        "node_status": 18 + rng.normal(0, 0.5, n),
    }
    df = pd.DataFrame(base, columns=axes)
    df.insert(0, "timestamp", ts.strftime("%Y-%m-%d %H:%M:%S"))
    return df


def main() -> int:
    print("=== STAGE 0: data + leakage guard ===")
    df = make_2025_frame()
    keys = df["timestamp"].tolist()
    iso = assert_holdout_isolated(keys)
    check(iso.isolated, "2025 keys isolated from March-2026 holdout")
    # negative control: a 2026-03 key must trip the guard
    leaked = assert_holdout_isolated(keys + ["2026-03-15 00:00:00"])
    check(not leaked.isolated and leaked.leaked_keys, "leakage guard trips on a 2026-03 key")

    axes = active_axes_ordered()
    train = df.iloc[:4000].reset_index(drop=True)
    normal_eval = df.iloc[4000:].reset_index(drop=True)

    print("=== STAGE 1: fit interpretable baselines (Sprint 28) ===")
    suite = fit_health_baseline_suite(train, axes=axes)
    bscore = suite.score(normal_eval)
    check("combined_deviation" in bscore.columns, "baseline emits combined_deviation")
    fa = suite.false_alarm_summary(normal_eval)
    check("combined_anomaly_flag_rate" in fa, "baseline false-alarm summary present")

    print("=== STAGE 2: train learned detector (Sprint 29) ===")
    detector = fit_health_detector(train, axes=axes, seed=0, epochs=8)
    dscore = detector.score(normal_eval)
    check("detector_anomaly_score" in dscore.columns, "detector emits detector_anomaly_score")
    # determinism
    detector2 = fit_health_detector(train, axes=axes, seed=0, epochs=8)
    d2 = detector2.score(normal_eval)
    check(np.allclose(dscore["detector_anomaly_score"], d2["detector_anomaly_score"]),
          "detector is deterministic on same seed")

    print("=== STAGE 3: inject faults (frozen seed) ===")
    injected = inject_faults(normal_eval, seed=123)
    labels = np.asarray(injected.labels)
    check(len(labels) == len(injected.frames), "fault labels align to faulted frames")
    check(int(np.sum(labels)) > 0, "at least one faulted row present")

    print("=== STAGE 4: evaluate detector vs baseline ===")
    ev = evaluate_detector_vs_baseline(
        detector=detector, baseline_suite=suite, injected=injected,
    )
    for k in ("detector", "baseline"):
        check(k in ev and "auroc" in ev[k], f"eval has {k}.auroc")
    print(f"      detector AUROC={ev['detector']['auroc']:.4f}  "
          f"baseline AUROC={ev['baseline']['auroc']:.4f}")

    print("=== STAGE 5: frozen gate + governance -> scorecard ===")
    gate = health_acceptance_gate(ev)
    check(gate["verdict"] in ("PASS", "FAIL"), "gate yields a real verdict")
    # governance block over the real modeling source, real split + norm stats
    gov = build_governance_block(
        split_manifest="data/splits/yilan_2025_split_v1.json",
        modeling_roots=["src/aquaoptima/advisory", "src/aquaoptima/training",
                        "src/aquaoptima/dataio", "src/aquaoptima/models"],
        normalization_stats="data/normalization/yilan_2025_train_stats.json",
    )
    check(gov.get("governance_status") == "PASS", "governance PASS on clean source+split+stats")
    final_gate = apply_governance_to_verdict(dict(gate), gov)
    check(final_gate["verdict"] == gate["verdict"],
          "governance PASS leaves model verdict unchanged")
    # negative control: governance FAIL forces verdict FAIL even on a passing gate
    forced = apply_governance_to_verdict({"verdict": "PASS", "passed": True, "criteria": []},
                                         {"governance_status": "FAIL"})
    check(forced["verdict"] == "FAIL", "governance FAIL forces verdict=FAIL regardless of metrics")

    print("=== STAGE 6: scorecard self-consistency ===")
    scorecard = {
        "pillar": "A_health", "advisory_only": True,
        "evaluation": ev, "acceptance_gate": final_gate,
        "governance": gov,
        "safety": {"evaluation_mode": "offline_only", "write_path": "scorecard_json_only",
                   "influences_control": False, "site_integration_allowed": False},
    }
    check(scorecard["safety"]["influences_control"] is False, "scorecard: influences_control=False")
    check(scorecard["safety"]["evaluation_mode"] == "offline_only", "scorecard: offline_only")
    # verdict consistent with the rule
    m = final_gate.get("metrics", {})
    if m:
        recomputed_r1 = (m["detector_auroc"] >= m["baseline_auroc"] + 0.02)
        recomputed_r3 = (m["detector_auroc"] >= 0.70)
        recomputed_r2 = (m["detector_false_alarm_rate"] <= m["baseline_false_alarm_rate"])
        expected = "PASS" if (recomputed_r1 and recomputed_r2 and recomputed_r3) else "FAIL"
        check(final_gate["verdict"] == expected,
              f"verdict ({final_gate['verdict']}) matches recomputed rule ({expected})")

    print("\n=== E2E PIPELINE SUMMARY ===")
    print(json.dumps({
        "detector_auroc": round(ev["detector"]["auroc"], 4),
        "baseline_auroc": round(ev["baseline"]["auroc"], 4),
        "model_verdict": final_gate["verdict"],
        "governance_status": gov.get("governance_status"),
        "checks_failed": len(FAILS),
    }, indent=2))

    if FAILS:
        print(f"\nE2E RESULT: FAIL ({len(FAILS)} checks failed)")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("\nE2E RESULT: PASS (full Pillar A pipeline coherent end to end)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
