# ADR-0004: PyTorch→ONNX packaging for edge advisory inference

- **Status:** Accepted
- **Date:** 2026-05-31
- **Owner:** Eng

## Context

Models are trained in PyTorch off-box, but the edge target is a CPU-only profile
that rejects the PyTorch/CUDA/TensorRT runtimes ([ADR-0002](0002-amax8580-cpu-only-edge.md)).
We need a packaging path that gets a trained Pillar A health-detection model
([ADR-0003](0003-pillar-a-ship-pillar-b-park.md)) onto the edge as an advisory,
non-control component ([ADR-0001](0001-ot-it-decoupling.md)).

## Decision

**We will export trained PyTorch models to ONNX and serve them on the edge with
ONNX Runtime (CPU).** TFLite is an acceptable alternative CPU runtime within the
`amax8580_cpu` profile.

- Training stays in PyTorch off-box.
- The deployment package is built for `amax8580_cpu` and validated against the
  rejected-runtime gate (no pytorch/cuda/tensorrt/arm64 in the edge package).
- Packaging and the deployment scorecard live under `data/eval/packaging/`; the
  Pillar A deployment runbook is in
  [`product/aopso-health-efficiency-ab/08-pillarA-linux-deployment-runbook.md`](../product/aopso-health-efficiency-ab/08-pillarA-linux-deployment-runbook.md).

## Consequences

- **Easier:** Clean separation between training (PyTorch, off-box) and serving
  (ONNX/TFLite, CPU edge). The package boundary is enforceable.
- **Harder:** Every model op must have an ONNX/TFLite-compatible export; custom
  ops require an export plan. Export parity (PyTorch vs ONNX outputs) must be
  verified as part of packaging.

## Alternatives considered

- **TorchScript / running PyTorch on the edge:** rejected by
  [ADR-0002](0002-amax8580-cpu-only-edge.md) — runtime footprint and the
  rejected-runtime policy.
- **A bespoke inference runtime:** rejected — needless qualification burden when
  ONNX Runtime / TFLite already meet the CPU-only constraint.
