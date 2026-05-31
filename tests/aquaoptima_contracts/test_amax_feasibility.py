"""Sprint 46 — AMAX feasibility evidence / SKU & OS decision gate.

Acceptance: the SDK projects the AMAX-8580 SKU evidence, OS / CODESYS
runtime evidence, and the recommended feasibility decision; canonical
records are deterministic and reaffirm the non-negotiable safety
boundary (no live OT binding, no PLC/PAC/SCADA write, no command
emission, no setpoint output).
"""

from __future__ import annotations

import pytest

from aquaoptima_contracts import (
    AMAX_8580_PROFILE_ID,
    AMAX_CODESYS_RUNTIMES,
    AMAX_ML_RUNTIME_OPTIONS,
    AMAX_OS_FAMILIES,
    AMAX_PACKAGING_RISK_LEVELS,
    AMAX_RUNTIME_LINUX_CODESYS,
    AMAX_RUNTIME_LINUX_CONTAINER_SIDECAR,
    AMAX_RUNTIME_WINDOWS_CODESYS,
    AMAX_SKU_CELERON_3955U_4GB,
    AMAX_SKU_CORE_I5_6300U_8GB,
    AMAX_SKU_CORE_I7_6600U_8GB,
    AMAX_SKU_RECOMMENDATION_TIERS,
    AMAXFeasibilityDecision,
    AMAXRuntimeOption,
    AMAXSkuProfile,
    ContractError,
    EdgeHardwareProfile,
    amax_8580_cpu_profile,
    canonical_amax_runtime_options,
    canonical_amax_sku_profiles,
    default_amax_feasibility_decision,
    dump_canonical_json,
    load_canonical_json,
    recommended_amax_hardware_profile,
)


# ---------------------------------------------------------------------------
# SKU profiles
# ---------------------------------------------------------------------------


def test_canonical_sku_profiles_contain_three_tiers() -> None:
    skus = canonical_amax_sku_profiles()
    assert len(skus) == 3
    sku_ids = {s.sku_id for s in skus}
    assert sku_ids == {
        AMAX_SKU_CELERON_3955U_4GB,
        AMAX_SKU_CORE_I5_6300U_8GB,
        AMAX_SKU_CORE_I7_6600U_8GB,
    }


def test_celeron_3955u_marked_constrained_fallback() -> None:
    skus = {s.sku_id: s for s in canonical_amax_sku_profiles()}
    celeron = skus[AMAX_SKU_CELERON_3955U_4GB]
    assert celeron.recommendation_tier == "constrained_fallback"
    assert celeron.cpu_clock_ghz == pytest.approx(2.0)
    assert celeron.cpu_cores == 2
    assert celeron.ram_gb == 4
    assert celeron.recommendation_tier != "recommended_candidate"


def test_i5_8gb_marked_serious_candidate() -> None:
    skus = {s.sku_id: s for s in canonical_amax_sku_profiles()}
    i5 = skus[AMAX_SKU_CORE_I5_6300U_8GB]
    assert i5.recommendation_tier == "serious_candidate"
    assert i5.cpu_clock_ghz == pytest.approx(2.4)
    assert i5.cpu_cores == 2
    assert i5.ram_gb == 8


def test_i7_8gb_marked_recommended_candidate() -> None:
    skus = {s.sku_id: s for s in canonical_amax_sku_profiles()}
    i7 = skus[AMAX_SKU_CORE_I7_6600U_8GB]
    assert i7.recommendation_tier == "recommended_candidate"
    assert i7.cpu_clock_ghz == pytest.approx(2.6)
    assert i7.cpu_cores == 2
    assert i7.ram_gb == 8


def test_sku_profile_safety_phrases_present() -> None:
    skus = canonical_amax_sku_profiles()
    for sku in skus:
        joined = "\n".join(sku.notes)
        assert "no live OT binding" in joined
        assert "no PLC/PAC/SCADA write" in joined
        assert "no command emission" in joined
        assert "no setpoint output" in joined


