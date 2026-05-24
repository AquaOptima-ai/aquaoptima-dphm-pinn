"""TDD slice D — ``CapabilityDeclaration`` / ``CapabilityRequirement``.

Acceptance: capability tokens are deny-by-default; unknown and
forbidden tokens are rejected.
"""

from __future__ import annotations

import pytest

from aquaoptima_contracts import (
    ALLOWED_CAPABILITY_TOKENS,
    FORBIDDEN_CAPABILITY_TOKENS,
    FORBIDDEN_VOCABULARY,
    CapabilityDeclaration,
    CapabilityGateResult,
    CapabilityRequirement,
    CapabilityTokenError,
    SDK_VERSION,
    SchemaVersion,
    dump_canonical_json,
    evaluate_capability_gate,
    load_canonical_json,
)
from aquaoptima_contracts.testing.builders import (
    make_capability_declaration,
    make_capability_requirement,
)


def test_forbidden_capability_tokens_equal_forbidden_vocabulary() -> None:
    assert FORBIDDEN_CAPABILITY_TOKENS == FORBIDDEN_VOCABULARY


def test_declaration_with_full_default_set_round_trips() -> None:
    decl = make_capability_declaration()
    raw = dump_canonical_json(decl)
    decoded = load_canonical_json(raw)
    assert decoded["component"] == "edge_runtime"
    assert sorted(decoded["declared"]) == sorted(ALLOWED_CAPABILITY_TOKENS)
    assert decoded["sdk_version"] == SDK_VERSION.render()
    rebuilt = CapabilityDeclaration.from_dict(decoded)
    assert rebuilt == decl


def test_empty_requirement_is_accepted_for_validation_only_package() -> None:
    req = make_capability_requirement(
        package_id="validation-only", required=()
    )
    assert req.required == frozenset()


def test_evaluate_capability_gate_reports_no_missing_when_decl_covers_req() -> None:
    decl = make_capability_declaration()
    req = make_capability_requirement(
        required={"validate_manifest", "validate_safety_flags"}
    )
    result = evaluate_capability_gate(decl, req)
    assert isinstance(result, CapabilityGateResult)
    assert result.allowed is True
    assert result.missing == frozenset()


def test_evaluate_capability_gate_reports_missing_when_req_exceeds_decl() -> None:
    decl = make_capability_declaration(
        declared={"validate_manifest", "validate_safety_flags"}
    )
    req = make_capability_requirement(
        required={
            "validate_manifest",
            "validate_safety_flags",
            "run_shadow_replay",
        }
    )
    result = evaluate_capability_gate(decl, req)
    assert result.allowed is False
    assert result.missing == frozenset({"run_shadow_replay"})


def test_evaluate_capability_gate_is_deny_by_default_for_empty_declaration() -> None:
    decl = make_capability_declaration(declared=())
    req = make_capability_requirement(
        required={"validate_manifest"}
    )
    result = evaluate_capability_gate(decl, req)
    assert result.allowed is False
    assert result.missing == frozenset({"validate_manifest"})


def test_evaluate_capability_gate_rejects_wrong_types() -> None:
    with pytest.raises(TypeError):
        evaluate_capability_gate(None, make_capability_requirement())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        evaluate_capability_gate(make_capability_declaration(), None)  # type: ignore[arg-type]


@pytest.mark.parametrize("unknown", ["unrelated_capability", "do_a_thing"])
def test_unknown_token_rejected_on_declaration(unknown: str) -> None:
    with pytest.raises(CapabilityTokenError):
        make_capability_declaration(declared={unknown})


@pytest.mark.parametrize("unknown", ["unrelated_capability", "do_a_thing"])
def test_unknown_token_rejected_on_requirement(unknown: str) -> None:
    with pytest.raises(CapabilityTokenError):
        make_capability_requirement(required={unknown})


@pytest.mark.parametrize("forbidden", sorted(FORBIDDEN_VOCABULARY))
def test_forbidden_token_rejected_on_declaration(forbidden: str) -> None:
    with pytest.raises(CapabilityTokenError):
        make_capability_declaration(declared={forbidden})


@pytest.mark.parametrize("forbidden", sorted(FORBIDDEN_VOCABULARY))
def test_forbidden_token_rejected_on_requirement(forbidden: str) -> None:
    with pytest.raises(CapabilityTokenError):
        make_capability_requirement(required={forbidden})


def test_unknown_component_rejected() -> None:
    with pytest.raises(CapabilityTokenError):
        CapabilityDeclaration(
            component="rogue_component",
            declared=frozenset(),
            sdk_version=SDK_VERSION,
        )


def test_empty_package_id_rejected() -> None:
    with pytest.raises(CapabilityTokenError):
        CapabilityRequirement(
            package_id="",
            required=frozenset(),
            sdk_version=SDK_VERSION,
        )


def test_capability_declaration_frozen_and_hashable() -> None:
    decl = make_capability_declaration()
    assert hash(decl) == hash(make_capability_declaration())
    with pytest.raises(Exception):
        decl.component = "ai_server"  # type: ignore[misc]


def test_non_string_token_rejected() -> None:
    with pytest.raises(CapabilityTokenError):
        CapabilityDeclaration(
            component="edge_runtime",
            declared=frozenset({123}),  # type: ignore[arg-type]
            sdk_version=SDK_VERSION,
        )


def test_bare_string_declared_rejected() -> None:
    with pytest.raises(CapabilityTokenError):
        CapabilityDeclaration(
            component="edge_runtime",
            declared="validate_manifest",  # type: ignore[arg-type]
            sdk_version=SDK_VERSION,
        )


def test_sdk_version_must_be_schema_version() -> None:
    with pytest.raises(CapabilityTokenError):
        CapabilityDeclaration(
            component="edge_runtime",
            declared=frozenset(),
            sdk_version="0.1.0",  # type: ignore[arg-type]
        )


def test_declaration_to_dict_sorts_declared_capabilities() -> None:
    decl = make_capability_declaration(
        declared={
            "validate_safety_flags",
            "run_shadow_replay",
            "validate_manifest",
        }
    )
    payload = decl.to_dict()
    assert payload["declared"] == sorted(payload["declared"])


def test_schema_version_default_supports_capability_dataclasses() -> None:
    decl = CapabilityDeclaration(
        component="ai_server",
        declared=frozenset({"validate_manifest"}),
        sdk_version=SchemaVersion(0, 1, 0),
    )
    assert decl.sdk_version.render() == "0.1.0"
