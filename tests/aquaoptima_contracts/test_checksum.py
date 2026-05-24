"""TDD — ``Checksum`` envelope identity contract (Sprint 42).

Acceptance: ``Checksum`` is a frozen, hashable, deterministic record
of ``algorithm``, ``hex_digest``, ``size_bytes``. Validation rejects
unknown algorithms, malformed hex, and negative sizes. No filesystem
or network IO.
"""

from __future__ import annotations

import pytest

from aquaoptima_contracts import (
    ALLOWED_CHECKSUM_ALGORITHMS,
    Checksum,
    ContractError,
    dump_canonical_json,
    load_canonical_json,
)


VALID_SHA256 = "a" * 64


def test_checksum_frozen_and_hashable() -> None:
    one = Checksum(algorithm="sha256", hex_digest=VALID_SHA256, size_bytes=42)
    two = Checksum(algorithm="sha256", hex_digest=VALID_SHA256, size_bytes=42)
    assert one == two
    assert hash(one) == hash(two)
    with pytest.raises(Exception):
        one.algorithm = "sha512"  # type: ignore[misc]


def test_checksum_to_dict_round_trip() -> None:
    payload = Checksum(
        algorithm="sha256",
        hex_digest=VALID_SHA256,
        size_bytes=12,
    )
    raw = dump_canonical_json(payload)
    decoded = load_canonical_json(raw)
    assert decoded == {
        "algorithm": "sha256",
        "hex_digest": VALID_SHA256,
        "size_bytes": 12,
    }
    restored = Checksum.from_dict(decoded)
    assert restored == payload


def test_checksum_rejects_unknown_algorithm() -> None:
    with pytest.raises(ContractError):
        Checksum(algorithm="md5", hex_digest=VALID_SHA256, size_bytes=1)


def test_checksum_rejects_uppercase_hex() -> None:
    with pytest.raises(ContractError):
        Checksum(algorithm="sha256", hex_digest="A" * 64, size_bytes=1)


def test_checksum_rejects_non_hex_digest() -> None:
    with pytest.raises(ContractError):
        Checksum(
            algorithm="sha256",
            hex_digest=("z" * 64),
            size_bytes=1,
        )


def test_checksum_rejects_wrong_length_digest() -> None:
    with pytest.raises(ContractError):
        Checksum(
            algorithm="sha256",
            hex_digest="a" * 63,
            size_bytes=1,
        )


def test_checksum_rejects_negative_size() -> None:
    with pytest.raises(ContractError):
        Checksum(algorithm="sha256", hex_digest=VALID_SHA256, size_bytes=-1)


def test_checksum_rejects_bool_size() -> None:
    with pytest.raises(ContractError):
        Checksum(
            algorithm="sha256",
            hex_digest=VALID_SHA256,
            size_bytes=True,  # type: ignore[arg-type]
        )


def test_allowed_algorithms_includes_sha256() -> None:
    assert "sha256" in ALLOWED_CHECKSUM_ALGORITHMS


def test_from_dict_rejects_unknown_fields() -> None:
    with pytest.raises(ContractError):
        Checksum.from_dict(
            {
                "algorithm": "sha256",
                "hex_digest": VALID_SHA256,
                "size_bytes": 1,
                "extra": "rogue",
            }
        )


def test_from_dict_rejects_non_mapping() -> None:
    with pytest.raises(ContractError):
        Checksum.from_dict(None)  # type: ignore[arg-type]