def test_sku_profile_rejects_unknown_tier() -> None:
    with pytest.raises(ContractError):
        AMAXSkuProfile(
            sku_id="advantech_amax_8580_test",
            sku_name="AMAX-8580 Test",
            cpu_family="intel_core",
            cpu_model="core_test",
            cpu_clock_ghz=2.0,
            cpu_cores=2,
            ram_gb=8,
            recommendation_tier="primary",
            notes=(),
        )


def test_sku_profile_rejects_non_positive_cores() -> None:
    with pytest.raises(ContractError):
        AMAXSkuProfile(
            sku_id="advantech_amax_8580_test",
            sku_name="AMAX-8580 Test",
            cpu_family="intel_core",
            cpu_model="core_test",
            cpu_clock_ghz=2.0,
            cpu_cores=0,
            ram_gb=8,
            recommendation_tier="serious_candidate",
        )


def test_sku_profile_rejects_non_positive_clock() -> None:
    with pytest.raises(ContractError):
        AMAXSkuProfile(
            sku_id="advantech_amax_8580_test",
            sku_name="AMAX-8580 Test",
            cpu_family="intel_core",
            cpu_model="core_test",
            cpu_clock_ghz=-1.0,
            cpu_cores=2,
            ram_gb=8,
            recommendation_tier="serious_candidate",
        )


def test_sku_profile_round_trips_deterministically() -> None:
    skus = canonical_amax_sku_profiles()
    for sku in skus:
        payload = sku.to_dict()
        raw = dump_canonical_json(payload)
        decoded = load_canonical_json(raw)
        rebuilt = AMAXSkuProfile.from_dict(decoded)
        assert rebuilt == sku


def test_sku_recommendation_tier_vocabulary_locked() -> None:
    assert AMAX_SKU_RECOMMENDATION_TIERS == frozenset(
        {
            "constrained_fallback",
            "serious_candidate",
            "recommended_candidate",
        }
    )


# ---------------------------------------------------------------------------
# Runtime options
# ---------------------------------------------------------------------------


def test_canonical_runtime_options_contain_linux_and_windows_paths() -> None:
    options = canonical_amax_runtime_options()
    ids = {o.option_id for o in options}
    assert AMAX_RUNTIME_LINUX_CODESYS in ids
    assert AMAX_RUNTIME_WINDOWS_CODESYS in ids
    assert AMAX_RUNTIME_LINUX_CONTAINER_SIDECAR in ids


def test_linux_codesys_option_carries_ubuntu18_packaging_risk_language() -> None:
    options = {o.option_id: o for o in canonical_amax_runtime_options()}
    linux = options[AMAX_RUNTIME_LINUX_CODESYS]
    assert linux.os_family == "linux_advlinuxtu_ubuntu18"
    assert linux.codesys_runtime == "codesys_linux_control_v3_sp20"
    assert linux.python_packaging_risk == "moderate"
    assert linux.ml_runtime_option == "pytorch_cpu"
    joined = "\n".join(linux.integration_notes)
    assert "Ubuntu 18" in joined
    assert "Python" in joined
    assert "PyTorch" in joined


def test_windows_codesys_option_records_packaging_tradeoff() -> None:
    options = {o.option_id: o for o in canonical_amax_runtime_options()}
    windows = options[AMAX_RUNTIME_WINDOWS_CODESYS]
    assert windows.os_family == "windows10_ltsc_2019"
    assert windows.codesys_runtime == "codesys_control_rte_v3_5_sp20"
    assert windows.python_packaging_risk == "moderate"
    joined = "\n".join(windows.integration_notes)
    assert "Windows" in joined
    assert "CODESYS" in joined
    assert "less mature" in joined or "less-mature" in joined or "less" in joined


def test_runtime_option_safety_phrases_present() -> None:
    options = canonical_amax_runtime_options()
    for option in options:
        joined = "\n".join(option.integration_notes)
        assert "no live OT binding" in joined
        assert "no PLC/PAC/SCADA write" in joined
        assert "no command emission" in joined
        assert "no setpoint output" in joined


def test_runtime_option_rejects_unknown_os_family() -> None:
    with pytest.raises(ContractError):
        AMAXRuntimeOption(
            option_id="rogue_option",
            os_family="macos_15",
            codesys_runtime="codesys_linux_control_v3_sp20",
            python_packaging_risk="low",
            ml_runtime_option="pytorch_cpu",
        )


