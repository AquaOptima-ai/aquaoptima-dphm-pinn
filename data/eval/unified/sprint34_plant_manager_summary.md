# AOPSO Sprint 34 - One-Page Plant-Manager Summary

> **SAFETY:** ADVISORY-ONLY OFFLINE EVIDENCE - NOT FOR ACTUATION OR CONTROL - NO LIVE SITE INTEGRATION - SITE DEPLOYMENT NOT AUTHORIZED IN THIS VERSION

## Product status

**Pillar A validated; Pillar B FAILED its locked-March acceptance gate (honest result). Advisory evidence only; deployment NOT authorized in this version.**

## Pillar A - Health detection (Sprint 30b verdict: PASS)

- AUROC: detector `0.9435953348633261` vs baseline `0.9175359491438111`
- False-alarm rate: detector `0.012800276229467765` vs baseline `0.05179302520593893`
- Mean lead-time (rows): detector `15.821428571428571` vs baseline `4.838709677419355`

## Pillar B - Efficiency advisory (Sprint 33 verdict: FAIL)

- Coverage: `21` supported / `58` total OperatingPoints
- Counterfactual opportunity (supported intervals only): p25 = `0.0` kWh, p10 = `1.3097953444387933` kWh
- Robust under conservative p25 quantile? `False`
- March-observed energy on supported intervals: `498.653777` kWh

## What we **cannot** claim

- We do NOT claim guaranteed energy savings.
- We do NOT claim a deployable control policy.
- We do NOT claim field-validated fault recall or predictive maintenance accuracy.
- We do NOT claim site integration, actuation, or write-path readiness.
- We do NOT claim that an advisory operating point may be used as a setpoint.
- We do NOT claim opportunity on intervals the envelope honestly REJECTED.

## Next step

This is offline evidence only. Any operational change requires future
validation under the same hydraulic constraints and a separate
qualification step. Site integration, actuation, and write-path
deployment are **not authorized** in this version.
