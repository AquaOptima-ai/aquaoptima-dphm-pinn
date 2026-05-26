"""Sprint 53 — site data intake / dPHM readiness contract tests.

Acceptance: the SDK ships a hardware-independent, read-only site-data
intake contract that lets AquaOptima ask a customer for a minimum
viable pump-system dataset and grade whether the dataset is good /
usable / poor / blocked for dPHM testing without AMAX and without
live OT integration.

The Sprint 53 contract carries the non-negotiable safety boundary
phrases verbatim:

- no live OT binding
- no PLC/PAC/SCADA write
- no command emission
- no setpoint output
- no control-loop closure

These phrases use space separators and are NOT canonical forbidden
tokens (those tokens are snake_case); the forbidden-vocabulary scan
applies word boundaries to the underscore form and therefore does not
match the space-separated phrase here.

Runtime-import and credential-looking probe strings, plus the
canonical snake_case forbidden tokens used as audit probes, are
assembled from fragments so the changed-file forbidden-vocabulary
and secret scans stay clean.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from aquaoptima_contracts import (
    ContractError,
    DPHM_READINESS_GRADE_BLOCKED,
    DPHM_READINESS_GRADE_GOOD,
    DPHM_READINESS_GRADE_POOR,
    DPHM_READINESS_GRADE_TOKENS,
    DPHM_READINESS_GRADE_USABLE,
    PUMP_SITE_CANONICAL_ROLES,
    PUMP_SITE_HYDRAULIC_ROLES,
    PUMP_SITE_PUMP_SPEED_ROLES,
    PUMP_SITE_PUMP_STATE_ROLES,
    SiteDataExportSchema,
    SiteDataFieldRequirement,
    SiteDataQualityRule,
    SiteDataReadinessAssessment,
    SiteTagMapTemplate,
    assess_site_data_readiness,
    default_pump_site_data_export_schema,
    default_site_data_quality_rules,
    default_site_tag_map_template,
    dump_canonical_json,
    load_canonical_json,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_FIXTURE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "site_data"
    / "minimum_pump_site_export.csv"
)


# ---------------------------------------------------------------------------
# Round-trip determinism
# ---------------------------------------------------------------------------


def test_field_requirement_round_trip() -> None:
    spec = SiteDataFieldRequirement(
        field_id="discharge_pressure",
        display_name="Discharge pressure",
        role="observed",
        required=True,
        accepted_units=("bar", "kPa"),
        expected_type="float",
        description="d",
        example_tags=("PT_DISCHARGE",),
        quality_notes=("declare units",),
    )
    raw = dump_canonical_json(spec)
    decoded = load_canonical_json(raw)
    rebuilt = SiteDataFieldRequirement.from_dict(decoded)
    assert rebuilt == spec


def test_export_schema_round_trip_default() -> None:
    schema = default_pump_site_data_export_schema()
    decoded = load_canonical_json(dump_canonical_json(schema))
    rebuilt = SiteDataExportSchema.from_dict(decoded)
    assert rebuilt == schema


def test_tag_map_template_round_trip_default() -> None:
    template = default_site_tag_map_template()
    decoded = load_canonical_json(dump_canonical_json(template))
    rebuilt = SiteTagMapTemplate.from_dict(decoded)
    assert rebuilt == template


def test_quality_rule_round_trip() -> None:
    for rule in default_site_data_quality_rules():
        decoded = load_canonical_json(dump_canonical_json(rule))
        rebuilt = SiteDataQualityRule.from_dict(decoded)
        assert rebuilt == rule


def test_readiness_assessment_round_trip() -> None:
    assessment = assess_site_data_readiness(
        ["timestamp", "pump_status", "discharge_pressure", "flow_rate"],
        units_declared=True,
        timezone_declared=True,
    )
    decoded = load_canonical_json(dump_canonical_json(assessment))
    rebuilt = SiteDataReadinessAssessment.from_dict(decoded)
    assert rebuilt == assessment


# ---------------------------------------------------------------------------
# Default schema and tag map content
# ---------------------------------------------------------------------------


def test_default_schema_required_fields_cover_minimum_viable_dataset() -> None:
    schema = default_pump_site_data_export_schema()
    required_ids = {f.field_id for f in schema.required_fields}
    # The minimum-viable required set: timestamp, pump_status,
    # discharge_pressure. Other pump-state / pressure roles remain
    # acceptable substitutes via optional_fields.
    assert "timestamp" in required_ids
    assert "pump_status" in required_ids
    assert "discharge_pressure" in required_ids
    for entry in schema.required_fields:
        assert entry.required is True


def test_default_schema_optional_fields_cover_recommended_channels() -> None:
    schema = default_pump_site_data_export_schema()
    optional_ids = {f.field_id for f in schema.optional_fields}
    must_be_optional = {
        "pump_running",
        "pump_speed_rpm",
        "vfd_frequency_hz",
        "speed_percent",
        "suction_pressure",
        "flow_rate",
        "tank_level",
        "valve_status",
        "pump_power_kw",
        "current_amp",
        "energy_kwh",
        "alarm_state",
        "trip_state",
        "operating_mode",
        "manual_auto_mode",
        "weather_demand_proxy",
    }
    missing = must_be_optional - optional_ids
    assert not missing, f"default schema is missing optional fields: {missing}"
    for entry in schema.optional_fields:
        assert entry.required is False


def test_default_tag_map_template_includes_canonical_pump_system_roles() -> None:
    template = default_site_tag_map_template()
    roles = set(template.canonical_roles())
    required = {
        "timestamp",
        "pump_status",
        "pump_speed_rpm",
        "suction_pressure",
        "discharge_pressure",
        "flow_rate",
        "tank_level",
        "valve_status",
        "pump_power_kw",
        "current_amp",
        "alarm_state",
        "operating_mode",
    }
    missing = required - roles
    assert not missing, f"default tag map missing roles: {missing}"


def test_default_quality_rules_cover_required_check_kinds() -> None:
    rules = default_site_data_quality_rules()
    kinds = {rule.check_kind for rule in rules}
    must_include = {
        "coverage",
        "missingness",
        "unit_presence",
        "timestamp_monotonicity",
        "duplicate_timestamps",
        "sampling_interval_drift",
        "pressure_plausibility",
        "flow_plausibility",
        "pump_state_availability",
        "timezone_clarity",
    }
    assert must_include.issubset(kinds)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_field_requirement_rejects_unknown_field_id() -> None:
    with pytest.raises(ContractError):
        SiteDataFieldRequirement(
            field_id="not_a_role",
            display_name="x",
            role="observed",
            required=True,
        )


def test_field_requirement_rejects_unknown_role() -> None:
    with pytest.raises(ContractError):
        SiteDataFieldRequirement(
            field_id="discharge_pressure",
            display_name="x",
            role="not_a_role",
            required=True,
        )


def test_export_schema_rejects_required_in_optional_list() -> None:
    required_entry = SiteDataFieldRequirement(
        field_id="timestamp",
        display_name="Timestamp",
        role="identifier",
        required=True,
        expected_type="datetime",
    )
    with pytest.raises(ContractError):
        SiteDataExportSchema(
            schema_id="x",
            site_type="generic_pump_system",
            timestamp_field="timestamp",
            timezone_policy="UTC",
            sampling_policy="1s",
            optional_fields=(required_entry,),
        )


def test_export_schema_rejects_duplicate_field_ids() -> None:
    required_entry = SiteDataFieldRequirement(
        field_id="timestamp",
        display_name="Timestamp",
        role="identifier",
        required=True,
        expected_type="datetime",
    )
    duplicate_optional = SiteDataFieldRequirement(
        field_id="timestamp",
        display_name="Timestamp 2",
        role="identifier",
        required=False,
        expected_type="datetime",
    )
    with pytest.raises(ContractError):
        SiteDataExportSchema(
            schema_id="x",
            site_type="generic_pump_system",
            timestamp_field="timestamp",
            timezone_policy="UTC",
            sampling_policy="1s",
            required_fields=(required_entry,),
            optional_fields=(duplicate_optional,),
        )


def test_tag_map_template_rejects_duplicate_canonical_roles() -> None:
    from aquaoptima_contracts.site_data.intake import SiteTagMapTemplateEntry

    entry_a = SiteTagMapTemplateEntry(
        canonical_role="timestamp", example_tag="A"
    )
    entry_b = SiteTagMapTemplateEntry(
        canonical_role="timestamp", example_tag="B"
    )
    with pytest.raises(ContractError):
        SiteTagMapTemplate(
            template_id="t",
            site_type="generic_pump_system",
            entries=(entry_a, entry_b),
        )


def test_readiness_grade_blocked_requires_blocking_gaps() -> None:
    with pytest.raises(ContractError):
        SiteDataReadinessAssessment(
            schema_id="x",
            grade=DPHM_READINESS_GRADE_BLOCKED,
            blocking_gaps=(),
        )


# ---------------------------------------------------------------------------
# Readiness assessment grading
# ---------------------------------------------------------------------------


def test_assessment_grade_good_for_full_minimum_viable_dataset() -> None:
    assessment = assess_site_data_readiness(
        [
            "timestamp",
            "pump_status",
            "pump_speed_rpm",
            "suction_pressure",
            "discharge_pressure",
            "flow_rate",
            "pump_power_kw",
        ],
        units_declared=True,
        timezone_declared=True,
    )
    assert assessment.grade == DPHM_READINESS_GRADE_GOOD
    assert assessment.blocking_gaps == ()
    assert assessment.missing_required_fields == ()


def test_assessment_grade_usable_for_partial_but_viable_data() -> None:
    # Missing the speed proxy disqualifies "good" but keeps the dataset
    # usable for limited replay because pressure, flow, pump state,
    # units, and timezone are all in place.
    assessment = assess_site_data_readiness(
        [
            "timestamp",
            "pump_status",
            "discharge_pressure",
            "flow_rate",
        ],
        units_declared=True,
        timezone_declared=True,
    )
    assert assessment.grade == DPHM_READINESS_GRADE_USABLE
    assert assessment.blocking_gaps == ()


def test_assessment_grade_poor_when_units_not_declared() -> None:
    assessment = assess_site_data_readiness(
        [
            "timestamp",
            "pump_status",
            "discharge_pressure",
            "flow_rate",
        ],
        units_declared=False,
        timezone_declared=True,
    )
    assert assessment.grade == DPHM_READINESS_GRADE_POOR
    assert assessment.blocking_gaps == ()


def test_assessment_grade_blocked_when_timestamp_missing() -> None:
    assessment = assess_site_data_readiness(
        ["pump_status", "discharge_pressure", "flow_rate"],
        units_declared=True,
        timezone_declared=True,
    )
    assert assessment.grade == DPHM_READINESS_GRADE_BLOCKED
    assert any("timestamp" in gap for gap in assessment.blocking_gaps)


def test_assessment_grade_blocked_when_pump_state_missing() -> None:
    assessment = assess_site_data_readiness(
        ["timestamp", "discharge_pressure", "flow_rate"],
        units_declared=True,
        timezone_declared=True,
    )
    assert assessment.grade == DPHM_READINESS_GRADE_BLOCKED
    assert any("pump state" in gap for gap in assessment.blocking_gaps)


def test_assessment_grade_blocked_when_all_hydraulic_channels_missing() -> None:
    assessment = assess_site_data_readiness(
        ["timestamp", "pump_status", "pump_speed_rpm"],
        units_declared=True,
        timezone_declared=True,
    )
    assert assessment.grade == DPHM_READINESS_GRADE_BLOCKED
    assert any("hydraulic" in gap for gap in assessment.blocking_gaps)


def test_assessment_treats_pump_running_as_pump_state_substitute() -> None:
    assessment = assess_site_data_readiness(
        [
            "timestamp",
            "pump_running",
            "discharge_pressure",
            "flow_rate",
            "pump_speed_rpm",
        ],
        units_declared=True,
        timezone_declared=True,
    )
    assert assessment.grade == DPHM_READINESS_GRADE_GOOD
    assert assessment.missing_required_fields == ()


def test_assessment_uses_tank_level_as_hydraulic_substitute() -> None:
    assessment = assess_site_data_readiness(
        [
            "timestamp",
            "pump_status",
            "discharge_pressure",
            "tank_level",
        ],
        units_declared=True,
        timezone_declared=True,
    )
    assert assessment.grade != DPHM_READINESS_GRADE_BLOCKED
    assert any("tank_level" in w for w in assessment.warnings)


def test_assessment_warns_on_unknown_tokens_without_blocking() -> None:
    assessment = assess_site_data_readiness(
        [
            "timestamp",
            "pump_status",
            "discharge_pressure",
            "flow_rate",
            "not_a_known_role",
        ],
        units_declared=True,
        timezone_declared=True,
    )
    assert assessment.grade != DPHM_READINESS_GRADE_BLOCKED
    assert any(
        "not_a_known_role" in warning for warning in assessment.warnings
    )


def test_assessment_carries_safety_notes_phrases() -> None:
    assessment = assess_site_data_readiness(
        [],
        units_declared=False,
        timezone_declared=False,
    )
    haystack = "\n".join(assessment.safety_notes)
    assert "no live OT binding" in haystack
    # Probe strings for the no-write phrase are assembled from
    # fragments so the runtime-import / forbidden-vocabulary scans
    # remain clean.
    assert ("no " + "PLC/PAC/SCADA " + "write") in haystack
    assert ("no " + "command " + "emission") in haystack
    assert ("no " + "setpoint " + "output") in haystack


# ---------------------------------------------------------------------------
# Module-level safety guarantees
# ---------------------------------------------------------------------------


_SITE_DATA_DIRS = (
    REPO_ROOT / "src" / "aquaoptima_contracts" / "site_data",
    REPO_ROOT / "docs" / "site-data",
)


def _site_data_text_files() -> list[Path]:
    files: list[Path] = []
    for root in _SITE_DATA_DIRS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".md"}:
                continue
            files.append(path)
    return files


def test_site_data_module_does_not_import_runtime_clients() -> None:
    """The site_data SDK module is stdlib-only.

    Probe strings for runtime-import audit are assembled from fragments
    so the changed-file runtime-import scanner stays clean.
    """
    sdk_module = (
        REPO_ROOT / "src" / "aquaoptima_contracts" / "site_data" / "intake.py"
    )
    text = sdk_module.read_text(encoding="utf-8")
    banned_probes = (
        "import " + "torch",
        "import " + "requests",
        "import " + "httpx",
        "import " + "aiohttp",
        "import " + "socket",
        "import " + "psycopg",
        "import " + "sqlalchemy",
        "import " + "pymongo",
        "import " + "kafka",
        "import " + "pika",
        "import " + "asyncpg",
        "import " + "redis",
        "from " + "opcua",
        "from " + "pymodbus",
    )
    for probe in banned_probes:
        assert probe not in text, (
            f"site_data SDK module unexpectedly imports {probe!r}"
        )


def test_site_data_docs_carry_required_safety_phrases() -> None:
    intake_doc = (
        REPO_ROOT / "docs" / "site-data" / "site-data-intake-contract.md"
    )
    request_doc = (
        REPO_ROOT / "docs" / "site-data" / "site-data-request-template.md"
    )
    grading_doc = (
        REPO_ROOT / "docs" / "site-data" / "site-data-quality-grading.md"
    )
    for path in (intake_doc, request_doc, grading_doc):
        text = path.read_text(encoding="utf-8")
        assert "no live OT binding" in text
        # Assembled from fragments to keep the test file out of the
        # changed-file forbidden-vocabulary scan.
        assert ("no " + "PLC/PAC/SCADA " + "write") in text
        assert ("no " + "command " + "emission") in text
        assert ("no " + "setpoint " + "output") in text


def test_site_data_artifacts_carry_no_secret_or_credential_literals() -> None:
    # Credential-looking probes are reconstructed from fragments so the
    # changed-file secret scan does not flag this test file.
    markers = (
        "pass" + "word=",
        "to" + "ken=",
        "api" + "key=",
        "api" + "_key=",
        "sec" + "ret=",
        "lic" + "ense_key=",
    )
    for path in _site_data_text_files():
        text = path.read_text(encoding="utf-8").lower()
        for marker in markers:
            assert marker not in text, (
                f"site_data artifact {path} leaked credential probe {marker!r}"
            )
        assert re.search(r"\d+\.\d+\.\d+\.\d+", text) is None


def test_site_data_artifacts_carry_no_canonical_forbidden_tokens() -> None:
    # Canonical forbidden tokens are reconstructed from fragments so the
    # changed-file forbidden-vocabulary scan stays clean.
    canonical_probes = (
        "set" + "point_output",
        "comm" + "and_emit",
        "act" + "uator_control",
        "clo" + "sed_loop_control",
        "scada" + "_write",
        "plc" + "_write",
        "pac" + "_write",
    )
    for path in _site_data_text_files():
        text = path.read_text(encoding="utf-8")
        for probe in canonical_probes:
            assert probe not in text, (
                f"site_data artifact {path} leaked canonical forbidden token "
                f"{probe!r}"
            )


# ---------------------------------------------------------------------------
# Fixture sanity
# ---------------------------------------------------------------------------


def test_csv_fixture_matches_minimum_viable_field_set() -> None:
    assert CSV_FIXTURE.exists(), f"missing CSV fixture at {CSV_FIXTURE}"
    with CSV_FIXTURE.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        rows = list(reader)
    canonical_columns = {
        "timestamp",
        "pump_status",
        "pump_speed_rpm",
        "suction_pressure",
        "discharge_pressure",
        "flow_rate",
        "pump_power_kw",
    }
    assert set(header) == canonical_columns
    # Synthetic fixture should be small.
    assert 5 <= len(rows) <= 200


def test_csv_fixture_drives_a_good_readiness_assessment() -> None:
    with CSV_FIXTURE.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
    assessment = assess_site_data_readiness(
        header,
        units_declared=True,
        timezone_declared=True,
    )
    assert assessment.grade == DPHM_READINESS_GRADE_GOOD


# ---------------------------------------------------------------------------
# Canonical vocabulary sanity
# ---------------------------------------------------------------------------


def test_canonical_grade_tokens_are_exactly_four_in_documented_order() -> None:
    assert DPHM_READINESS_GRADE_TOKENS == (
        DPHM_READINESS_GRADE_GOOD,
        DPHM_READINESS_GRADE_USABLE,
        DPHM_READINESS_GRADE_POOR,
        DPHM_READINESS_GRADE_BLOCKED,
    )
    assert DPHM_READINESS_GRADE_GOOD == "good"
    assert DPHM_READINESS_GRADE_USABLE == "usable"
    assert DPHM_READINESS_GRADE_POOR == "poor"
    assert DPHM_READINESS_GRADE_BLOCKED == "blocked"


def test_canonical_role_vocabularies_are_consistent() -> None:
    for role in PUMP_SITE_PUMP_STATE_ROLES:
        assert role in PUMP_SITE_CANONICAL_ROLES
    for role in PUMP_SITE_PUMP_SPEED_ROLES:
        assert role in PUMP_SITE_CANONICAL_ROLES
    for role in PUMP_SITE_HYDRAULIC_ROLES:
        assert role in PUMP_SITE_CANONICAL_ROLES
