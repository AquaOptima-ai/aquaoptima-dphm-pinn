# ADR-0002: AMAX-8580 CPU-only edge profile (`amax8580_cpu`)

- **Status:** Accepted
- **Date:** 2026-05-31
- **Owner:** Tech lead

## Context

The edge advisory inference for the legacy pump-station site runs on vendor
hardware. The target edge box is the **AMAX-8580** (updated from the earlier
AMAX-5580 evaluation — see [ADR-0005](0005-amax-5580-to-8580-reconciliation.md)
for the doc reconciliation). AMAX ships distinct SKUs: a *Control IPC Barebone*
and a *CODESYS Ready PAC*. The CODESYS Ready PAC runs Windows 10 LTSC 64-bit
with CODESYS V3 Pure Control + Visu/HMI, 128 GB M.2 storage, and 2 MB NVRAM.

This is a constrained, **CPU-only** environment. There is no GPU, and the
control box must not carry heavyweight or unvetted ML runtimes. Edge software
inventory and feasibility are documented under [`hardware/`](../hardware/).

## Decision

**We will target a CPU-only edge profile, identified as `amax8580_cpu`, for all
edge advisory inference.**

- Inference runtimes are limited to **ONNX Runtime / TFLite (CPU)**.
- The profile **rejects** `pytorch`, `cuda`, `tensorrt`, and `arm64` at the
  edge. These are training-time / non-target dependencies and must not ship to
  the edge box.
- Models are trained in PyTorch off-box and exported for edge serving (see
  [ADR-0004](0004-onnx-tflite-advisory-packaging.md)).

## Consequences

- **Easier:** A small, vetted, CPU-only dependency surface that fits the vendor
  PAC environment and is realistic to qualify. Deployment packaging can assert
  the rejected-runtime list as a hard gate.
- **Harder:** Model architecture and latency budgets are bounded by CPU
  inference. Anything requiring GPU/TensorRT acceleration is out of scope at the
  edge and must run off-box.

## Alternatives considered

- **GPU edge inference:** rejected — no GPU on the target hardware, and adding
  one is outside the legacy-site deployment envelope.
- **Shipping PyTorch to the edge:** rejected — runtime footprint and qualification
  burden are unacceptable on the CODESYS Ready PAC.