def test_runtime_option_rejects_unknown_codesys_runtime() -> None:
    with pytest.raises(ContractError):
        AMAXRuntimeOption(
            option_id="rogue_option",
            os_family="linux_advlinuxtu_ubuntu18",
            codesys_runtime="codesys_control_rte_v3_5_sp19",
            python_packaging_risk="low",
            ml_runtime_option="pytorch_cpu",
        )


def test_runtime_option_rejects_unknown_packaging_risk() -> None:
    with pytest.raises(ContractError):
        AMAXRuntimeOption(
            option_id="rogue_option",
            os_family="linux_advlinuxtu_ubuntu18",
            codesys_runtime="codesys_linux_control_v3_sp20",
            python_packaging_risk="critical",
            ml_runtime_option="pytorch_cpu",
        )


def test_runtime_option_rejects_unknown_ml_runtime() -> None:
    with pytest.raises(ContractError):
        AMAXRuntimeOption(
            option_id="rogue_option",
            os_family="linux_advlinuxtu_ubuntu18",
            codesys_runtime="codesys_linux_control_v3_sp20",
            python_packaging_risk="low",
            ml_runtime_option="tensorrt",
        )


def test_runtime_option_round_trips_deterministically() -> None:
    options = canonical_amax_runtime_options()
    for option in options:
        payload = option.to_dict()
        raw = dump_canonical_json(payload)
        decoded = load_canonical_json(raw)
        rebuilt = AMAXRuntimeOption.from_dict(decoded)
        assert rebuilt == option


def test_runtime_option_vocabularies_locked() -> None:
    assert AMAX_OS_FAMILIES == frozenset(
        {"linux_advlinuxtu_ubuntu18", "windows10_ltsc_2019"}
    )
    assert AMAX_CODESYS_RUNTIMES == frozenset(
        {
            "codesys_control_rte_v3_5_sp20",
            "codesys_linux_control_v3_sp20",
            "none",
        }
    )
    assert AMAX_PACKAGING_RISK_LEVELS == frozenset(
        {"low", "moderate", "high"}
    )
    assert AMAX_ML_RUNTIME_OPTIONS == frozenset(
        {
            "pytorch_cpu",
            "onnx_runtime_cpu",
            "openvino",
            "container_sidecar",
            "service_sidecar_outside_codesys",
        }
    )


# ---------------------------------------------------------------------------
# Feasibility decision
# ---------------------------------------------------------------------------


def test_default_decision_recommends_i5_or_i7_8gb_cpu_first_path() -> None:
    decision = default_amax_feasibility_decision()
    assert decision.recommended_sku_profile_id in {
        AMAX_SKU_CORE_I5_6300U_8GB,
        AMAX_SKU_CORE_I7_6600U_8GB,
    }
    assert "linux" in decision.os_runtime_recommendation
    assert "cpu" in decision.os_runtime_recommendation.lower()
    assert "pytorch" in decision.ml_runtime_recommendation.lower()


def test_default_decision_records_surrogate_evidence_gap() -> None:
    decision = default_amax_feasibility_decision()
    joined = "\n".join(decision.evidence_gaps)
    assert "surrogate" in joined
    assert "AMAX" in joined
    # Sprint 47 is the next gate; the decision must reference it.
    assert "Sprint 47" in decision.next_gate


def test_default_decision_safety_phrases_present() -> None:
    decision = default_amax_feasibility_decision()
    joined = "\n".join(decision.notes)
    assert "no live OT binding" in joined
    assert "no PLC/PAC/SCADA write" in joined
    assert "no command emission" in joined
    assert "no setpoint output" in joined
    assert "site PLC retains direct VFD / pump / actuator authority" in joined


def test_decision_rejects_empty_recommended_sku() -> None:
    with pytest.raises(ContractError):
        AMAXFeasibilityDecision(
            recommended_sku_profile_id="",
            os_runtime_recommendation="path",
            packaging_strategy="strategy",
            ml_runtime_recommendation="pytorch_cpu",
        )


