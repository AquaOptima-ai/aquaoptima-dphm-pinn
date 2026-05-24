"""TDD — ``Provenance`` envelope identity contract (Sprint 42).

Acceptance: ``Provenance`` is a frozen, hashable record of the
producing component, version, build id, and optional signer identity.
The signer identity slot is deliberately string-only; signature
verification is out of scope for Sprint 42.
"""

from __future__ import annotations

import pytest

from aquaoptima_contracts import (
    ALLOWED_PROVENANCE_COMPONENTS,
    ContractError,
    Provenance,
    dump_canonical_json,
    load_canonical_json,
)


def test_minimal_provenance_round_trips() -> None:
    prov = Provenance(component="sdk", version="0.2.0")
    raw = dump_canonical_json(prov)
    decoded = load_canonical_json(raw)
    assert decoded == {"component": "sdk", "version": "0.2.0"}
    restored = Provenance.from_dict(decoded)
    assert restored == prov


def test_provenance_with_all_optional_fields() -> None:
    prov = Provenance(
        component="ai_server",
        version="1.2.3",
        build_id="ci-12345",
        signer_identity="signer-abc",
    )
    raw = dump_canonical_json(prov)
    decoded = load_canonical_json(raw)
    assert decoded == {
        "component": "ai_server",
        "version": "1.2.3",
        "build_id": "ci-12345",
        "signer_identity": "signer-abc",
    }
    assert Provenance.from_dict(decoded) == prov


def test_optional_fields_absent_when_unset() -> None:
    prov = Provenance(component="sdk", version="0.2.0")
    decoded = load_canonical_json(dump_canonical_json(prov))
    assert "build_id" not in decoded
    assert "signer_identity" not in decoded


def test_provenance_frozen() -> None:
    prov = Provenance(component="sdk", version="0.2.0")
    with pytest.raises(Exception):
        prov.component = "ai_server"  # type: ignore[misc]


def test_provenance_rejects_unknown_component() -> None:
    with pytest.raises(ContractError):
        Provenance(component="control_loop", version="0.0.0")


def test_provenance_rejects_empty_strings() -> None:
    with pytest.raises(ContractError):
        Provenance(component="", version="0.0.0")
    with pytest.raises(ContractError):
        Provenance(component="sdk", version="")
    with pytest.raises(ContractError):
        Provenance(component="sdk", version="0.0.0", build_id="")


def test_provenance_allowed_components_contains_canonical_set() -> None:
    for canon in ("sdk", "edge_runtime", "ai_server", "operations_console", "test"):
        assert canon in ALLOWED_PROVENANCE_COMPONENTS


def test_provenance_from_dict_rejects_unknown_field() -> None:
    with pytest.raises(ContractError):
        Provenance.from_dict(
            {
                "component": "sdk",
                "version": "0.1.0",
                "extra": "rogue",
            }
        )


def test_provenance_from_dict_rejects_non_mapping() -> None:
    with pytest.raises(ContractError):
        Provenance.from_dict(["sdk", "0.1.0"])  # type: ignore[arg-type]
