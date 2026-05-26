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
    args = parser.parse_args()

    summary = run_demo(
        config_path=Path(args.config),
        replay_path=Path(args.replay),
        cycles=args.cycles,
        audit_db=args.audit_db,
    )
    lines = cast(list[str], summary["lines"])
    for line in lines:
        print(line)
    print(f"audit_count={summary['audit_count']}")
    print(f"audit_db={summary['audit_db']}")


if __name__ == "__main__":
    main()
