<!--
PR template — see CONTRIBUTING.md for the same-PR documentation rule.
-->

## Summary

<!-- What does this PR do and why? Link the Plane issue. -->

Plane issue:

## Type of change

- [ ] Feature
- [ ] Fix
- [ ] Refactor
- [ ] Docs / governance
- [ ] Content migration (own PR — not mixed with feature/governance)

## Documentation

- [ ] Docs updated **in this PR** for any behavior change, **or** N/A because:
      <!-- reason -->
- [ ] An ADR was added/updated for any architecturally significant decision
      (or N/A)
- [ ] [`docs/README.md`](../docs/README.md) index updated if docs were added/moved

## Safety (OT/IT boundary)

- [ ] No code path connects advisory output to a controller write
      (see [ADR-0001](../docs/adr/0001-ot-it-decoupling.md) and
      [`docs/safety-boundary.md`](../docs/safety-boundary.md))
- [ ] `TagDefinition.writable` defaults preserved (no wholesale site-level write)

## Definition of Done

- [ ] Tests pass (TDD)
- [ ] Plane issue updated and linked
- [ ] Reviewer can verify the claims above
