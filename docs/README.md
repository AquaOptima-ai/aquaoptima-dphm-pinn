# AquaOptima Documentation Index

> **Start here.** This is the map to every developer-facing document in the
> AquaOptima dPHM-PINN project. If you are a new developer, read the
> **Day-one** docs top to bottom, then dip into the rest as you touch the
> relevant area.

---

## The three-layer documentation model

We deliberately keep documentation in three places, matched to **who reads it**
and **how fast it changes**. The governing rule is:

> **One fact has exactly one home. Everything else *links* to it — never copies it.**

Copying a fact between layers creates a future lie the moment one copy changes.

| Layer | Lives in | Audience | Changes | Holds |
|---|---|---|---|---|
| **1 — Technical truth (CANONICAL)** | **GitHub** — this repo, in `/docs` | Developers | With the code, via PR | PRD, architecture, ADRs, specs, interfaces, deployment, safety |
| **2 — Operational state (live ledger)** | **Plane** | PM + team, daily | Hourly/daily | Sprint/phase/module status, QA summaries, commit + PR links — *links to these docs, never restates them* |
| **3 — Stakeholder narrative** | **Google Drive (AOPSO Docs)** | Business stakeholders | Per-milestone | Business/investor framing — *links down to this repo for any technical claim* |

If you find the same fact written in two layers, that is a bug. Fix it by
deleting the copy and replacing it with a link to the canonical home.

---

## Day-one reading (every developer)

1. **[`/README.md`](../README.md)** — repo orientation, module map, current status.
2. **PRD** — [`product/aopso-health-efficiency-ab/03-prd.md`](product/aopso-health-efficiency-ab/03-prd.md)
   — the *why* and *what*. See also the
   [decision memo: Pillar A pass / Pillar B fail](product/aopso-health-efficiency-ab/07-decision-memo-A-pass-B-fail.md).
3. **[`architecture.md`](architecture.md)** — system structure and module map.
4. **[`safety-boundary.md`](safety-boundary.md)** — **read this before you write any code.**
   The read-vs-write process boundary; an unsafe write to a live PLC is a
   real-world safety incident, not a software bug.
5. **[Architecture Decision Records](adr/)** — *why* the system is built the way
   it is. Start with [ADR-0001 (OT/IT decoupling)](adr/0001-ot-it-decoupling.md).

---

## Architecture & contracts

- [`architecture.md`](architecture.md) — top-level architecture.
- [`architecture/product-components-3-plus-1.md`](architecture/product-components-3-plus-1.md) — the 3+1 component model.
- [`architecture/component-ownership-matrix.md`](architecture/component-ownership-matrix.md) — who owns what.
- [`architecture/contracts-inventory.md`](architecture/contracts-inventory.md) — contract inventory.
- [`architecture/shared-contracts-sdk.md`](architecture/shared-contracts-sdk.md) — shared contracts SDK.
- [`advisory-contract.md`](advisory-contract.md) — advisory output contract.
- [`learner/advisory_ranking_contract.md`](learner/advisory_ranking_contract.md),
  [`learner/performance_model_contract.md`](learner/performance_model_contract.md).

## Safety & qualification (OT/IT boundary)

- [`safety-boundary.md`](safety-boundary.md) — read-vs-write policy.
- [`safety/capability-model-and-safety-gates.md`](safety/capability-model-and-safety-gates.md).
- [`safety/component-boundaries-and-qualification-gates.md`](safety/component-boundaries-and-qualification-gates.md).

## Hardware & deployment (edge)

- [`hardware/`](hardware/) — AMAX edge feasibility, benchmarking, read-only
  integration, vendor PAC software inventory, HIL plan.
  The canonical edge target is **AMAX-8580** (CPU-only profile
  `amax8580_cpu`); the AMAX-5580→8580 reconciliation is complete (see
  [ADR-0005](adr/0005-amax-5580-to-8580-reconciliation.md)).
- [`deployment/`](deployment/) — Optimizer-Lite readiness, pilot handoff/signoff.
- [`product/aopso-health-efficiency-ab/08-pillarA-linux-deployment-runbook.md`](product/aopso-health-efficiency-ab/08-pillarA-linux-deployment-runbook.md) — Pillar A deployment runbook.

## Product

- [`product/aopso-health-efficiency-ab/`](product/aopso-health-efficiency-ab/) —
  research report, MoSCoW features, PRD, UX/UI, decision memos, runbook.
- [`product/phase2-phase3-3plus1-roadmap.md`](product/phase2-phase3-3plus1-roadmap.md) — roadmap.

## Planning & evaluation

- [`planning/`](planning/) — training plans, profiling, safety-verification
  reviews, evaluation methodology.

## Governance (how we keep docs alive)

- **[`/CONTRIBUTING.md`](../CONTRIBUTING.md)** — workflow, branch strategy, and
  the **same-PR documentation rule**.
- **[`/GLOSSARY.md`](../GLOSSARY.md)** — domain vocabulary (dPHM, PINN, dPL, MPC,
  MG-PID, PAC, EtherCAT, Pillar A/B, advisory, dry-run, evidence).
- **[`adr/`](adr/)** — Architecture Decision Records (append-only, immutable).

---

## Keeping this index current

When you **add or move** a doc, update this index in the **same PR**. An
orphaned doc that is not linked here effectively does not exist for a new
developer.
