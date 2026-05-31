# Architecture Decision Records (ADRs)

An ADR captures **one architecturally significant decision**: the context that
forced it, the decision itself, and the consequences we accept by making it.

## Rules

1. **One decision per file**, numbered sequentially: `NNNN-short-title.md`.
2. **Append-only and immutable.** Never edit an *accepted* decision to change
   its meaning. If a decision changes, write a **new** ADR that *supersedes*
   the old one, and set the old one's status to `Superseded by ADR-NNNN`.
   Preserving the trail is the whole point — it is how a new developer learns
   *why* without a meeting.
3. **Status** is one of: `Proposed`, `Accepted`, `Superseded by ADR-NNNN`,
   `Deprecated`.
4. Keep each ADR to roughly **one page**. Link out to specs/docs for detail.

## Format

Use [`template.md`](template.md): **Context → Decision → Consequences → Status**.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-ot-it-decoupling.md) | OT/IT decoupling — AquaOptima is an advisory sidecar | Accepted |
| [0002](0002-amax8580-cpu-only-edge.md) | AMAX-8580 CPU-only edge profile (`amax8580_cpu`) | Accepted |
| [0003](0003-pillar-a-ship-pillar-b-park.md) | Ship Pillar A (health); park Pillar B (efficiency) | Accepted |
| [0004](0004-onnx-tflite-advisory-packaging.md) | PyTorch→ONNX packaging for edge advisory inference | Accepted |
| [0005](0005-amax-5580-to-8580-reconciliation.md) | Reconcile AMAX-5580 → AMAX-8580 naming across docs | Proposed |
