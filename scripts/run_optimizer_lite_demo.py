#!/usr/bin/env python3
"""Run the Optimizer Lite replay demo."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aquaoptima_lite.app.demo import run_demo


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Optimizer Lite replay demo")
    parser.add_argument("--config", required=True)
    parser.add_argument("--replay", required=True)
    parser.add_argument("--cycles", type=int, default=4)
    parser.add_argument("--audit-db", default=None)
    parser.add_argument("--learner-shadow", action="store_true")
    parser.add_argument("--learner-performance-shadow", action="store_true")
    args = parser.parse_args()

    summary = run_demo(
        config_path=Path(args.config),
        replay_path=Path(args.replay),
        cycles=args.cycles,
        audit_db=args.audit_db,
        enable_learner_shadow=args.learner_shadow,
        enable_performance_shadow=args.learner_performance_shadow,
    )
    lines = cast(list[str], summary["lines"])
    for line in lines:
        print(line)
    print(f"audit_count={summary['audit_count']}")
    if "learner_shadow" in summary:
        learner = cast(dict[str, Any], summary["learner_shadow"])
        learner_summary = cast(dict[str, Any], learner["summary"])
        print(
            "learner_shadow="
            f"{learner['status']} "
            f"confidence={learner['confidence']} "
            f"accepted={learner_summary['accepted_samples']} "
            f"rejected={learner_summary['rejected_samples']} "
            f"influences_control={learner['influences_control']}"
        )
    if "performance_model" in summary:
        perf = cast(dict[str, Any], summary["performance_model"])
        print(
            "performance_model "
            f"readiness={perf['readiness']} "
            f"confidence={perf['confidence']} "
            f"training_sample_count={perf['training_sample_count']} "
            f"influences_control={perf['influences_control']}"
        )
    print(f"audit_db={summary['audit_db']}")


if __name__ == "__main__":
    main()
