# Sprint 21 Report — Explicit EPANET Ignored-Section Contract

## Goal

Make the fallback EPANET `.inp` parser's ignored-section behaviour
**explicit, tested, and documented** for the common EPANET sections
that fall outside the current steady-state Hazen-Williams dPHM
scope. Sprint 17–20 hardened the parser's `[OPTIONS]` scalar surface
(pressure units, demand multiplier, specific gravity, viscosity).
Sprint 21 does not add new hydraulics; it pins the contract that
tolerated sections are intentionally dropped and cannot leak rows
into active sections.

## Verdict

**APPROVED.**

All Sprint 21 hard approval gates and the WNTR-installed additional
gate pass; see "Validation results" below.

## Files changed

| File                                                | Change                                                                                                                                            |
|-----------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------|
| `src/aquaoptima/dphm/inp_io.py`                     | Promoted `_IGNORED_SECTIONS` to the public `IGNORED_SECTIONS` frozenset, exported in `__all__`. Kept `_IGNORED_SECTIONS` as a backwards-compatible alias. Expanded the module docstring with a Sprint 21 paragraph and documented the explicit no-op contract / limitations in a long block comment next to the constant. |
| `docs/epanet-inp-import.md`                         | Updated title and lead paragraph for Sprint 21. Added a new "Ignored sections (Sprint 21)" section enumerating every target section, the contract, the documented `[CONTROLS]` / `[RULES]` limitation, the WNTR adapter notes, and the test surface. |
| `tests/dphm/test_inp_ignored_sections.py` (new)     | 65 new tests pinning the ignored-section contract.                                                                                                |
| `SPRINT21_REPORT.md` (new)                          | This report.                                                                                                                                       |

No production hydraulic code was changed. No new shipped fixtures
were added (the inline `tmp_path` fixtures in the new test file are
sufficient to cover the contract).

## Ignored-section design

The frozenset `aquaoptima.dphm.inp_io.IGNORED_SECTIONS` is the
public surface for the no-op contract. The constant is
**documentation as code**: the parser does *not* branch on
membership at any point. `_fallback_parse` only ever reads the
hydraulically-meaningful sections (`[OPTIONS]`, `[JUNCTIONS]`,
`[RESERVOIRS]`, `[TANKS]`, `[PIPES]`, `[PUMPS]`, `[VALVES]`,
`[CURVES]`); every other section header is tokenised by
`_split_sections` and then simply never consumed. Promoting the
constant to a public surface makes the explicit list inspectable by
external code (and the test suite), and pins the contract against
silent regression.

### Sprint 21 target sections (full no-op coverage)

The nine sections enumerated in the sprint brief:

```
[TIMES] [REPORT] [CONTROLS] [RULES] [EMITTERS]
[QUALITY] [SOURCES] [REACTIONS] [MIXING]
```

All nine were already present in the pre-Sprint-21
`_IGNORED_SECTIONS` constant; Sprint 21 ships explicit tests that
confirm the contract holds, plus the public export so external code
can introspect it.

### Other sections in `IGNORED_SECTIONS`

The constant also lists the inert layout / annotation sections
(`[TITLE]`, `[END]`, `[PATTERNS]`, `[COORDINATES]`, `[VERTICES]`,
`[LABELS]`, `[BACKDROP]`, `[TAGS]`, `[ENERGY]`, `[STATUS]`,
`[DEMANDS]`). These were already silently dropped pre-Sprint-21;
Sprint 21 documents them in the public docstring/table but does not
add new test coverage for them beyond the surface check.

### Why `[CURVES]` is NOT in `IGNORED_SECTIONS`

Sprint 12 consumes `[CURVES]` when a `[PUMPS]` row references a
HEAD curve. The Sprint 21 test
`test_curves_is_not_globally_ignored` pins this distinction so
future refactors cannot promote `[CURVES]` to a no-op by accident.
A separate test
`test_head_pump_unaffected_by_simultaneous_ignored_sections`
appends every target ignored section to a HEAD-curve fixture and
confirms the fitted pump coefficients are still byte-for-byte
identical.

## Fallback parser behaviour

The fallback parser handles ignored sections through a two-stage
mechanism:

1. **Tokenisation (`_split_sections`).** Every section header is
   recognised; every non-blank, non-comment row inside a section is
   tokenised on whitespace and appended to the section's row list.
   This step does not validate row shape against the section.

2. **Per-section consumption (`_fallback_parse`).** The parser
   explicitly reads `sections.get(name, [])` for the eight
   hydraulically-active section names listed above. Every other
   section's rows sit in the `sections` dict untouched.

Consequences pinned by Sprint 21 tests:

- Ignored sections can appear anywhere in the file (before, after,
  or interleaved with hydraulic sections) without affecting parsing.
- Ignored sections can be repeated — a second `[CONTROLS]` header
  just continues appending rows to the same dict entry, and the
  parser never reads it.
- Malformed-looking rows inside ignored sections (non-numeric
  fields, unknown node references, extra columns) are tolerated
  silently.
- `[CONTROLS]` / `[RULES]` rows that would close a link, change a
  pump speed, or modify a fixed-head boundary are *dropped*, not
  enforced. This is the explicit Sprint 21 limitation.

