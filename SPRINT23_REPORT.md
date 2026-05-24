# Sprint 23 Report — Read-only EPANET `[STATUS]` diagnostics

## Goal

Expose accepted `[STATUS] OPEN` declarations from imported EPANET
`.inp` files as **read-only diagnostics metadata**, on top of the
Sprint 22 validated-no-op behaviour. The diagnostics path must not
change any hydraulic field on the loaded `Network`, must preserve
the Sprint 22 rejection contract for status-changing rows, and must
keep `load_network_from_inp(path)` backward-compatible.

## Files changed

| Path                                                                       | Change                                                                                                                                                          |
|----------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `src/aquaoptima/dphm/inp_io.py`                                            | Added `EpanetStatusDiagnostic` + `EpanetImportDiagnostics` frozen dataclasses; rewired `_validate_status_rows` to return accepted-row diagnostics; refactored `_fallback_parse` and `_wntr_parse` to return `(Network, EpanetImportDiagnostics)`; split kwarg validation into `_dispatch_inp_parse`; added new public `load_inp_diagnostics(...)` accessor and `return_diagnostics` flag on `load_network_from_inp`. |
| `src/aquaoptima/dphm/__init__.py`                                          | Re-exported `EpanetImportDiagnostics`, `EpanetStatusDiagnostic`, `load_inp_diagnostics` at the top-level `aquaoptima.dphm` namespace.                                                                                                                                                       |
| `docs/epanet-inp-import.md`                                                | Title bumped to Sprint 11–23; added Sprint 23 preamble; added new "Read-only `[STATUS]` diagnostics (Sprint 23)" section with public-API examples, dataclass shape, hydraulic-inertness statement, WNTR back-end asymmetry, and test list.                                          |
| `tests/dphm/test_inp_status_diagnostics.py`                                | New test module pinning the Sprint 23 contract end-to-end (39 tests).                                                                                                                                                                                                                       |
| `SPRINT23_REPORT.md`                                                       | This report.                                                                                                                                                                                                                                                                                |

No fixture files added, no Python dependencies changed, no
secrets introduced.

## Diagnostics API design

```python
from aquaoptima.dphm import (
    EpanetImportDiagnostics,
    EpanetStatusDiagnostic,
    load_inp_diagnostics,
    load_network_from_inp,
)
```

Two equally-valid entry points:

```python
# A) Explicit, read-only diagnostics accessor.
diagnostics = load_inp_diagnostics(path, parser="fallback")
for row in diagnostics.status_rows:
    print(row.link_id, row.status, row.is_noop, row.message)

# B) One call returning both the Network and the diagnostics.
network, diagnostics = load_network_from_inp(
    path, parser="fallback", return_diagnostics=True,
)
```

`load_network_from_inp(path)` (without `return_diagnostics=True`)
**continues to return only a `Network`** — Sprint 11–22 callers
need no changes.

Dataclasses (both `frozen=True`):

```python
@dataclass(frozen=True)
class EpanetStatusDiagnostic:
    link_id: str            # echoed verbatim from the source file
    status: str             # normalised, e.g. "OPEN"
    section: str = "STATUS"
    is_noop: bool = True
    message: str = "OPEN accepted as a no-op; status-changing semantics are unsupported."


@dataclass(frozen=True)
class EpanetImportDiagnostics:
    status_rows: tuple[EpanetStatusDiagnostic, ...] = ()
```

`status_rows` is a `tuple` (not a list); both dataclasses raise
`dataclasses.FrozenInstanceError` on attempted reassignment so the
surface is structurally read-only.

## Fallback parser behaviour

- `_validate_status_rows(rows, known_link_ids)` now returns a
  `tuple[EpanetStatusDiagnostic, ...]` containing exactly one record
  per accepted `<link_id> OPEN` row. The link id is preserved
  verbatim from the source file; the status token is normalised to
  upper-case `"OPEN"`; the row count and order match the source
  `[STATUS]` block.
- Rejected rows (`CLOSED`, `CV`, numeric, unknown id, short row,
  arbitrary token) still raise `ValueError` **before** any
  diagnostic is appended. A block mixing `OPEN` and `CLOSED` rows
  raises with no partial diagnostics leaked.
- `_fallback_parse(...)` now returns `(Network, EpanetImportDiagnostics)`.
  The `Network` it builds is **identical to the Sprint 22
  byte-for-byte network** — the diagnostics are computed alongside
  but never mutate any hydraulic field.

## WNTR back-end behaviour

- `_wntr_parse(...)` was extended to return
  `(Network, EpanetImportDiagnostics)` so the API surface is
  uniform across back-ends.
- The dPHM WNTR adapter **does not** re-parse `[STATUS]` — WNTR has
  its own `[STATUS]` parser that handles closed-link state inside
  the WNTR engine — so the diagnostics container returned by the
  WNTR back-end is always empty.
