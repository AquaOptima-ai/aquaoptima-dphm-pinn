# AOPSO Decision Memo — Health/Anomaly Detection Works; Efficiency Advisory Does Not (at this site, on current data)

**Project:** Pump Station Optimizer Lite (AOPSO) — Yilan single legacy pump station
**Scope:** Offline, advisory-only evaluation against the locked **March 2026** benchmark
**Status:** Decision memo after the unified A+B product evaluation (Sprints 27–35)
**Safety posture:** Advisory-only, offline-only. No actuation, no setpoints, no site integration, no write path. **Packaging is not deployment authorization.**

---

## 1. One-paragraph executive summary

After two honest failures of short-horizon **forecasting** against the locked March 2026 holdout, we
pivoted to a unified product with two pillars: **A — Health/Anomaly Detection** and **B — Efficiency
Advisory (kWh/m³)**. On honest, leakage-controlled, out-of-sample evaluation, **Pillar A works and is
worth using** as an offline advisory: it detects abnormal operation and sensor faults far more cleanly
than the interpretable baseline, holds up across seasonal shift, and is now packaged as a portable,
safety-flagged ONNX artifact. **Pillar B does not produce a defensible efficiency opportunity at this
single site on the current data** — under a conservative quantile there is essentially no robust kWh
saving to advise, and most intervals lack enough comparable history to advise on at all. We recommend
**adopting Pillar A as an offline health advisory** and **shelving Pillar B** pending a clearly-scoped
sensitivity study (already drafted, parked). Both conclusions are evidence-backed, not assumptions.

---

## 2. What we tested, and how honestly

- **Locked holdout:** March 2026 telemetry was frozen and **never used for training, tuning, or
  threshold selection.** Models were fit on 2025 auto-mode data only; leakage guards raise if any
  March key reaches a fit input.
- **Pre-registration:** acceptance gates were frozen (hash-checked) *before* the holdout was scored,
  so we could not move the goalposts after seeing results. A FAIL was always an allowed outcome.
- **No tuning-to-the-test:** gate definitions were justified up front (operations grounds), not
  reverse-engineered to make a number pass.
- **Independent verification:** every model run was re-checked against git and the raw scorecards;
  self-reported "success" was never taken at face value.

This is why both the PASS and the FAIL below can be trusted.

---

## 3. Pillar A — Health/Anomaly Detection: **VALIDATED**

A small CPU autoencoder learns the *normal* operating envelope from 2025 data; reconstruction error
flags drift, degradation, and sensor faults. Evaluated on the locked March 2026 holdout under a
pre-registered gate, with a full-year-2025 stratified fit (8 distinct months) to rule out a
seasonal artifact:

| Metric (March 2026 holdout) | Learned detector | Interpretable baseline |
|---|---|---|
| AUROC | **0.944** | 0.918 |
| Injected-fault false-alarm rate | **1.28%** | 5.18% (**~4× fewer false alarms**) |
| Mean lead time | **15.8 steps** | 4.8 steps |
| Raw unsupervised March flag rate | **1.23%** | 5.18% |

**Why this matters to operations:** the #1 complaint about monitoring systems is alarm fatigue. This
detector flags genuine abnormality with roughly a quarter of the false alarms of the baseline, earlier,
and is robust to seasonal change. It is now exported to **ONNX** (parity-verified vs PyTorch — flags
bit-identical on 42,674 real March rows; ~0.017 ms/inference on CPU), wrapped in a contracts-compliant
artifact record with an **all-True safety flag set** (no control, no write, offline, read-only).

**Honest limitations (cannot-claim):** March 2026 has no ground-truth fault labels, so we measure
response to canonical injected faults on genuinely-unseen normal data — **not** field-validated fault
recall or predictive-maintenance accuracy. We do not claim a deployable control policy. Real operator/
maintenance logs, if available, would let us validate against true events.

---

## 4. Pillar B — Efficiency Advisory (kWh/m³): **FAILED (honest)**

The idea: learn an efficient operating envelope from 2025 history (specific energy kWh/m³ under
matched demand/level/pressure conditions), then flag where March 2026 operation fell short — as
**counterfactual, offline opportunity only**, never as setpoints. Engine and envelope were built
correctly (units confirmed; speed ranges restricted to historically-observed values; unsupported
intervals rejected). On the locked March holdout under the pre-registered frozen gate, it **FAILed**:

- Under the **conservative (p25) envelope, estimated kWh opportunity = 0.0** (even the optimistic p10
  was only ~1.3 kWh).
- Only **21 of 58** valid March intervals had enough comparable 2025 history to advise on; 37 were
  honestly rejected for insufficient support.
- All safety/leakage/no-unsupported-savings checks passed — the failure is *real*, not a bug.

**Interpretation:** on this single legacy station, 2025 auto operation is already close to its own
efficient envelope, so there is no conservative, defensible saving to advise — and much of March's
operation has no well-matched historical precedent to compare against. Selling an efficiency number
here would mean overstating value we cannot stand behind. **Knowing this is itself valuable.**

---

## 5. Recommendation

1. **Adopt Pillar A as an offline health/anomaly advisory.** It is validated, packaged (ONNX), fast,
   and safety-flagged. Use it for evidence-based monitoring and early degradation/sensor-fault
   warnings — **offline and advisory**, with no control authority.
2. **Shelve Pillar B** as "no defensible efficiency opportunity at this site on current data." Do not
   ship an efficiency savings claim.
3. **Keep one open question parked:** a clearly-scoped **sensitivity study** (Plane #44) to test whether
   relaxed matching tolerances or deeper per-condition history would yield robust support on more than
   21/58 intervals — run 2025-only, with March re-frozen and re-pre-registered for at most one final
   check. Current expectation: it confirms the FAIL. Revisit only when prioritized.

## 6. Safety boundary (applies to everything above)

This work is **offline and advisory only.** No setpoints, no actuation, no live/site integration, no
write path. The ONNX packaging is a portable inference/evidence artifact — **packaging is not
deployment authorization.** Edge deployment and control integration remain blocked and require a
separate future safety qualification before they can even be discussed.

---

*Evidence: `data/eval/pillarA/sprint30b_fullyear_holdout_scorecard.json` (Pillar A PASS),
`data/eval/pillarB/sprint33_locked_march_scorecard.json` (Pillar B FAIL),
`data/eval/packaging/sprint35_pillarA_onnx_scorecard.json` (ONNX packaging PASS),
`data/eval/unified/` (unified A+B evidence bundle). All verdicts independently verified against the
locked March 2026 holdout under pre-registered gates.*
