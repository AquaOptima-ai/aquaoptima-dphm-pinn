# ADR-0005: Reconcile AMAX-5580 → AMAX-8580 naming across docs

- **Status:** Accepted
- **Date:** 2026-05-31
- **Owner:** Tech lead
- **Resolved by:** PR #18 (`docs/amax-5580-to-8580-migration`), merged into `main`

## Context

The canonical edge target moved from **AMAX-5580** to **AMAX-8580**
([ADR-0002](0002-amax8580-cpu-only-edge.md)). The repository still carries the
older `AMAX-5580` naming in several places, while newer artifacts already use
`AMAX-8580`. Both strings currently appear across tracked files, e.g.:

- `docs/hardware/amax-5580-*.md` (file names + bodies)
- `README.md`, `SPRINT35_REPORT.md`, `SPRINT36_REPORT.md`
- `data/eval/packaging/*.json`
- `deploy/pillarA_advisory/Dockerfile`

This is a naming/content drift, not a decision change. Leaving it mixed will
confuse the incoming human dev team about which hardware is the real target.

## Decision

**We will reconcile the hardware naming to AMAX-8580 in a dedicated,
separately-reviewed migration PR** — not in this docs-governance change.

The migration will:

1. Rename `docs/hardware/amax-5580-*.md` → `amax-8580-*.md` and update bodies,
   preserving any genuinely 5580-specific historical evaluation as clearly
   dated context.
2. Update `README.md` and packaging artifacts to the 8580 target.
3. Leave **historical sprint reports** (`SPRINT35/36_REPORT.md`) unedited —
   they are an immutable record of what was true at the time.

## Consequences

- **Easier:** A single unambiguous edge target for the new team.
- **Harder:** A focused migration PR with careful review is required so we do not
  rewrite history or break links. This ADR is the tracking record until it lands;
  flip status to `Accepted` and reference the migration PR when done.

## Alternatives considered

- **Silent bulk rename inside this PR:** rejected — content migration across
  7+ files deserves its own reviewed change, and conflating it with docs
  governance hides a meaningful diff.
- **Leave as-is:** rejected — ambiguity about the target hardware is exactly the
  kind of thing that derails new-developer onboarding.