## WNTR behaviour

Sprint 21 documents but does **not** enforce WNTR-side handling of
the target ignored sections. WNTR 1.4 has its own (stricter)
parsers for several of them:

- `[MIXING]` is validated against the network's tank registry —
  injecting a `T1 MIXED` row into a fixture that has no `T1` tank
  raises a `KeyError` from WNTR.
- `[CONTROLS]` and `[RULES]` are validated against link / node
  references and active-control state.
- `[QUALITY]`, `[SOURCES]`, `[REACTIONS]` are parsed into WNTR's
  water-quality model.

Because the dPHM importer's contract is about *our* parser's
behaviour (not WNTR's), the Sprint 21 WNTR smoke test
(`test_wntr_smoke_ignored_sections_do_not_break_back_end`) limits
itself to the subset WNTR is happy to round-trip:

- `[TIMES]` and `[REPORT]` are accepted unconditionally by WNTR
  (simulation / output settings).
- `[QUALITY]` against an existing node (`J1`) is accepted.

For that subset, the WNTR-backed `Network` agrees with the fallback
`Network` on demand sum, node count, and edge count, which is the
property the dPHM importer cares about.

WNTR-ambiguous sections (those WNTR validates against the network)
are documented in `docs/epanet-inp-import.md` § "Ignored sections"
and listed here as a known asymmetry rather than an enforced
contract.

## Test / invariance evidence

`tests/dphm/test_inp_ignored_sections.py` ships 65 new tests
covering eight invariance / surface dimensions:

| Test group                                                    | Count | What it pins                                                                                          |
|---------------------------------------------------------------|-------|-------------------------------------------------------------------------------------------------------|
| `IGNORED_SECTIONS` public surface (per-target + non-target)   | 18    | Every target section is on the public surface; no hydraulically-active section is on it; immutability. |
| Per-section invariance (each of 9 targets)                    | 9     | Adding the section to the baseline leaves the loaded `Network` byte-for-byte unchanged.                |
| All targets at once invariance                                | 1     | Stacking all 9 target sections into one file still yields an identical `Network`.                       |
| Position invariance (before / after hydraulic sections)        | 18    | Section placed before `[JUNCTIONS]` does not block parsing; section placed after `[OPTIONS]` does not mutate already-parsed values. |
| Malformed-row tolerance (per-section)                         | 9     | Unknown-node refs, non-numeric fields, extra columns inside ignored sections do not raise.             |
| Documented `[CONTROLS]` / `[RULES]` limitation                | 2     | Control / rule rows that would close a link are dropped; the loaded network and Newton-solve state are unchanged. |
| `[CURVES]` active vs ignored sections                          | 2     | `[CURVES]` consumption still works; HEAD-pump fixture is invariant under simultaneous ignored sections. |
| Valve invariance (PRV, TCV) under all ignored sections         | 2     | PRV pressure-boundary and TCV resistance surrogates produce identical outputs with / without noise.    |
| Interleaved layout, repeated `[CONTROLS]` headers              | 2     | Real EPANET-emitter layouts and exporter quirks accepted.                                              |
| Optional WNTR smoke check                                     | 1     | Fallback / WNTR back-ends agree on demand sum + node / edge counts for the WNTR-compatible subset.     |
| Helper checks (frozenset type, total)                          | 1     | Constant is a `frozenset` (immutable).                                                                 |
| **Total**                                                     | **65** |                                                                                                       |

Equality is asserted with `_assert_networks_identical`, which checks
node count, edge count, fixed-head count, `edge_index`,
`pipe_mask`, `pump_mask`, `fixed_head_mask`, plus tensor equality on
`demands`, `fixed_head_values`, `lengths`, `diameters`,
`c_factors`, `pump_speeds` (all `atol = 0`, bit-exact — a single
conversion path per file column means the same row must give the
same bytes) and `pump_coeffs` (`atol = rtol = 1e-9`). The slightly
relaxed tolerance on `pump_coeffs` absorbs `torch.linalg.lstsq`
multi-threaded BLAS scheduling noise (~1e-14 ULP-level drift in the
near-zero `a1` term on the shipped HEAD-pump fixture) while
catching any real algorithmic drift.

For the documented `[CONTROLS]` limitation, the test additionally
runs `newton_solve` on both networks and asserts `heads` agree to
`1e-9` m and `flows` to `1e-12` m³/s — pinning the *behaviour*, not
just the loaded data.

## Validation commands and results

```bash
python -m pip install -e .                                                          # OK
python -m pytest tests/dphm tests/models tests/training tests/dataio -q             # 900 passed, 1 skipped
python -m pytest tests -q                                                           # 908 passed, 1 skipped
python -m compileall src tests                                                      # clean
git status --short                                                                  # only intended Sprint 21 changes
```

Sprint 20 numbers for comparison:

- targeted: 835 passed, 1 skipped → Sprint 21: 900 passed, 1 skipped
  (+65 new tests, all passing; no regressions).
- full: 843 passed, 1 skipped → Sprint 21: 908 passed, 1 skipped
  (+65 new tests, all passing; no regressions).
- compileall: clean → clean.

WNTR 1.4.0 is installed in the verification environment; the
WNTR-marked tests run rather than skip and pass cleanly.

### `git status --short` (final)

```
 M docs/epanet-inp-import.md
 M src/aquaoptima/dphm/inp_io.py
?? tests/dphm/test_inp_ignored_sections.py
?? SPRINT21_REPORT.md
```

Three intended files (one new test, one parser edit, one docs edit)
plus this report. No secret files, no accidental binary blobs, no
unrelated drift.

## Compatibility notes

- The public `IGNORED_SECTIONS` constant is a new export. The
  underscored alias `_IGNORED_SECTIONS` is preserved for any
  hypothetical downstream that imported the private name.
- No existing fixture, helper, resolver, or back-end was changed.
- Sprint 11 / 16 / 17 / 18 / 19 / 20 fixture behaviour is preserved
  (verified by re-running every prior test module).
- HEAD pump (Sprint 12), POWER pump (Sprint 14), PRV / TCV valves
  (Sprint 15), GPM / US-customary fixtures (Sprint 16), `[OPTIONS]
  Pressure` (Sprint 17), Demand Multiplier (Sprint 18), Specific
  Gravity (Sprint 19), Viscosity (Sprint 20) all still pass.
- WNTR-optional tests still skip cleanly when WNTR is uninstalled
  (no path was added that imports WNTR at module load time).

## Known limitations (Sprint 21)

Pinned explicitly by tests and / or documented in
`docs/epanet-inp-import.md`:

1. **`[CONTROLS]` and `[RULES]` are dropped, not enforced.** A
   control rule that closes a pipe at a given time / pressure does
   *not* affect the loaded `pipe_mask` or any link's status. The
   dPHM steady-state core does not model active controls. Importing
   EPANET fixtures whose hydraulics depend on control logic will
   not reproduce EPANET's solved state.
2. **`[EMITTERS]` is dropped.** Pressure-driven leakage / emitter
   demand is not modelled by the Hazen-Williams steady-state core.
3. **`[QUALITY]`, `[SOURCES]`, `[REACTIONS]`, `[MIXING]` are
   dropped.** Water-quality transport is out of scope for the
   current core; the relevant advection-reaction physics is not
   present.
4. **`[STATUS]` is dropped.** Initial open / closed status overrides
   are ignored. The steady-state core models OPEN pipes only;
   `[PIPES]` rows with `CLOSED` / `CV` status still raise
   `ValueError` as before.
5. **`[ENERGY]` is dropped.** Energy-cost coefficients are not
   modelled. Deferred along with active controls.
6. **`[PATTERNS]` is dropped.** Time-varying demand patterns are
   out of scope; the dPHM core is steady-state. Sprint 18's
   `Demand Multiplier` scalar remains the only honoured demand
   scaling.
7. **WNTR-side handling of ignored sections is asymmetric.** WNTR
   1.4 validates several of the target sections against the
   network's tank / link / node registries and may raise where the
   fallback parser would silently drop. Sprint 21 does not try to
   normalise this; the WNTR smoke test covers only the
   round-trippable subset.

## Sprint 22 recommendation

The hardening track on `[OPTIONS]` scalar surface and parser
boundary explicitness is now complete (Sprints 17–21). The next
high-value, low-physics-risk steps live on **one** of two axes;
recommend picking exactly one for Sprint 22:

1. **Honour `[STATUS]` for `OPEN` overrides on existing edges
   (parser-only).** EPANET emits `[STATUS]` rows on rows that are
   *already* `OPEN` in `[PIPES]` for legibility; the parser can
   accept and validate these as no-ops while still rejecting
   `CLOSED` overrides on `OPEN` pipes. Small, dependency-free,
   pinable with the Sprint 21 invariance test pattern. **Recommended
   as the Sprint 22 default — same risk profile as Sprint 21.**

2. **Active `[CONTROLS]` line-status state at parse time (`OPEN`
   only).** A `[CONTROLS]` row like `LINK P1 OPEN AT TIME 0` is a
   degenerate case — the pipe is already `OPEN`. Detect that
   specific shape, validate it, and continue. Do NOT yet honour
   `CLOSED` rules, time-varying clocktimes, or pressure-trigger
   rules; those still need the steady-state-vs-controls boundary
   resolved.

Both keep the steady-state Hazen-Williams scope intact and reuse
the Sprint 21 test pattern (load fixture, perturb, assert
`Network` invariance). Neither requires WNTR. Avoid touching real
EPANET runtime, write paths, or active-controls physics until a
dedicated controls-physics sprint is scoped.

Out-of-scope reminders (still deferred, unchanged from prior
sprints):

- no Darcy-Weisbach branch
- no real EPANET binary / runtime
- no PLC / PAC / SCADA adapters
- no `[PATTERNS]` time-varying demand
- no `[ENERGY]` parsing
- no new pump forms (`SPEED`, `LINEAR`, efficiency curves)
- no new valve forms (`FCV`, `PSV`, `PBV`, `GPV`)
- no dPL parameter learning
- no ONNX / TensorRT / Jetson deployment
- no production / savings claims
