# Import-quality Report Validation

## Purpose

Validate that imported EPANET/WNTR topology diagnostics clearly expose unsupported sections, row-level diagnostics, and surrogate approximations.

## Current sources

- `EpanetImportDiagnostics.summary()`.
- `rows_for_section(name)`.
- `edge_surrogates`.
- `build_import_quality_report(...)`.

## Validation goals

- No double counting.
- Deterministic ordering.
- WNTR asymmetry explicitly reported.
- No parser/network mutation.
