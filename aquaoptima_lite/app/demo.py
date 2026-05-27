"""Replay-demo runner for Optimizer Lite."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..config import load_site_config
from ..ingestion import JsonlReplayAdapter
from ..normalization import SnapshotBuilder
from ..app import RuntimeCycle
from ..learner import (
    AdvisoryRankingService,
    LearnerSampleCollector,
    LearnerShadowService,
    StatisticalPerformanceModel,
)
from ..storage import SQLiteAuditStore


def run_demo(
    *,
    config_path: str | Path,
    replay_path: str | Path,
    cycles: int = 4,
    audit_db: str | Path | None = None,
    enable_learner_shadow: bool = False,
    enable_performance_shadow: bool = False,
    enable_advisory_ranking: bool = False,
) -> dict[str, object]:
    config = load_site_config(config_path)
    builder = SnapshotBuilder(config)
    store = SQLiteAuditStore(audit_db or ":memory:")
    runtime = RuntimeCycle(config=config, audit_store=store)
    learner = (
        LearnerSampleCollector(min_samples_for_shadow=2)
        if enable_learner_shadow or enable_performance_shadow or enable_advisory_ranking
        else None
    )
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
            evidence_dict = LearnerShadowService(learner).build_evidence().to_dict()
            if enable_performance_shadow:
                performance = StatisticalPerformanceModel(min_samples_per_combo=2).evaluate(learner.samples)
                evidence_dict["performance_model"] = performance.to_dict()
            if enable_advisory_ranking:
                ranking = AdvisoryRankingService(min_samples_per_combo=2).rank(
                    learner.samples,
                    baseline=result.recommendation,
                )
                evidence_dict["advisory_ranking"] = ranking.to_dict()
            store.attach_learner_shadow(result.audit_id, evidence_dict)
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
    latest_baseline = runtime._latest.recommendation if runtime._latest is not None else None
    if learner is not None:
        learner_shadow = LearnerShadowService(learner).build_evidence().to_dict()
        summary["learner_shadow"] = learner_shadow
        if enable_performance_shadow:
            performance = StatisticalPerformanceModel(min_samples_per_combo=2).evaluate(learner.samples)
            summary["performance_model"] = performance.to_dict()
        if enable_advisory_ranking:
            if latest_baseline is not None:
                ranking = AdvisoryRankingService(min_samples_per_combo=2).rank(
                    learner.samples,
                    baseline=latest_baseline,
                )
                summary["advisory_ranking"] = ranking.to_dict()
    if audit_db is None:
        store.close()
    return summary
