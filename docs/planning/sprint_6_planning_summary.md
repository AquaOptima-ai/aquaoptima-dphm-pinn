# Pump Station Optimizer Lite — Sprint 6 Planning Summary

Sprint 6 is a **planning-only** sprint. It uses CrewAI to turn the completed Sprint 2–5 runtime foundation into implementation-ready plans for Sprints 7–10. It intentionally does **not** implement production code, schema changes, API changes, tests, deployment scripts, or learner/advisory behavior.

## Sprint 6 outputs

- `docs/planning/sprint_6_backlog_sprints_7_10.md`
- `docs/planning/sprint_6_technical_implementation_plan.md`
- `docs/planning/sprint_6_safety_verification_review.md`

## Planned implementation sequence

1. **Sprint 7 — Shadow learned pump/combination performance model**
   - Build a simple local performance model from accepted learner samples.
   - Remains shadow-only with `influences_control=False`.

2. **Sprint 8 — Learned advisory ranking and baseline comparison**
   - Rank safe candidate pump/combo options as advisory evidence.
   - Compare learned advisory against deterministic baseline without replacing it.

3. **Sprint 9 — Operations Console evidence/API expansion**
   - Add read-only evidence APIs for learning status, advisory comparison, recent audit evidence, and savings evidence.
   - GET-only; no command semantics.

4. **Sprint 10 — Packaging, deployment readiness, and site-data readiness gate**
   - Prepare a single-station shadow/advisory pilot package.
   - Validate site-data readiness and deployment profile without live actuation.

## Safety decision

Proceed to **Sprint 7 only** after Sprint 6 planning approval. Do not chain Sprint 8–10 automatically; each depends on the previous sprint's verification gate.

Non-negotiable boundary:

```text
learner/advisory shadow-only
baseline remains control reference
no PLC/PAC/SCADA write path
no autonomous control qualification
```

Any request to allow learned/advisory output to control equipment, override deterministic baseline behavior, bypass quality/authority/manual/trip/alarm/interlock protections, or write to PLC/PAC/SCADA is a hard no-go and must move to a separately scoped safety-qualified release.
