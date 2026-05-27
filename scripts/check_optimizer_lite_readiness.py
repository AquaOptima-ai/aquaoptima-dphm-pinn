#!/usr/bin/env python3
"""Run Optimizer Lite deployment readiness checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aquaoptima_lite.deployment import DeploymentReadinessChecker


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Optimizer Lite deployment readiness")
    parser.add_argument("--config", required=True)
    parser.add_argument("--replay", required=True)
    parser.add_argument("--cycles", type=int, default=4)
    args = parser.parse_args()

    report = DeploymentReadinessChecker().check(
        config_path=args.config,
        replay_path=args.replay,
        cycles=args.cycles,
    )
    print(json.dumps(report.to_dict(), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
