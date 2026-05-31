# ADR-0003: Ship Pillar A (health detection); park Pillar B (efficiency advisory)

- **Status:** Accepted
- **Date:** 2026-05-31
- **Owner:** Product + Tech lead

## Context

AquaOptima's value hypothesis had two pillars:

- **Pillar A — health / anomaly detection:** detect equipment/process anomalies
  and degraded health on the pump station.
- **Pillar B — efficiency advisory (dPL):** recommend operating changes that
  reduce energy (kWh) for the same delivered service.

Both were tested against the locked offline March Yilan benchmark and broader
out-of-sample data:

- **Pillar A — VALIDATED.** Unqualified out-of-sample evaluation passed and was
  seasonally robust (Sprint 30b full-year holdout). It generalises.
- **Pillar B — honest FAIL.** Sprint 33 against the locked March benchmark found
  the **p25 kWh opportunity at 0.0**, with only **21 of 58 March intervals**
  supported. The site is already operating near its efficient envelope, so there
  is little real energy headroom to advise on.

See the [decision memo](../product/aopso-health-efficiency-ab/07-decision-memo-A-pass-B-fail.md).

## Decision

**We will ship Pillar A as an offline/advisory health-detection product, and
park Pillar B.**

- Pillar A is packaged for edge advisory serving (PyTorch→ONNX, see
  [ADR-0004](0004-onnx-tflite-advisory-packaging.md)) and remains advisory /
  non-control per [ADR-0001](0001-ot-it-decoupling.md).
- Pillar B is parked as a **sensitivity study** in the Plane backlog
  (AOPSO #44). A scientific FAIL is recorded as evidence, not buried — we may
  revisit if a site with more energy headroom appears.

## Consequences

- **Easier:** A focused, validated product to ship. Honest evidence on Pillar B
  protects credibility and avoids over-promising energy savings that the data
  does not support.
- **Harder:** The near-term commercial story is health detection only; the
  energy-savings narrative is deferred until evidence supports it.

## Alternatives considered

- **Ship Pillar B anyway:** rejected — would advise zero/near-zero opportunity
  on a site near its efficient envelope; not honest and not useful.
- **Block Pillar A on Pillar B:** rejected — Pillar A is independently validated
  and valuable; coupling them delays a real win for a parked one.
