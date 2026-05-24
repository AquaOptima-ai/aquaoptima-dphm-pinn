"""Deterministic JSON helpers (stdlib only).

The Phase 1 ``write_shadow_deployment_manifest_json`` writer uses
``sort_keys=True``, ``indent=2``, ``separators=(",", ": ")``,
``ensure_ascii=False``, and a trailing newline. The Sprint 41 SDK
helpers reuse the same format so that any future SDK projection of a
Phase 1 manifest round-trips byte-for-byte through both writers.
"""

from __future__ import annotations

import json
import os
from dataclasses import is_dataclass
from pathlib import Path
from typing import Any


_CANONICAL_INDENT: int = 2
_CANONICAL_SEPARATORS: tuple[str, str] = (",", ": ")
_CANONICAL_ENCODING: str = "utf-8"


def _coerce(value: Any) -> Any:
    """Project SDK / Python objects into JSON-native primitives.

    Supported inputs:
      * primitives accepted by ``json.dumps`` (str, int, float, bool,
        None);
      * mappings (recursively coerced);
      * lists, tuples (preserving caller order);
      * frozenset / set (sorted alphabetically for determinism);
      * objects exposing a ``to_dict()`` method;
      * dataclass instances (via ``dataclasses.asdict``-style projection
        when no ``to_dict`` is available).
    """

    if isinstance(value, bool) or isinstance(value, (int, float, str)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_coerce(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_coerce(item) for item in value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _coerce(to_dict())
    if is_dataclass(value):
        from dataclasses import fields

        return {f.name: _coerce(getattr(value, f.name)) for f in fields(value)}
    raise TypeError(
        f"dump_canonical_json: object of type {type(value).__name__} "
        "is not JSON-serializable through the SDK canonical writer"
    )


def dump_canonical_json(obj: Any) -> str:
    """Render ``obj`` to a deterministic UTF-8 JSON string.

    Sorted keys at every level, ``indent=2``, no trailing newline. Use
    :func:`write_canonical_json` for the file writer (which appends
    the trailing newline).
    """

    return json.dumps(
        _coerce(obj),
        sort_keys=True,
        indent=_CANONICAL_INDENT,
        ensure_ascii=False,
        separators=_CANONICAL_SEPARATORS,
    )


def load_canonical_json(raw: str | bytes) -> Any:
    """Decode a canonical JSON document.

    Accepts ``str`` or UTF-8 ``bytes`` for caller convenience.
    """

    if isinstance(raw, bytes):
        raw = raw.decode(_CANONICAL_ENCODING)
    if not isinstance(raw, str):
        raise TypeError(
            f"load_canonical_json requires str or bytes, got "
            f"{type(raw).__name__}"
        )
    return json.loads(raw)


def write_canonical_json(obj: Any, path: os.PathLike[str] | str) -> Path:
    """Write ``obj`` deterministically to ``path`` and return the path.

    Parent directories are created if missing. The file is overwritten
    if present. The writer always appends a trailing newline and uses
    UTF-8 encoding.
    """

    if not isinstance(path, (str, os.PathLike)):
        raise TypeError(
            f"write_canonical_json path must be str or PathLike, got "
            f"{type(path).__name__}"
        )
    out_path = Path(os.fspath(path))
    if out_path.parent and not out_path.parent.exists():
        out_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = dump_canonical_json(obj) + "\n"
    out_path.write_text(rendered, encoding=_CANONICAL_ENCODING)
    return out_path