- This documented asymmetry matches the Sprint 22 split: the
  fallback parser is authoritative for `[STATUS]` semantics in
  dPHM. The optional WNTR smoke test in
  `tests/dphm/test_inp_status_diagnostics.py` only asserts the
  WNTR API does not raise and returns the read-only container
  shape; it does not require parity with the fallback diagnostics.

## Read-only / hydraulically-inert evidence

The Sprint 23 test suite explicitly proves the no-op contract:

- `test_status_diagnostics_do_not_change_network` — loads a fixture
  with `[STATUS] P1 OPEN P2 OPEN` and a baseline fixture without
  `[STATUS]`; uses the same `_assert_networks_identical` helper as
  the Sprint 22 tests to confirm `num_nodes`, `num_edges`,
  `num_fixed_heads`, `edge_index`, `pipe_mask`, `pump_mask`,
  `fixed_head_mask`, `demands`, `fixed_head_values`, `lengths`,
  `diameters`, `c_factors`, `pump_speeds`, and `pump_coeffs` are
  byte-for-byte identical.
- `test_return_diagnostics_network_matches_default_load` — confirms
  the `Network` returned by `load_network_from_inp(..., return_diagnostics=True)`
  is identical to the one returned by the default
  `load_network_from_inp(...)`.
- `test_load_inp_diagnostics_does_not_return_network` — confirms
  the diagnostics accessor returns only `EpanetImportDiagnostics`,
  never a `Network`.
- `test_diagnostics_dataclass_is_frozen` and
  `test_diagnostics_container_is_frozen_and_uses_tuple_storage`
  — confirm `FrozenInstanceError` on attempted reassignment and
  tuple-backed storage.

## Tests added / updated

**Added:** `tests/dphm/test_inp_status_diagnostics.py` — 39 tests:

- public-surface checks (dataclasses are importable, frozen, use a
  tuple-backed container; `load_inp_diagnostics` is callable);
- accepted-row records for pipes (`P1 OPEN`), HEAD-curve pumps
  (`PU1 OPEN` and `PU1 open`), PRV valves (`V1 OPEN`);
- case-insensitive `OPEN` normalisation; link id casing preserved;
- multiple-row count + order invariance; mixed pipe + pump in one
  block;
- empty diagnostics for files with no `[STATUS]` and for an empty
  `[STATUS]` section;
- byte-for-byte `Network` equality between default and
  `return_diagnostics=True` loads; byte-for-byte equality between
  fixtures with and without `[STATUS]`;
- backwards compatibility: default `load_network_from_inp(path)`
  returns only `Network` (with and without `[STATUS]` in the file,
  with explicit `return_diagnostics=False`);
- every Sprint 22 rejection (CLOSED / closed / CV / 1.0 / 0 /
  unknown id / arbitrary token / short row) still raises through
  both `load_inp_diagnostics` and `load_network_from_inp(..., return_diagnostics=True)`;
  error messages still name the offending token / id;
- mixed OPEN+CLOSED block raises with no partial diagnostics
  leaked (asserted on both the diagnostics accessor and the
  diagnostics-with-network entry point);
- `[CONTROLS]` and `[RULES]` content does **not** appear in
  diagnostics, even in files that also declare `[STATUS] OPEN`;
- parser selector + units kwargs reach the diagnostics path
  (unknown parser / non-SI units raise);
- optional WNTR back-end smoke check (`pytest.importorskip("wntr")`)
  — confirms the WNTR API does not raise and returns the read-only
  container shape.

**Unchanged but re-validated:** all 938 Sprint 11–22 tests
continue to pass; total 977 passed, 1 skipped (same Sprint 22
WNTR-ImportError-path skip; the rest of the WNTR optional suite
passes because `wntr==1.4.0` is installed in this env).

## Validation commands and results

```bash
$ python -m pip install -e .
Successfully installed aquaoptima-dphm-pinn-0.1.0

$ python -m pytest tests/dphm tests/models tests/training tests/dataio -q
969 passed, 1 skipped, 3 warnings in 96.23s (0:01:36)
SKIPPED [1] tests/dphm/test_wntr_optional_import.py:371: WNTR is installed; ImportError path not exercised here

$ python -m pytest tests -q
977 passed, 1 skipped, 3 warnings in 86.54s (0:01:26)
SKIPPED [1] tests/dphm/test_wntr_optional_import.py:371: WNTR is installed; ImportError path not exercised here

$ python -m compileall -q src tests
rc=0  # exit clean

$ git status --short
 M docs/epanet-inp-import.md
 M src/aquaoptima/dphm/__init__.py
 M src/aquaoptima/dphm/inp_io.py
?? tests/dphm/test_inp_status_diagnostics.py
?? SPRINT23_REPORT.md   # this file
```

All four worktree changes are deliberate Sprint 23 changes. No
secret-looking strings introduced; no unexpected files; no
modifications to existing fixtures or to `pyproject.toml`.

## Compatibility notes

- `load_network_from_inp(path)` is **fully backward-compatible**.
  The new `return_diagnostics` keyword defaults to `False` and the
  default return shape is unchanged.
