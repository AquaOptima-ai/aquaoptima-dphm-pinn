"""JSONL replay adapter.

Each line of the replay file is a JSON object that is either:

- a raw tag dict (legacy or MVP-style names plus a ``timestamp`` key), or
- a canonical-ish snapshot dict that already groups tags under
  ``"tags"`` / ``"sensor_data"`` plus top-level metadata.

The adapter does not attempt canonicalization -- it only resolves the
frame's timestamp and flattens whichever shape was provided into a
single ``tags`` mapping for the normalization layer to consume.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Mapping

from .base import IngestionAdapter, RawFrame


_TAG_CONTAINER_KEYS = ("tags", "sensor_data", "raw_tags")


def _extract_tags(record: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten container keys into a single tag mapping."""

    out: dict[str, Any] = {}
    # Pick up nested containers first, then let top-level scalars
    # override them so an explicit top-level key wins.
    for container_key in _TAG_CONTAINER_KEYS:
        container = record.get(container_key)
        if isinstance(container, Mapping):
            for k, v in container.items():
                out[str(k)] = v
    for k, v in record.items():
        if k in _TAG_CONTAINER_KEYS:
            continue
        # Skip metadata keys we already promoted out.
        if k in ("timestamp", "source", "site_id"):
            continue
        out[str(k)] = v
    return out


def _coerce_timestamp(record: Mapping[str, Any]) -> str:
    ts = record.get("timestamp")
    if ts is None:
        # MVP-style records sometimes nest the timestamp inside the tags.
        nested = record.get("sensor_data") or record.get("tags")
        if isinstance(nested, Mapping):
            ts = nested.get("timestamp")
    if ts is None:
        raise ValueError("replay record missing 'timestamp'")
    return str(ts)


class JsonlReplayAdapter:
    """Iterates a JSONL file as :class:`RawFrame` instances.

    The adapter is read-only and does not mutate the underlying file.
    Empty lines and lines whose content is just whitespace are skipped
    so files can be hand-edited without breaking the parser.
    """

    source = "replay_jsonl"

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        if not self._path.exists():
            raise FileNotFoundError(f"replay file not found: {self._path}")

    @property
    def path(self) -> Path:
        return self._path

    def __iter__(self) -> Iterator[RawFrame]:
        return self.frames()

    def frames(self) -> Iterator[RawFrame]:
        with self._path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"replay file {self._path}:{lineno} is not valid JSON: {exc}"
                    ) from exc
                if not isinstance(record, Mapping):
                    raise ValueError(
                        f"replay file {self._path}:{lineno} must be a JSON object"
                    )
                yield RawFrame(
                    timestamp=_coerce_timestamp(record),
                    source=str(record.get("source", self.source)),
                    tags=_extract_tags(record),
                )
