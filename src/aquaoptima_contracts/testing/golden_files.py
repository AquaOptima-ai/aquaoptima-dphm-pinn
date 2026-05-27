"""Golden-fixture round-trip harness.

The harness reads a JSON fixture, decodes through the supplied SDK
contract type, re-encodes via :func:`dump_canonical_json` (or its
file-writer twin), and asserts byte equality against the on-disk
fixture. Sprint 41 ships positive coverage; Sprint 42+ contract types
plug into the same harness without modification.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol

from ..base.serialization import dump_canonical_json, load_canonical_json


class _ContractLike(Protocol):
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "_ContractLike":  # pragma: no cover
        ...

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover
        ...


def assert_golden_roundtrip(
    fixture_path: Path | str,
    *,
    schema: type[_ContractLike] | None = None,
    decoder: Callable[[dict[str, Any]], Any] | None = None,
    encoder: Callable[[Any], dict[str, Any]] | None = None,
) -> None:
    """Round-trip ``fixture_path`` through the SDK and assert byte equality.

    Either pass ``schema=...`` (which must expose ``from_dict`` and
    ``to_dict``) or pass an explicit ``decoder``/``encoder`` pair.

    The trailing newline written by :func:`write_canonical_json` is
    accepted at the end of the fixture; the comparison treats a
    fixture with or without a trailing newline as canonical-equivalent.
    """

    path = Path(fixture_path)
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    document = load_canonical_json(text)

    if decoder is not None and encoder is not None:
        decoded = decoder(document)
        re_encoded = encoder(decoded)
    elif schema is not None:
        decoded = schema.from_dict(document)
        re_encoded = decoded.to_dict()
    else:
        raise TypeError(
            "assert_golden_roundtrip: provide either schema= or both "
            "decoder= and encoder="
        )

    canonical = dump_canonical_json(re_encoded)
    expected_with_nl = canonical + "\n"
    if text != canonical and text != expected_with_nl:
        raise AssertionError(
            f"golden fixture {path!s} is not byte-equal to the SDK "
            "canonical re-encoding"
        )


def assert_byte_equal(path_a: Path | str, path_b: Path | str) -> None:
    """Assert two files are byte-identical (used by fixture-pair tests)."""

    raw_a = Path(path_a).read_bytes()
    raw_b = Path(path_b).read_bytes()
    if raw_a != raw_b:
        raise AssertionError(
            f"files differ: {path_a!s} vs {path_b!s} "
            f"(sizes {len(raw_a)} vs {len(raw_b)})"
        )
