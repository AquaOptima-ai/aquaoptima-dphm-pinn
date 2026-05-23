"""Sprint 11 — optional WNTR-backed INP loader.

WNTR (`Water Network Tool for Resilience`) is an **optional**
dependency. The dPHM-PINN test suite must run cleanly without it, so
every test in this module is guarded by :func:`pytest.importorskip`.
If WNTR is installed in the active environment, the same shipped
fixture used by ``tests/dphm/test_inp_network_io.py`` is parsed
through both back-ends and the two networks are checked for
structural agreement.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import torch

from aquaoptima.dphm import Network, load_network_from_inp, newton_solve


_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "epanet_reference_loop.inp"
)


def test_wntr_loader_matches_fallback_on_shipped_fixture() -> None:
    pytest.importorskip("wntr")

    net_fb = load_network_from_inp(_FIXTURE_PATH, parser="fallback")
    net_wn = load_network_from_inp(_FIXTURE_PATH, parser="wntr")

    assert isinstance(net_wn, Network)
    assert net_wn.num_nodes == net_fb.num_nodes
    assert net_wn.num_edges == net_fb.num_edges
    assert net_wn.num_fixed_heads == net_fb.num_fixed_heads
    # Fixed-head boundary values match (reservoir head).
    fb_fixed = sorted(
        float(v) for v, m in zip(
            net_fb.fixed_head_values.tolist(), net_fb.fixed_head_mask.tolist()
        ) if m
    )
    wn_fixed = sorted(
        float(v) for v, m in zip(
            net_wn.fixed_head_values.tolist(), net_wn.fixed_head_mask.tolist()
        ) if m
    )
    assert fb_fixed == pytest.approx(wn_fixed, abs=1e-6)


def test_wntr_loaded_network_solves() -> None:
    pytest.importorskip("wntr")

    net = load_network_from_inp(_FIXTURE_PATH, parser="wntr")
    result = newton_solve(
        net, max_iterations=200, tol=1e-9, jacobian_mode="analytic"
    )
    assert result.converged, f"WNTR-loaded network did not solve: {result.reason}"
    assert result.residual_norm < 1e-8


def test_wntr_parser_explicit_raises_importerror_when_missing() -> None:
    """If WNTR is *not* installed and parser='wntr' is forced, raise ImportError.

    The opposite case (WNTR present) is covered above; here we only
    assert the error path when WNTR is absent. We detect the absence
    by trying to import wntr ourselves; if it imports, the test is
    skipped because there is no negative path to exercise.
    """
    try:
        import wntr  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError, match="wntr"):
            load_network_from_inp(_FIXTURE_PATH, parser="wntr")
    else:
        pytest.skip("WNTR is installed; ImportError path not exercised here")
