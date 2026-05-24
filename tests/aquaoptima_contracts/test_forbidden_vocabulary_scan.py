"""TDD slice G — forbidden-vocabulary scan.

Acceptance: no forbidden token appears anywhere in the new SDK code,
tests, or fixtures, **except** the canonical denylist constant in
``src/aquaoptima_contracts/safety/vocabulary.py``.

If this test fails, the build is blocked.
"""

from __future__ import annotations

import re
from pathlib import Path

from aquaoptima_contracts.safety.vocabulary import FORBIDDEN_VOCABULARY


REPO_ROOT = Path(__file__).resolve().parents[2]
SDK_SRC_DIR = REPO_ROOT / "src" / "aquaoptima_contracts"
SDK_TESTS_DIR = REPO_ROOT / "tests" / "aquaoptima_contracts"

# The single exempted file: the canonical denylist constant lives here
# and is allowed to enumerate every forbidden token literal exactly
# once. Every other file in the SDK source / tests / fixtures trees is
# scanned.
EXEMPT_FILE = SDK_SRC_DIR / "safety" / "vocabulary.py"

# Binary / generated files we never scan.
SKIP_SUFFIXES: frozenset[str] = frozenset({".pyc"})
SKIP_DIR_NAMES: frozenset[str] = frozenset({"__pycache__"})


def _files_to_scan() -> list[Path]:
    candidates: list[Path] = []
    for root in (SDK_SRC_DIR, SDK_TESTS_DIR):
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.suffix in SKIP_SUFFIXES:
                continue
            if path.resolve() == EXEMPT_FILE.resolve():
                continue
            candidates.append(path)
    return candidates


def test_no_forbidden_token_outside_canonical_denylist() -> None:
    # Word-boundary regex: ``\bsetpoint_output\b`` does NOT match the
    # canonical safety flag ``no_setpoint_output`` because the leading
    # ``_`` is a word character (no boundary), but DOES match the
    # standalone forbidden token. This is the contract the Sprint 41
    # plan describes ("exempt the canonical denylist constant in the
    # safety module itself") — the standalone token only ever appears
    # in ``safety/vocabulary.py``.
    hits: list[tuple[Path, str]] = []
    tokens = sorted(FORBIDDEN_VOCABULARY)
    patterns = {term: re.compile(rf"\b{re.escape(term)}\b") for term in tokens}
    # ``patterns`` is keyed by the forbidden term; the loop below
    # pulls per-term regexes by name to avoid scanning N*K times.
    for path in _files_to_scan():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for forbidden_term in tokens:
            if patterns[forbidden_term].search(text):
                hits.append((path, forbidden_term))
    if hits:
        formatted = "\n".join(
            f"{p.relative_to(REPO_ROOT)} -> {t}" for p, t in hits
        )
        raise AssertionError(
            "forbidden vocabulary token(s) leaked into SDK source / tests "
            f"/ fixtures:\n{formatted}"
        )


def test_vocabulary_module_actually_contains_every_token() -> None:
    # Defends against the denylist being silently emptied or moved.
    text = EXEMPT_FILE.read_text(encoding="utf-8")
    for term in FORBIDDEN_VOCABULARY:
        assert term in text, (
            f"forbidden vocabulary term {term!r} is no longer present "
            f"in the canonical denylist module at {EXEMPT_FILE!s}"
        )


def test_at_least_twelve_canonical_forbidden_tokens() -> None:
    # Sanity guard against a denylist regression.
    assert len(FORBIDDEN_VOCABULARY) >= 12
