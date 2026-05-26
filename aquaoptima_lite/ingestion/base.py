"""Base contracts for ingestion adapters.

A :class:`RawFrame` is the lowest-common-denominator unit of input: an
ordered mapping of tag names to values, plus a timestamp string and the
source label that produced the frame.  Adapters yield :class:`RawFrame`
instances; the normalization layer turns those frames into canonical
:class:`StationSnapshot` records via the tag mapper, unit normalizer, and
snapshot builder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class RawFrame:
    """A single raw observation from an ingestion source.

    The ``tags`` mapping is intentionally permissive: legacy tag names,
    MVP-style suffixed names, and canonical names may all appear.  The
    normalization layer is responsible for resolving the actual names
    into canonical fields.
    """

    timestamp: str
    source: str
    tags: Mapping[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.tags.get(key, default)


@runtime_checkable
class IngestionAdapter(Protocol):
    """Read-only producer of :class:`RawFrame` instances.

    An adapter is iterable and may be re-entered (``__iter__`` should
    return a fresh iterator over the underlying source).  Adapters do
    not perform any PLC/PAC writes.
    """

    source: str

    def __iter__(self) -> Iterator[RawFrame]: ...

    def frames(self) -> Iterable[RawFrame]: ...