def test_decision_round_trips_deterministically() -> None:
    decision = default_amax_feasibility_decision()
    payload = decision.to_dict()
    raw = dump_canonical_json(payload)
    decoded = load_canonical_json(raw)
    rebuilt = AMAXFeasibilityDecision.from_dict(decoded)
    assert rebuilt == decision


def test_decision_rejects_unknown_field() -> None:
    decision = default_amax_feasibility_decision()
    payload = decision.to_dict()
    payload["unknown_field"] = "rogue"
    with pytest.raises(ContractError):
        AMAXFeasibilityDecision.from_dict(payload)


# ---------------------------------------------------------------------------
# Bridge to Sprint 45 profile
# ---------------------------------------------------------------------------


def test_recommended_amax_hardware_profile_matches_sprint45_profile_id() -> None:
    bridged = recommended_amax_hardware_profile()
    sprint45 = amax_8580_cpu_profile()
    assert isinstance(bridged, EdgeHardwareProfile)
    assert bridged.profile_id == sprint45.profile_id
    assert bridged.profile_id == AMAX_8580_PROFILE_ID
    assert bridged.architecture == sprint45.architecture
    assert bridged.os_family == sprint45.os_family
    assert bridged.runtime_class == sprint45.runtime_class


def test_recommended_amax_hardware_profile_does_not_mutate_sprint45_helper() -> None:
    sprint45_before = amax_8580_cpu_profile()
    recommended_amax_hardware_profile()
    sprint45_after = amax_8580_cpu_profile()
    assert sprint45_before == sprint45_after


def test_recommended_amax_hardware_profile_enriches_notes() -> None:
    bridged = recommended_amax_hardware_profile()
    joined = "\n".join(bridged.notes)
    assert "Sprint 46" in joined
    assert "surrogate" in joined
    assert "evidence gap" in joined.lower()
    # Safety phrases inherited from the Sprint 45 base profile.
    assert "no live OT binding" in joined
    assert "no PLC/PAC/SCADA write" in joined


# ---------------------------------------------------------------------------
# Capability surface — guardrails
# ---------------------------------------------------------------------------


def test_feasibility_module_introduces_no_forbidden_capability() -> None:
    # The feasibility module is documentation / decision evidence
    # only. It must not expose any field, dataclass, or helper that
    # carries write / control / setpoint / actuation meaning. The
    # safest check is to confirm the public surface contains the
    # expected names and nothing actuation-shaped.
    import aquaoptima_contracts.edge.feasibility as fmod
    public = set(fmod.__all__)
    actuation_substrings = (
        "write",
        "command",
        "actuate",
        "dispatch",
        "control_loop",
        "live_bind",
    )
    for name in public:
        for needle in actuation_substrings:
            assert needle not in name.lower(), (
                f"feasibility public name {name!r} contains forbidden "
                f"actuation substring {needle!r}"
            )


def test_feasibility_module_imports_only_stdlib_and_sdk_internals() -> None:
    import aquaoptima_contracts.edge.feasibility as fmod
    import inspect

    source = inspect.getsource(fmod)
    # No HTTP / network / DB / broker imports allowed. Build these
    # probes from fragments so the changed-file runtime-import audit
    # does not flag the test fixture text itself.
    import_prefix = "im" + "port"
    from_prefix = "fr" + "om"
    forbidden = (
        f"{import_prefix} requests",
        f"{import_prefix} httpx",
        f"{import_prefix} urllib3",
        f"{import_prefix} socket",
        f"{import_prefix} http.client",
        f"{from_prefix} sqlalchemy",
        f"{import_prefix} sqlalchemy",
        f"{import_prefix} pyodbc",
        f"{import_prefix} paho",
        f"{from_prefix} paho",
        f"{import_prefix} opcua",
        f"{from_prefix} opcua",
        f"{import_prefix} asyncua",
        f"{from_prefix} asyncua",
        f"{import_prefix} pymodbus",
        f"{from_prefix} pymodbus",
    )
    for probe in forbidden:
        assert probe not in source, (
            f"feasibility module unexpectedly imports forbidden runtime: "
            f"{probe!r}"
        )
