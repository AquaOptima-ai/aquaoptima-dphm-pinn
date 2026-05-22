"""Tests for ``SolveResult`` and failure-classification helpers."""

import math

import pytest
import torch

from aquaoptima.dphm.diagnostics import (
    SolveResult,
    classify_failure,
    SolveFailureReason,
)


def test_solve_result_defaults_reason_to_none_when_converged():
    res = SolveResult(
        converged=True,
        heads=torch.zeros(3),
        flows=torch.zeros(2),
        residual_norm=1e-9,
        iterations=4,
    )
    assert res.converged
    assert res.reason is None


def test_solve_result_accepts_reason_string_on_failure():
    res = SolveResult(
        converged=False,
        heads=torch.zeros(3),
        flows=torch.zeros(2),
        residual_norm=12.5,
        iterations=50,
        reason="max_iterations",
    )
    assert not res.converged
    assert res.reason == "max_iterations"


def test_classify_failure_returns_max_iterations_when_iter_budget_hit():
    reason = classify_failure(
        residual_norm=10.0,
        iterations=50,
        max_iterations=50,
        tol=1e-6,
        diverged=False,
    )
    assert reason == SolveFailureReason.MAX_ITERATIONS


def test_classify_failure_returns_diverged_when_residual_explodes():
    reason = classify_failure(
        residual_norm=float("inf"),
        iterations=5,
        max_iterations=50,
        tol=1e-6,
        diverged=True,
    )
    assert reason == SolveFailureReason.DIVERGED


def test_classify_failure_returns_nan_when_residual_is_nan():
    reason = classify_failure(
        residual_norm=math.nan,
        iterations=3,
        max_iterations=50,
        tol=1e-6,
        diverged=False,
    )
    assert reason == SolveFailureReason.NAN_RESIDUAL


def test_classify_failure_returns_none_when_converged():
    reason = classify_failure(
        residual_norm=1e-8,
        iterations=6,
        max_iterations=50,
        tol=1e-6,
        diverged=False,
    )
    assert reason is None


def test_failure_reason_enum_values_are_strings():
    # Reason strings are part of the public API surface — they get logged.
    assert SolveFailureReason.MAX_ITERATIONS.value == "max_iterations"
    assert SolveFailureReason.DIVERGED.value == "diverged"
    assert SolveFailureReason.NAN_RESIDUAL.value == "nan_residual"


def test_solve_result_rejects_inconsistent_converged_flag():
    # A converged=True solve must not carry a non-finite residual norm.
    with pytest.raises(ValueError, match="converged"):
        SolveResult(
            converged=True,
            heads=torch.zeros(3),
            flows=torch.zeros(2),
            residual_norm=float("nan"),
            iterations=4,
        )
