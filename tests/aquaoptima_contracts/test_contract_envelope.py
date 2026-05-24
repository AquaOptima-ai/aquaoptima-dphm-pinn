"""TDD slice B — ``ContractEnvelope``.

Acceptance: every envelope is frozen, deterministic, and rejects
unknown families.
"""

from __future__ import annotations

import pytest

from aquaoptima_contracts import (
    ALLOWED_SCHEMA_FAMILIES,
    ContractEnvelope,
    ContractError,
    SchemaVersion,
    dump_canonical_json,
    load_canonical_json,
)
from aquaoptima_contracts.testing.builders import make_envelope


def test_minimal_envelope_renders_to_byte_stable_json() -> None:
    envelope = make_envelope()
    rendered_a = dump_canonical_json(envelope)
    rendered_b = dump_canonical_json(envelope)
    assert rendered_a == rendered_b
    decoded = load_canonical_json(rendered_a)
    assert decoded == {
        "schema_family": "safety",
        "schema_name": "SafetyFlagSet",
        "schema_version": "1.0.0",
        "sdk_version": "0.1.0",
    }


def test_envelope_with_all_optional_fields_round_trips() -> None:
    envelope = make_envelope(
        created_at="1970-01-01T00:00:00Z",
        created_by_component="sdk",
        artifact_id="artifact-abc",
        correlation_id="corr-xyz",
    )
    raw = dump_canonical_json(envelope)
    decoded = load_canonical_json(raw)
    assert decoded["created_at"] == "1970-01-01T00:00:00Z"
    assert decoded["created_by_component"] == "sdk"
    assert decoded["artifact_id"] == "artifact-abc"
    assert decoded["correlation_id"] == "corr-xyz"

    via_from_dict = ContractEnvelope.from_dict(decoded)
    assert via_from_dict == envelope


def test_two_identical_envelopes_hash_identically() -> None:
    one = make_envelope()
    two = make_envelope()
    assert one == two
    assert hash(one) == hash(two)


def test_envelope_is_frozen() -> None:
    envelope = make_envelope()
    with pytest.raises(Exception):
        envelope.schema_family = "telemetry"  # type: ignore[misc]


def test_unknown_schema_family_rejected() -> None:
    with pytest.raises(ContractError):
        make_envelope(schema_family="control")


@pytest.mark.parametrize("family", sorted(ALLOWED_SCHEMA_FAMILIES))
def test_every_allowed_family_constructs(family: str) -> None:
    envelope = make_envelope(schema_family=family, schema_name="Stub")
    assert envelope.schema_family == family


def test_absent_optional_fields_do_not_appear_in_json() -> None:
    envelope = make_envelope()
    raw = dump_canonical_json(envelope)
    decoded = load_canonical_json(raw)
    for field in (
        "created_at",
        "created_by_component",
        "artifact_id",
        "correlation_id",
    ):
        assert field not in decoded


def test_unknown_created_by_component_rejected() -> None:
    with pytest.raises(ContractError):
        make_envelope(created_by_component="not_a_component")


def test_empty_string_fields_rejected() -> None:
    with pytest.raises(ContractError):
        ContractEnvelope(
            schema_family="",
            schema_name="X",
            schema_version=SchemaVersion(1, 0, 0),
            sdk_version=SchemaVersion(0, 1, 0),
        )
    with pytest.raises(ContractError):
        ContractEnvelope(
            schema_family="safety",
            schema_name="",
            schema_version=SchemaVersion(1, 0, 0),
            sdk_version=SchemaVersion(0, 1, 0),
        )


def test_from_dict_rejects_missing_required_fields() -> None:
    with pytest.raises(ContractError):
        ContractEnvelope.from_dict({"schema_family": "safety"})


def test_from_dict_rejects_unknown_fields() -> None:
    with pytest.raises(ContractError):
        ContractEnvelope.from_dict(
            {
                "schema_family": "safety",
                "schema_name": "SafetyFlagSet",
                "schema_version": "1.0.0",
                "sdk_version": "0.1.0",
                "rogue_field": "x",
            }
        )


def test_from_dict_requires_mapping() -> None:
    with pytest.raises(ContractError):
        ContractEnvelope.from_dict(None)  # type: ignore[arg-type]
