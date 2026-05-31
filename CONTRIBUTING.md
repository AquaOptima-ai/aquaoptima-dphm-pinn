# Contributing to AquaOptima dPHM-PINN

Welcome. This guide is the operating manual for developing in this repo. Read it
once before your first PR, then keep it open as a reference.

## Documentation lives where the code lives

Developer-facing technical documentation is **canonical in this repository**,
under [`docs/`](docs/README.md). We use a three-layer model:

- **GitHub (this repo)** — technical truth: PRD, architecture, ADRs, specs,
  safety, deployment. Canonical.
- **Plane** — the live PM ledger: sprint/phase/module status, QA summaries,
  commit + PR links. Plane **links to** docs here; it does not restate them.
- **Google Drive (AOPSO Docs)** — stakeholder narrative. It **links down** to
  this repo for any technical claim.

> **One fact, one home.** If a fact is written here, do not copy it into Plane or
> Drive — link to it. A copy is a future lie.

Start at the **[documentation index](docs/README.md)**.

## The same-PR documentation rule (load-bearing)

> **A behavior change and its documentation change land in the *same* pull request.**

Not a follow-up ticket, not "docs at end of sprint." The same PR. The cost of
updating the doc is paid by the person who has the context, at the moment they
have it. This is the single most important rule for keeping docs alive.

Enforced three ways:
1. The **PR template** has a "Docs updated?" checkbox.
2. It is in the **Definition of Done** (below).
3. **Reviewers are empowered to block** a PR whose docs are stale.

## Architecture Decision Records

When you make an architecturally significant decision (a boundary, a runtime
constraint, a ship/park call, a contract), record it as an
**[ADR](docs/adr/README.md)**. ADRs are **append-only and immutable**: never
edit an accepted decision — supersede it with a new ADR. During the post-merge
Plane reconciliation we check whether a merged sprint produced a decision that
deserves an ADR.

## Branch & PR workflow

- Branch from `main`. Name branches by intent, e.g.
  `aopso/sprintNN-<topic>`, `docs/<topic>`, `fix/<topic>`.
- Keep PRs focused. A content migration (e.g. a bulk rename) gets its **own** PR,
  separate from feature or governance changes.
- Open a PR against `main` and request review. Do not push directly to `main`.
- Link the PR to its Plane issue; link the Plane issue to the relevant doc section.

## Definition of Done

A change is done when:

- [ ] Tests pass (this project is built sprint-by-sprint via strict TDD).
- [ ] Behavior changes are documented in the **same PR** (or the docs checkbox is
      marked N/A with a reason).
- [ ] Any architecturally significant decision has an ADR.
- [ ] The [docs index](docs/README.md) is updated if docs were added/moved.
- [ ] The **OT/IT boundary** ([ADR-0001](docs/adr/0001-ot-it-decoupling.md)) is
      respected — no code path from advisory output to a controller write.
- [ ] The Plane issue is updated and linked.

## Safety first

Read [`docs/safety-boundary.md`](docs/safety-boundary.md) before writing code.
An unsafe write to a live PLC on a drinking-water network is a real-world safety
incident. AquaOptima is **advisory / non-control**; there is no write path, and
`TagDefinition.writable` defaults to `False`.
