# Product Operating Model: GitHub + Plane

## Ownership split

Use GitHub and Plane together, with clear ownership boundaries:

- **GitHub** is the source of truth for durable product, technical, architecture, safety, validation, deployment, and code documentation.
- **Plane** is the source of truth for execution state: sprint progress, phase tracking, module ownership, prompt/completion notes, QA summaries, commit links, PR links, and blockers.

## GitHub responsibilities

Store canonical, reviewable, versioned documentation in the repository:

- PRD and product roadmap.
- Architecture and model design.
- Safety boundary and safety contracts.
- Validation methodology and acceptance criteria.
- Deployment and edge/PAC qualification plans.
- Sprint reports and implementation docs.

GitHub documents must be maintained through branches and pull requests so changes can be reviewed, diffed, and tied to code.

## Plane responsibilities

Use Plane as the live management ledger:

- **Cycles** represent roadmap phases.
- **Modules** represent product subsystems.
- **Issues** represent sprints or product-document work items.
- **Comments/notes** record CrewAI prompts, worktree/branch/process metadata, verification summaries, commit SHAs, PR links, known limitations, and next recommendations.

Plane should link to canonical GitHub docs rather than duplicate them as the long-term source of truth.

## Traceability pattern

For each sprint:

1. Plane issue tracks status, phase, module, prompt, and execution notes.
2. Git branch/commit/PR contains code, tests, docs, and `SPRINTNN_REPORT.md`.
3. Canonical docs under `docs/` capture durable product/architecture/safety/validation knowledge.

Recommended links in each Plane sprint issue:

- branch: `sprintNN`
- PR: `https://github.com/AquaOptima-ai/aquaoptima-dphm-pinn/pull/new/sprintNN`
- report: `SPRINTNN_REPORT.md`
- prompt path: `/home/hunter_lin/projects/dphm-pinn-research/sprint_prompts/sprintNN_claude_prompt.md` when available
- product docs touched or relevant

## Current phase/module convention

- Phase 1 — Foundation + EPANET Diagnostics: Sprints 1-33.
- Phase 2 — Shadow-mode MVP: Sprints 34-39.
- Phase 3 — Advisory / Supervised Control: Sprints 40-51.
- Phase 4 — Qualified PAC-like Edge: Sprints 52-70.

Modules:

- Core dPHM Physics.
- dPHM-PINN / ML Model.
- EPANET / WNTR Import.
- Diagnostics / Import Quality.
- Telemetry / Tag Mapping.
- Shadow Replay / Evaluation.
- Safety / Advisory Contract.
- Control / PAC Edge Runtime.
