"""Repo-root conftest: ensure THIS worktree's ``src/`` shadows any globally
installed editable copy of aquaoptima, so Sprint 23 tests resolve the local
modules under development.
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(__file__), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# Drop any pre-imported aquaoptima coming from a different editable install.
for _mod in [m for m in list(sys.modules) if m.split(".")[0] in {"aquaoptima"}]:
    _loaded = getattr(sys.modules[_mod], "__file__", "") or ""
    if _SRC not in _loaded:
        del sys.modules[_mod]
