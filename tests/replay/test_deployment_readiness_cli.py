import json
import subprocess
import sys
from pathlib import Path

CONFIG_PATH = "config/examples/legacy_station_001.yaml"
REPLAY_PATH = "tests/fixtures/replay/legacy_station_replay.jsonl"


def test_deployment_readiness_cli_outputs_json_report():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_optimizer_lite_readiness.py",
            "--config",
            CONFIG_PATH,
            "--replay",
            REPLAY_PATH,
            "--cycles",
            "4",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["status"] == "ready_for_pilot_review"
    assert payload["read_only"] is True
    assert payload["influences_control"] is False
    assert payload["config"]["site_id"] == "legacy_station_001"
    assert payload["api"]["has_console_evidence_endpoint"] is True
    assert payload["handoff"]["operator_review_required"] is True
