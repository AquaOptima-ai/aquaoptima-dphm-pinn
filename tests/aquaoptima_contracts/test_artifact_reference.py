"""TDD — extended ``ArtifactReference`` (Sprint 42).

Sprint 41 shipped the minimal ``kind`` / ``id`` / ``version`` triple.
Sprint 42 adds the optional ``checksum`` and ``uri`` fields described
in ``docs/architecture/contracts-inventory.md``.
"""

from __future__ import annotations

import pytest

from aquaoptima_contracts import (
    ArtifactReference,
    Checksum,
    ContractError,
    dump_canonical_json,
    load_canonical_json,
)


VALID_SHA256 = "1" * 64


def test_minimal_artifact_reference_still_round_trips() -> None:
    ref = ArtifactReference(
        kind="shadow_replay_dataset",
        id="phase1-replay",
        version="1.0.0",
    )
    decoded = load_canonical_json(dump_canonical_json(ref))
    assert decoded == {
        "kind": "shadow_replay_dataset",
        "id": "phase1-replay",
        "version": "1.0.0",
    }
    assert ArtifactReference.from_dict(decoded) == ref


def test_artifact_reference_with_checksum_and_uri() -> None:
    checksum = Checksum(
        algorithm="sha256",
        hex_digest=VALID_SHA256,
        size_bytes=128,
    )
    ref = ArtifactReference(
        kind="shadow_replay_dataset",
        id="phase1-replay",
        version="1.0.0",
        checksum=checksum,
        uri="artifact://phase1-replay",
    )
    decoded = load_canonical_json(dump_canonical_json(ref))
    assert decoded == {
        "kind": "shadow_replay_dataset",
        "id": "phase1-replay",
        "version": "1.0.0",
        "checksum": {
            "algorithm": "sha256",
            "hex_digest": VALID_SHA256,
            "size_bytes": 128,
        },
        "uri": "artifact://phase1-replay",
    }
    restored = ArtifactReference.from_dict(decoded)
    assert restored == ref


def test_artifact_reference_empty_optional_fields_omitted() -> None:
    ref = ArtifactReference(kind="file", id="x", version="1.0.0")
    decoded = load_canonical_json(dump_canonical_json(ref))
    assert "checksum" not in decoded
    assert "uri" not in decoded


def test_artifact_reference_rejects_empty_required_fields() -> None:
    with pytest.raises(ValueError):
        ArtifactReference(kind="", id="x", version="1.0.0")
    with pytest.raises(ValueError):
        ArtifactReference(kind="file", id="", version="1.0.0")
    with pytest.raises(ValueError):
        ArtifactReference(kind="file", id="x", version="")


def test_artifact_reference_rejects_empty_uri_when_set() -> None:
    with pytest.raises(ValueError):
        ArtifactReference(kind="file", id="x", version="1.0.0", uri="")


def test_artifact_reference_rejects_bad_checksum_type() -> None:
    with pytest.raises(ValueError):
        ArtifactReference(
            kind="file",
            id="x",
            version="1.0.0",
            checksum={"algorithm": "sha256"},  # type: ignore[arg-type]
        )


def test_artifact_reference_from_dict_rejects_unknown_field() -> None:
    with pytest.raises(ValueError):
        ArtifactReference.from_dict(
            {
                "kind": "file",
                "id": "x",
                "version": "1.0.0",
                "rogue": "value",
            }
        )


def test_artifact_reference_frozen() -> None:
    ref = ArtifactReference(kind="file", id="x", version="1.0.0")
    with pytest.raises(Exception):
        ref.kind = "blob"  # type: ignore[misc]
