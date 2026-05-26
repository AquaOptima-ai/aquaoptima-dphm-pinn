"""Replay-demo runner for Optimizer Lite."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..config import load_site_config
from ..ingestion import JsonlReplayAdapter
from ..normalization import SnapshotBuilder
from ..app import RuntimeCycle
from ..learner import LearnerSampleCollector, LearnerShadowService
from ..storage import SQLiteAuditStore


def run_demo(
    *,
    config_path: str | Path,
    replay_path: str | Path,
    cycles: int = 4,
    audit_db: str | Path | None = None,
    enable_learner_shadow: bool = False,
) -> dict[str, object]:
    config = load_site_config(config_path)
    builder = SnapshotBuilder(config)
    store = SQLiteAuditStore(audit_db or ":memory:")
    runtime = RuntimeCycle(config=config, audit_store=store)
    learner = LearnerSampleCollector(min_samples_for_shadow=2) if enable_learner_shadow else None
    adapter = JsonlReplayAdapter(replay_path)
    outputs: list[str] = []
    count = 0
    for frame in adapter:
        if count >= cycles:
            break
        snapshot = builder.build(frame)
        result = runtime.run(snapshot)
        if learner is not None:
            learner.collect(result.snapshot, result.quality, runtime.demand)
            evidence = LearnerShadowService(learner).build_evidence()
            store.attach_learner_shadow(result.audit_id, evidence)
        outputs.append(
            f"cycle={count+1} quality={result.quality.status} "
            f"source={result.recommendation.source} "
            f"authority={result.authority.decision} audit_id={result.audit_id}"
        )
        count += 1
    summary = {
        "cycles": count,
        "audit_count": store.count(),
        "audit_db": str(audit_db or ":memory:"),
        "lines": outputs,
    }
    if learner is not None:
        summary["learner_shadow"] = LearnerShadowService(learner).build_evidence().to_dict()
    if audit_db is None:
        store.close()
    return summary
