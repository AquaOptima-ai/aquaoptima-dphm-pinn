"""Read-only ingestion adapters."""

from .base import IngestionAdapter, RawFrame
from .replay import JsonlReplayAdapter

__all__ = ["IngestionAdapter", "JsonlReplayAdapter", "RawFrame"]
