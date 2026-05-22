"""Tests for Sprint 4 lambda schedulers.

A lambda scheduler maps training step ``k`` to a non-negative scalar
weight used by :func:`aquaoptima.models.losses.composite_loss`. Two
shapes are required:

* ``FixedLambda`` — returns a constant value at every step. Allows
  zero (used by the sensor-only ablation).
* ``LinearRampLambda`` — linearly ramps from ``start`` to ``end`` over
  the first ``ramp_steps`` steps, then clamps at ``end`` forever after.
"""

from __future__ import annotations

import pytest

from aquaoptima.models.lambda_scheduler import (
    FixedLambda,
    LinearRampLambda,
    make_scheduler,
)


def test_fixed_lambda_returns_constant() -> None:
    sched = FixedLambda(0.7)
    assert sched.value(0) == pytest.approx(0.7)
    assert sched.value(10) == pytest.approx(0.7)
    assert sched.value(10_000) == pytest.approx(0.7)


def test_fixed_lambda_accepts_zero() -> None:
    sched = FixedLambda(0.0)
    assert sched.value(0) == 0.0
    assert sched.value(123) == 0.0


def test_fixed_lambda_rejects_negative() -> None:
    with pytest.raises(ValueError):
        FixedLambda(-0.1)


def test_linear_ramp_starts_at_start_value() -> None:
    sched = LinearRampLambda(start=0.0, end=1.0, ramp_steps=10)
    assert sched.value(0) == pytest.approx(0.0)


def test_linear_ramp_reaches_end_value_at_ramp_steps() -> None:
    sched = LinearRampLambda(start=0.0, end=1.0, ramp_steps=10)
    assert sched.value(10) == pytest.approx(1.0)


def test_linear_ramp_midpoint_is_halfway() -> None:
    sched = LinearRampLambda(start=0.0, end=1.0, ramp_steps=10)
    assert sched.value(5) == pytest.approx(0.5)


def test_linear_ramp_clamps_after_end() -> None:
    sched = LinearRampLambda(start=0.0, end=2.0, ramp_steps=4)
    assert sched.value(100) == pytest.approx(2.0)
    assert sched.value(1000) == pytest.approx(2.0)


def test_linear_ramp_supports_descending() -> None:
    sched = LinearRampLambda(start=2.0, end=0.5, ramp_steps=3)
    assert sched.value(0) == pytest.approx(2.0)
    assert sched.value(3) == pytest.approx(0.5)
    assert sched.value(99) == pytest.approx(0.5)


def test_linear_ramp_rejects_zero_ramp_steps() -> None:
    with pytest.raises(ValueError):
        LinearRampLambda(start=0.0, end=1.0, ramp_steps=0)


def test_linear_ramp_rejects_negative_start_or_end() -> None:
    with pytest.raises(ValueError):
        LinearRampLambda(start=-0.1, end=1.0, ramp_steps=5)
    with pytest.raises(ValueError):
        LinearRampLambda(start=0.0, end=-0.5, ramp_steps=5)


def test_make_scheduler_fixed() -> None:
    sched = make_scheduler({"kind": "fixed", "value": 0.3})
    assert isinstance(sched, FixedLambda)
    assert sched.value(0) == pytest.approx(0.3)


def test_make_scheduler_linear() -> None:
    sched = make_scheduler(
        {"kind": "linear", "start": 0.0, "end": 1.0, "ramp_steps": 4}
    )
    assert isinstance(sched, LinearRampLambda)
    assert sched.value(2) == pytest.approx(0.5)


def test_make_scheduler_unknown_kind_raises() -> None:
    with pytest.raises(ValueError):
        make_scheduler({"kind": "no_such_scheduler"})