- `Network` shape is **unchanged** — diagnostics do not attach
  state to `Network`.
- `IGNORED_SECTIONS` is **unchanged** — `STATUS` remains *outside*
  the set, exactly as Sprint 22 left it. `[CONTROLS]` and
  `[RULES]` remain documented limitations.
- The fallback parser is authoritative for `[STATUS]` diagnostics;
  the WNTR back-end returns an empty
  `EpanetImportDiagnostics` (documented limitation). This mirrors
  the Sprint 22 split where the fallback parser is authoritative
  for `[STATUS]` semantics.

## Known limitations

- Diagnostics surface **accepted `[STATUS] OPEN` rows only**.
  Rejected rows raise `ValueError` and do not appear in diagnostics
  (by design — they never produce a valid network either).
- The WNTR back-end does not emit diagnostics. Callers that need
  fallback-vs-WNTR diagnostic parity must use `parser="fallback"`.
- `[CONTROLS]` and `[RULES]` remain unimplemented and are **not**
  surfaced as diagnostics. The Sprint 21 documented limitation
  stands.
- The diagnostics container has a single field (`status_rows`)
  today. Future sprints may add more fields (e.g. surfacing
  ignored-section metadata or pump-translation diagnostics);
  adding optional fields is backwards-compatible because the
  current field has a default.

## Sprint 23 hard approval gates — checklist

- [x] targeted pytest exits 0 (`969 passed, 1 skipped`)
- [x] full pytest exits 0 (`977 passed, 1 skipped`)
- [x] compileall exits 0 (`rc=0`)
- [x] `SPRINT23_REPORT.md` exists (this file)
- [x] public diagnostics API exists and is tested
  (`load_inp_diagnostics`, `return_diagnostics=True`,
  `EpanetImportDiagnostics`, `EpanetStatusDiagnostic`)
- [x] accepted `[STATUS] OPEN` rows produce read-only diagnostics
- [x] diagnostics are proven hydraulically inert / no-op
  (byte-for-byte network equality vs. baseline)
- [x] `load_network_from_inp(path)` remains backward-compatible
  by default
- [x] Sprint 22 rejection behaviour remains intact for
  status-changing / invalid rows (8 parametrised cases re-tested
  through the diagnostics API; mixed OPEN+CLOSED block raises)
- [x] `STATUS` remains outside `IGNORED_SECTIONS`
  (`tests/dphm/test_inp_status.py::test_status_no_longer_in_ignored_sections`
  still passes)
- [x] `[CONTROLS]` / `[RULES]` remain ignored, not implemented
  (`test_controls_section_not_represented_in_diagnostics`,
  `test_rules_section_not_represented_in_diagnostics`)
- [x] existing SI / GPM / pressure / demand / SG / viscosity /
  ignored-section / STATUS fixture behaviour still passes
  (Sprint 11–22 suite green)
- [x] HEAD pump tests still pass
- [x] POWER pump tests still pass
- [x] PRV / TCV valve tests still pass
- [x] WNTR optional tests skip / pass cleanly
  (1 skip is the `wntr` ImportError-path that requires WNTR to be
  *absent*; the rest of the WNTR optional suite is green because
  `wntr==1.4.0` is installed)
- [x] no obvious secret files / strings introduced
- [x] git status contains only intended Sprint 23 changes

With `wntr==1.4.0` installed, the additional WNTR gates apply:

- [x] WNTR HEAD / POWER / PRV / TCV / demand-multiplier parity
  from Sprints 13–22 still pass
- [x] WNTR-side `[STATUS]` diagnostic asymmetry is documented
  (`docs/epanet-inp-import.md` — fallback authoritative; WNTR
  returns empty diagnostics)

## Verdict

`VERDICT: APPROVED`

## Sprint 24 recommendation

The diagnostics container shipped in Sprint 23 has room for one
specific, low-risk extension that would close a remaining
visibility gap *without* widening the safety boundary:

**Add ignored-section diagnostics (`ignored_sections: tuple[str, ...]`)
to `EpanetImportDiagnostics`** so analysts can see which
`IGNORED_SECTIONS` were actually *present* in the imported file
(e.g. flag that a file declared `[CONTROLS]` content that the
parser is silently dropping). This:

- stays inside the steady-state hydraulic boundary (no new
  physics);
- builds on the read-only / frozen-dataclass discipline established
  in Sprint 23;
- gives analysts concrete signal when a fixture declares
  `[CONTROLS]` / `[RULES]` they would otherwise have to grep the
  source file to discover;
- does not require any change to `Network` shape, the existing
  diagnostics records, or the fallback / WNTR parser invariants.

Strictly out of scope for Sprint 24 (deferred): closed-link
modelling, `[CONTROLS]` / `[RULES]` activation, Darcy-Weisbach,
`[PATTERNS]` time-varying demand, `[ENERGY]` parsing, real
PLC/PAC/SCADA, write/control path, dPL parameter learning, ONNX
deployment, real EPANET binary.
