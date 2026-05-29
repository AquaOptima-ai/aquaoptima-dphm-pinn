"""Architecture guard (AOPSO Sprint 24): no edge imports in core.

Static scan: no file under ``src/aquaoptima/models`` or
``src/aquaoptima/training`` may import ``aquaoptima.edge`` or
``aquaoptima_contracts.edge`` (offline-training safety boundary). Also asserts
the Sprint 24 new files contain no ONNX export code (deferred to Sprint 26).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
CORE_DIRS = [SRC / "aquaoptima" / "models", SRC / "aquaoptima" / "training"]

FORBIDDEN_PREFIXES = ("aquaoptima.edge", "aquaoptima_contracts.edge")


def _iter_core_py_files():
    for d in CORE_DIRS:
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            yield p


def _imported_modules(path: Path):
    tree = ast.parse(path.read_text(), filename=str(path))
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                mods.append(node.module)
    return mods


@pytest.mark.parametrize("py_file", list(_iter_core_py_files()), ids=lambda p: p.name)
def test_no_edge_imports_in_core(py_file):
    for mod in _imported_modules(py_file):
        for bad in FORBIDDEN_PREFIXES:
            assert not (mod == bad or mod.startswith(bad + ".")), (
                f"{py_file} imports forbidden edge module '{mod}'"
            )


def test_scan_covered_some_files():
    files = list(_iter_core_py_files())
    assert len(files) > 0, "expected to scan core model/training files"


SPRINT24_NEW_FILES = [
    SRC / "aquaoptima" / "models" / "tcn_dphm.py",
    SRC / "aquaoptima" / "training" / "dphm_loss.py",
    SRC / "aquaoptima" / "training" / "dphm_trainer.py",
    SRC / "aquaoptima" / "training" / "seed.py",
]


@pytest.mark.parametrize("py_file", SPRINT24_NEW_FILES, ids=lambda p: p.name)
def test_no_onnx_export_in_new_files(py_file):
    text = py_file.read_text().lower()
    # No ONNX export this sprint (deferred to Sprint 26).
    assert "torch.onnx" not in text
    assert "export(" not in text or "onnx" not in text
    assert "import onnx" not in text
