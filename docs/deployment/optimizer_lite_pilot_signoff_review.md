# Optimizer Lite pilot package signoff review

Date: 2026-05-27

## Decision

**Approved for internal pilot-review package signoff.**

This signoff approves the merged Optimizer Lite bundle as the baseline package for internal/customer-facing pilot review, replay demo, and shadow-mode preparation.

It does **not** approve live OT deployment, PLC/PAC/SCADA writes, learner control, replacement of the commissioned MVP controller, or customer production acceptance.

## Package identity

```text
AquaOptima Pump Station Optimizer Lite — Pilot Review Package v0.1
```

Repository branch:

```text
origin/main
```

Mainline head at review:

```text
fb95ef9 docs: add optimizer lite merge audit
```

Core package commits contained in main:

- `ec4f160 feat: add shadow pump performance model`
- `83cdd9f feat: add advisory ranking shadow evidence`
- `b422a03 feat: add console evidence API`
- `c7ec812 feat: add optimizer lite deployment readiness gate`
- `c160798 docs: add optimizer lite pilot handoff checklist`

## Signoff evidence

Commands run from `main`:

```bash
python -m compileall -q aquaoptima_lite tests scripts
python -m pytest tests/unit tests/contract tests/replay -q
python scripts/check_optimizer_lite_readiness.py \
  --config config/examples/legacy_station_001.yaml \
  --replay tests/fixtures/replay/legacy_station_replay.jsonl \
  --cycles 4
python scripts/run_optimizer_lite_demo.py \
  --config config/examples/legacy_station_001.yaml \
  --replay tests/fixtures/replay/legacy_station_replay.jsonl \
  --cycles 4 \
  --learner-shadow \
  --learner-performance-shadow \
  --advisory-ranking-shadow
```

Results:

```text
tests/unit tests/contract tests/replay: 44 passed
SIGNOFF_READINESS_OK ready_for_pilot_review 4
SIGNOFF_DEMO_OK
SIGNOFF_SECRET_FLAGS 0
SIGNOFF_NO_WRITE_FLAGS 0
SIGNOFF_DOC_MISSING 0
```

Readiness summary:

```text
status=ready_for_pilot_review
audit_count=4
read_only=true
influences_control=false
console evidence endpoint present=true
```

Demo evidence remains intentionally conservative on the current small replay fixture:

```text
learner_shadow=insufficient_data
performance_model readiness=insufficient_data
advisory_ranking readiness=insufficient_data
influences_control=False
```

This is acceptable for signoff because the package is approved for pilot review and shadow-preparation evidence, not learned control or production optimization claims.

## Safety boundary signed off

The signoff is conditional on preserving these boundaries:

- No learner/AI/Console direct write path.
- No uncontrolled or newly introduced PLC/PAC/SCADA write path.
- No live OT binding introduced by this package.
- No command emission from learner, advisory, Console, or readiness paths.
- No setpoint output from learner, advisory, Console, or readiness paths.
- Existing commissioned MVP baseline control remains authority/fallback.
- Manual mode, trips, interlocks, and authority gate remain binding.

## Approved use

Approved:

1. Internal pilot-review demo.
2. Customer-facing technical walkthrough, if clearly framed as evidence/readiness package.
3. Replay-based demo using provided or future approved site-data replay files.
4. Shadow-mode preparation planning.
5. Review of Console evidence endpoint payload shape.
6. Site tag-map/unit/data-readiness discussion.

Not approved by this signoff:

1. Live OT deployment.
2. Any learner/advisory/Console direct write to PLC/PAC/SCADA/VFD.
3. Enabling learned advisory to influence control.
4. Replacing the commissioned MVP controller.
5. Production acceptance or commercial go-live.
6. Any use of customer data outside agreed data policy.

## Open conditions before field/shadow trial

Before any field-connected shadow trial, confirm:

1. Real site tag map and units against actual station telemetry.
2. Customer/site data policy for replay and audit evidence.
3. Location and retention rules for audit SQLite/output artifacts.
4. Which machine hosts the runtime/API during the pilot review.
5. Who reviews evidence and signs off on each pilot step.
6. That all learner/advisory/Console paths remain read-only/evidence-only.

## Recommended next track

Recommended next work item:

```text
CAP — Site-data ingestion and configuration hardening for Optimizer Lite pilot
```

Keep it as a Backlog/Candidate capability until real site tag-map/data-policy details are confirmed. Do not assign another numeric sprint until scope, acceptance criteria, and pilot data inputs are execution-ready.

Alternative tracks:

- `CAP — Operations Console productization` in a separate product/repo/container.
- `SPIKE — Real-site replay fixture expansion` if more data must be collected first.
- `TASK — Pilot package demo script and walkthrough` if business review is the immediate next step.
