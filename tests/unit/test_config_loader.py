from pathlib import Path

import pytest

from aquaoptima_lite.config import compute_config_hash, load_site_config

CONFIG_PATH = Path("config/examples/legacy_station_001.yaml")


def test_load_legacy_station_config_and_hash_is_stable():
    config = load_site_config(CONFIG_PATH)

    assert config.site_id == "legacy_station_001"
    assert config.runtime.default_mode == "baseline_plus_learning_shadow"
    assert config.safety.baseline_control_enabled is True
    assert config.safety.future_control_enabled is False
    assert config.pump_by_id("pump_1") is not None
    assert config.tag_by_canonical("discharge_pressure_bar") is not None

    first_hash = compute_config_hash(config)
    second_hash = compute_config_hash(load_site_config(CONFIG_PATH))
    assert len(first_hash) == 64
    assert first_hash == second_hash


def test_load_config_rejects_missing_required_sections(tmp_path):
    bad_config = tmp_path / "bad.yaml"
    bad_config.write_text("site:\n  id: x\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required"):
        load_site_config(bad_config)
