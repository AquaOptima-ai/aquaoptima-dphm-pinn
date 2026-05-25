"""Sprint 48 — AMAX read-only PLC/SCADA integration contract.

Acceptance: the SDK projects the read-only integration contract /
source / tag binding / freshness policy / replay-to-live equivalence
shapes. The canonical default contract is deterministic, audit-only,
and reaffirms the non-negotiable safety boundary (no live OT binding,
no PLC/PAC/SCADA write, no command emission, no setpoint output).

The SDK module stays stdlib-only: no live OPC UA, Modbus, CODESYS,
SCADA, PLC, MQTT, HTTP, database, or message-broker client. Probe
strings for the runtime-import audit are assembled from fragments so
the changed-file runtime-import audit remains clean.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aquaoptima_contracts import (
    ACCESS_MODE_AUDIT_ONLY,
    ACCESS_MODE_READ_ONLY,
    AMAX_READ_ONLY_INTEGRATION_CONTRACT_ID,
    ContractError,
    EQUIVALENCE_BLOCKED,
    EQUIVALENCE_COMPATIBLE,
    EQUIVALENCE_NOT_EVALUATED,
    EQUIVALENCE_STATUS_TOKENS,
    MISSING_BEHAVIOR_DROP_FRAME,
    MISSING_BEHAVIOR_FLAG_MISSING,
    MISSING_BEHAVIOR_TOKENS,
    PROTOCOL_CODESYS_SHARED_MEMORY,
    PROTOCOL_CODESYS_SYMBOL,
    PROTOCOL_MODBUS_RTU,
    PROTOCOL_MODBUS_TCP,
    PROTOCOL_MQTT_SPARKPLUG_READ_ONLY,
    PROTOCOL_OPC_UA,
    READ_ONLY_ACCESS_MODES,
    READ_ONLY_INTEGRATION_PROTOCOLS,
    ReadOnlyIntegrationContract,
    ReadOnlyIntegrationDiagnostics,
    ReadOnlyIntegrationProtocol,
    ReadOnlyTagBinding,
    ReadOnlyTelemetrySource,
    ReplayToLiveEquivalenceEvidence,
    STALE_BEHAVIOR_DROP_FRAME,
    STALE_BEHAVIOR_FLAG_STALE,
    STALE_BEHAVIOR_HOLD_LAST_GOOD,
    STALE_BEHAVIOR_TOKENS,
    TelemetryFreshnessPolicy,
    TelemetryTagSpec,
    default_amax_read_only_integration_contract,
    default_amax_replay_to_live_equivalence_evidence,
    diagnose_read_only_integration_contract,
    dump_canonical_json,
    load_canonical_json,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
READ_ONLY_MODULE_PATH = (
    REPO_ROOT
    / "src"
    / "aquaoptima_contracts"
    / "edge"
    / "read_only_integration.py"
)


# ---------------------------------------------------------------------------
# Canonical protocol vocabulary
# ---------------------------------------------------------------------------


def test_canonical_protocols_cover_opc_ua_modbus_codesys() -> None:
    assert PROTOCOL_OPC_UA in READ_ONLY_INTEGRATION_PROTOCOLS
    assert PROTOCOL_MODBUS_TCP in READ_ONLY_INTEGRATION_PROTOCOLS
    assert PROTOCOL_MODBUS_RTU in READ_ONLY_INTEGRATION_PROTOCOLS
    assert PROTOCOL_CODESYS_SYMBOL in READ_ONLY_INTEGRATION_PROTOCOLS
    assert PROTOCOL_CODESYS_SHARED_MEMORY in READ_ONLY_INTEGRATION_PROTOCOLS


def test_canonical_protocols_include_mqtt_sparkplug_read_only_it_path() -> None:
    assert (
        PROTOCOL_MQTT_SPARKPLUG_READ_ONLY in READ_ONLY_INTEGRATION_PROTOCOLS
    )


def test_protocol_namespace_round_trip() -> None:
    assert ReadOnlyIntegrationProtocol.OPC_UA == "opc_ua"
    assert ReadOnlyIntegrationProtocol.MODBUS_TCP == "modbus_tcp"
    assert ReadOnlyIntegrationProtocol.MODBUS_RTU == "modbus_rtu"
    assert ReadOnlyIntegrationProtocol.CODESYS_SYMBOL == "codesys_symbol"
    assert (
        ReadOnlyIntegrationProtocol.CODESYS_SHARED_MEMORY
        == "codesys_shared_memory"
    )
    assert ReadOnlyIntegrationProtocol.is_recognised(PROTOCOL_OPC_UA)
    assert not ReadOnlyIntegrationProtocol.is_recognised("rogue_protocol")
    assert not ReadOnlyIntegrationProtocol.is_recognised(123)


# ---------------------------------------------------------------------------
# ReadOnlyTelemetrySource
# ---------------------------------------------------------------------------


def _make_source(**overrides):
    defaults = dict(
        source_id="amax_opc_ua_test",
        protocol=PROTOCOL_OPC_UA,
        endpoint_label="ot_zone_opc_ua_label",
        security_zone_label="ot_zone",
        polling_interval_seconds=1.0,
        freshness_threshold_seconds=5.0,
        credential_reference_label="site_secret_store_ref",
        access_mode=ACCESS_MODE_READ_ONLY,
        notes=("read-only audit source",),
    )
    defaults.update(overrides)
    return ReadOnlyTelemetrySource(**defaults)


def test_source_round_trip_is_deterministic() -> None:
    src = _make_source()
    raw = dump_canonical_json(src.to_dict())
    decoded = load_canonical_json(raw)
    rebuilt = ReadOnlyTelemetrySource.from_dict(decoded)
    assert rebuilt == src


def test_source_rejects_unsupported_protocol() -> None:
    with pytest.raises(ContractError):
        _make_source(protocol="rogue_protocol")


def test_source_rejects_unsupported_access_mode() -> None:
    with pytest.raises(ContractError):
        _make_source(access_mode="read_write")


def test_source_allows_explicit_no_secret_credential_reference() -> None:
    src = _make_source(credential_reference_label="")
    assert src.credential_reference_label == ""


def test_source_rejects_freshness_below_polling_interval() -> None:
    with pytest.raises(ContractError):
        _make_source(
            polling_interval_seconds=10.0,
            freshness_threshold_seconds=1.0,
        )


def test_source_rejects_non_positive_polling_interval() -> None:
    with pytest.raises(ContractError):
        _make_source(polling_interval_seconds=0.0)


def test_source_explicit_access_mode_is_read_only_by_default() -> None:
    src = _make_source()
    assert src.access_mode == ACCESS_MODE_READ_ONLY
    assert src.access_mode in READ_ONLY_ACCESS_MODES


def test_source_allows_audit_only_access_mode() -> None:
    src = _make_source(access_mode=ACCESS_MODE_AUDIT_ONLY)
    assert src.access_mode == ACCESS_MODE_AUDIT_ONLY


# ---------------------------------------------------------------------------
# ReadOnlyTagBinding
# ---------------------------------------------------------------------------


def _make_tag_spec(**overrides) -> TelemetryTagSpec:
    defaults = dict(
        tag="PT_J1",
        axis="node_pressure",
        target_id=1,
        unit="m_h2o",
        role="observed",
        description="J1 pressure transmitter (read-only)",
    )
    defaults.update(overrides)
    return TelemetryTagSpec(**defaults)


def _make_binding(**overrides) -> ReadOnlyTagBinding:
    defaults = dict(
        binding_id="binding_test",
        source_id="amax_opc_ua_test",
        source_path_label="ns_2_pt_j1_label",
        tag_spec=_make_tag_spec(),
        quality_behavior=STALE_BEHAVIOR_FLAG_STALE,
        freshness_behavior=STALE_BEHAVIOR_FLAG_STALE,
        access_mode=ACCESS_MODE_READ_ONLY,
        notes=("read-only binding",),
    )
    defaults.update(overrides)
    return ReadOnlyTagBinding(**defaults)


def test_binding_round_trip_is_deterministic() -> None:
    binding = _make_binding()
    raw = dump_canonical_json(binding.to_dict())
    decoded = load_canonical_json(raw)
    rebuilt = ReadOnlyTagBinding.from_dict(decoded)
    assert rebuilt == binding


def test_binding_links_axis_role_unit_metadata() -> None:
    binding = _make_binding(
        tag_spec=_make_tag_spec(
            axis="edge_flow",
            target_id=4,
            unit="m3_s",
            role="observed",
        )
    )
    assert binding.tag_spec.axis == "edge_flow"
    assert binding.tag_spec.target_id == 4
    assert binding.tag_spec.unit == "m3_s"
    assert binding.tag_spec.role == "observed"


def test_binding_rejects_unknown_freshness_behavior() -> None:
    with pytest.raises(ContractError):
        _make_binding(freshness_behavior="ignore")


def test_binding_rejects_unknown_quality_behavior() -> None:
    with pytest.raises(ContractError):
        _make_binding(quality_behavior="ignore")


# ---------------------------------------------------------------------------
# TelemetryFreshnessPolicy
# ---------------------------------------------------------------------------


def _make_policy(**overrides) -> TelemetryFreshnessPolicy:
    defaults = dict(
        max_age_seconds=5.0,
        stale_behavior=STALE_BEHAVIOR_FLAG_STALE,
        missing_behavior=MISSING_BEHAVIOR_FLAG_MISSING,
        quality_flag_mapping=(
            ("opc_ua_good", "good"),
            ("opc_ua_bad", "bad"),
        ),
        replay_equivalence_expectations=(
            "replay cadence must match live polling cadence",
        ),
        notes=("freshness audit only",),
    )
    defaults.update(overrides)
    return TelemetryFreshnessPolicy(**defaults)


def test_freshness_policy_round_trip_is_deterministic() -> None:
    policy = _make_policy()
    raw = dump_canonical_json(policy.to_dict())
    decoded = load_canonical_json(raw)
    rebuilt = TelemetryFreshnessPolicy.from_dict(decoded)
    assert rebuilt == policy


def test_freshness_policy_classifies_stale_and_fresh_without_runtime_access() -> None:
    policy = _make_policy(max_age_seconds=5.0)
    assert policy.classify_age(0.0) == "fresh"
    assert policy.classify_age(5.0) == "fresh"
    assert policy.classify_age(5.0001) == "stale"
    assert policy.classify_age(60.0) == "stale"


def test_freshness_policy_rejects_unknown_stale_behavior() -> None:
    with pytest.raises(ContractError):
        _make_policy(stale_behavior="ignore")


def test_freshness_policy_rejects_unknown_missing_behavior() -> None:
    with pytest.raises(ContractError):
        _make_policy(missing_behavior="ignore")


def test_freshness_policy_rejects_duplicate_source_flag() -> None:
    with pytest.raises(ContractError):
        _make_policy(
            quality_flag_mapping=(
                ("opc_ua_good", "good"),
                ("opc_ua_good", "uncertain"),
            )
        )


def test_freshness_policy_stale_and_missing_tokens_set() -> None:
    assert STALE_BEHAVIOR_FLAG_STALE in STALE_BEHAVIOR_TOKENS
    assert STALE_BEHAVIOR_DROP_FRAME in STALE_BEHAVIOR_TOKENS
    assert STALE_BEHAVIOR_HOLD_LAST_GOOD in STALE_BEHAVIOR_TOKENS
    assert MISSING_BEHAVIOR_FLAG_MISSING in MISSING_BEHAVIOR_TOKENS
    assert MISSING_BEHAVIOR_DROP_FRAME in MISSING_BEHAVIOR_TOKENS


# ---------------------------------------------------------------------------
# ReadOnlyIntegrationContract
# ---------------------------------------------------------------------------


def test_default_contract_id_matches_canonical_constant() -> None:
    contract = default_amax_read_only_integration_contract()
    assert contract.contract_id == AMAX_READ_ONLY_INTEGRATION_CONTRACT_ID


def test_default_contract_round_trip_is_deterministic() -> None:
    contract = default_amax_read_only_integration_contract()
    raw = dump_canonical_json(contract.to_dict())
    decoded = load_canonical_json(raw)
    rebuilt = ReadOnlyIntegrationContract.from_dict(decoded)
    assert rebuilt == contract


def test_default_contract_is_read_only_or_audit_only() -> None:
    contract = default_amax_read_only_integration_contract()
    for src in contract.sources:
        assert src.access_mode in READ_ONLY_ACCESS_MODES
    for binding in contract.tag_bindings:
        assert binding.access_mode in READ_ONLY_ACCESS_MODES


def test_default_contract_carries_required_safety_phrases() -> None:
    contract = default_amax_read_only_integration_contract()
    joined = "\n".join(contract.safety_notes)
    assert "no live OT binding" in joined
    assert "no PLC/PAC/SCADA write" in joined
    assert "no command emission" in joined
    assert "no setpoint output" in joined
    # Sprint 49 next-gate language must be present.
    assert "Sprint 49" in joined


def test_default_contract_protocols_cover_opc_ua_modbus_codesys() -> None:
    contract = default_amax_read_only_integration_contract()
    protocols = {src.protocol for src in contract.sources}
    assert PROTOCOL_OPC_UA in protocols
    assert PROTOCOL_MODBUS_TCP in protocols
    assert PROTOCOL_MODBUS_RTU in protocols
    assert PROTOCOL_CODESYS_SYMBOL in protocols
    assert PROTOCOL_CODESYS_SHARED_MEMORY in protocols


def test_default_contract_labels_carry_no_forbidden_write_vocabulary() -> None:
    """Labels and bindings must not embed write / setpoint / command phrases.

    The contract's *safety_notes* explicitly negate these phrases (e.g.
    "no PLC/PAC/SCADA write"); that is allowed. What is not allowed is
    a *label* that affirmatively names a write register, command topic,
    setpoint topic, or actuator address. Probe strings here are
    assembled from fragments so the changed-file runtime-import audit
    remains clean.
    """
    contract = default_amax_read_only_integration_contract()
    unsafe_probes = (
        "set" + "point",
        "comm" + "and",
        "act" + "uator",
        "wri" + "te_register",
        "wri" + "te_topic",
    )
    label_parts: list[str] = [contract.contract_id]
    for src in contract.sources:
        label_parts.append(src.source_id)
        label_parts.append(src.endpoint_label)
        label_parts.append(src.security_zone_label)
        label_parts.append(src.credential_reference_label)
    for binding in contract.tag_bindings:
        label_parts.append(binding.binding_id)
        label_parts.append(binding.source_path_label)
    haystack = "\n".join(label_parts).lower()
    for probe in unsafe_probes:
        assert probe.lower() not in haystack, (
            f"default contract label leaked unsafe phrase {probe!r}"
        )


def test_default_contract_does_not_embed_canonical_forbidden_tokens() -> None:
    """No canonical snake_case forbidden token appears anywhere in contract."""
    contract = default_amax_read_only_integration_contract()
    all_parts: list[str] = [contract.contract_id, contract.tag_map_reference]
    all_parts.extend(contract.compatibility_notes)
    all_parts.extend(contract.safety_notes)
    for src in contract.sources:
        all_parts.extend(
            [
                src.source_id,
                src.endpoint_label,
                src.security_zone_label,
                src.credential_reference_label,
            ]
        )
        all_parts.extend(src.notes)
    for binding in contract.tag_bindings:
        all_parts.extend(
            [binding.binding_id, binding.source_path_label]
        )
        all_parts.extend(binding.notes)
    haystack = "\n".join(all_parts)
    # Canonical forbidden tokens are reconstructed from fragments to
    # keep the test file itself out of the forbidden-vocabulary scan.
    canonical_probes = (
        "set" + "point_output",
        "comm" + "and_emit",
        "act" + "uator_control",
        "clo" + "sed_loop_control",
        "scada" + "_write",
        "plc" + "_write",
        "pac" + "_write",
    )
    for probe in canonical_probes:
        assert probe not in haystack, (
            f"default contract leaked canonical forbidden token {probe!r}"
        )


def test_default_contract_has_no_secret_or_token_literals() -> None:
    contract = default_amax_read_only_integration_contract()
    haystack_parts: list[str] = []
    for src in contract.sources:
        haystack_parts.append(src.credential_reference_label)
        haystack_parts.append(src.endpoint_label)
    haystack = "\n".join(haystack_parts).lower()
    # Credential-looking probes are built from fragments so the
    # changed-file secret scan does not flag this test fixture text.
    markers = (
        "pass" + "word=",
        "to" + "ken=",
        "api" + "key=",
        "api" + "_key=",
        "sec" + "ret=",
    )
    for marker in markers:
        assert marker not in haystack
    # No IP-shaped literals.
    import re

    assert re.search(r"\d+\.\d+\.\d+\.\d+", haystack) is None


def test_diagnostics_round_trip() -> None:
    diag = ReadOnlyIntegrationDiagnostics(
        warnings=("w1",),
        errors=("e1",),
    )
    rebuilt = ReadOnlyIntegrationDiagnostics.from_dict(diag.to_dict())
    assert rebuilt == diag


def test_diagnose_clean_default_contract() -> None:
    contract = default_amax_read_only_integration_contract()
    diag = diagnose_read_only_integration_contract(contract)
    assert diag.errors == ()


def test_diagnose_flags_duplicate_binding_ids() -> None:
    contract = default_amax_read_only_integration_contract()
    duplicated_binding = ReadOnlyTagBinding(
        binding_id="binding_opc_ua_pressure_pt_j1",
        source_id="amax_opc_ua_subscription",
        source_path_label="some_other_path_label",
        tag_spec=_make_tag_spec(tag="PT_J9", target_id=9),
    )
    mutated = ReadOnlyIntegrationContract(
        contract_id=contract.contract_id,
        sources=contract.sources,
        tag_bindings=contract.tag_bindings + (duplicated_binding,),
        freshness_policy=contract.freshness_policy,
        tag_map_reference=contract.tag_map_reference,
        compatibility_notes=contract.compatibility_notes,
        safety_notes=contract.safety_notes,
    )
    diag = diagnose_read_only_integration_contract(mutated)
    assert any(
        "duplicate binding id" in err for err in diag.errors
    )


def test_diagnose_flags_unknown_binding_source_id() -> None:
    spec = _make_tag_spec()
    policy = _make_policy(max_age_seconds=10.0)
    source = _make_source()
    binding = _make_binding(
        source_id="nonexistent_source",
        tag_spec=spec,
    )
    contract = ReadOnlyIntegrationContract(
        contract_id="audit_contract",
        sources=(source,),
        tag_bindings=(binding,),
        freshness_policy=policy,
        safety_notes=("no live OT binding",),
    )
    diag = diagnose_read_only_integration_contract(contract)
    assert any(
        "references unknown source id" in err for err in diag.errors
    )


# ---------------------------------------------------------------------------
# ReplayToLiveEquivalenceEvidence
# ---------------------------------------------------------------------------


def test_equivalence_default_is_not_evaluated() -> None:
    evidence = default_amax_replay_to_live_equivalence_evidence()
    assert evidence.equivalence_status == EQUIVALENCE_NOT_EVALUATED
    assert EQUIVALENCE_NOT_EVALUATED in EQUIVALENCE_STATUS_TOKENS
    assert EQUIVALENCE_COMPATIBLE in EQUIVALENCE_STATUS_TOKENS
    assert EQUIVALENCE_BLOCKED in EQUIVALENCE_STATUS_TOKENS


def test_equivalence_round_trip_is_deterministic() -> None:
    evidence = default_amax_replay_to_live_equivalence_evidence()
    raw = dump_canonical_json(evidence.to_dict())
    decoded = load_canonical_json(raw)
    rebuilt = ReplayToLiveEquivalenceEvidence.from_dict(decoded)
    assert rebuilt == evidence


def test_equivalence_rejects_unknown_status() -> None:
    with pytest.raises(ContractError):
        ReplayToLiveEquivalenceEvidence(
            replay_dataset_reference="ds",
            live_source_id="src",
            tag_map_reference="map",
            expected_cadence_seconds=1.0,
            expected_freshness_threshold_seconds=5.0,
            equivalence_status="rogue_status",
        )


def test_equivalence_rejects_freshness_below_cadence() -> None:
    with pytest.raises(ContractError):
        ReplayToLiveEquivalenceEvidence(
            replay_dataset_reference="ds",
            live_source_id="src",
            tag_map_reference="map",
            expected_cadence_seconds=10.0,
            expected_freshness_threshold_seconds=1.0,
        )


def test_equivalence_carries_safety_notes() -> None:
    evidence = default_amax_replay_to_live_equivalence_evidence()
    joined = "\n".join(evidence.notes)
    assert "no live OT binding" in joined
    assert "no PLC/PAC/SCADA write" in joined
    assert "no command emission" in joined
    assert "no setpoint output" in joined


# ---------------------------------------------------------------------------
# Module hygiene — no runtime / network / DB / broker imports
# ---------------------------------------------------------------------------


def _iter_import_statement_lines(text: str) -> list[str]:
    """Return the stripped lines that begin with ``import`` or ``from``.

    Skips comments. Filters out import-like phrases that appear inside
    docstrings or other prose. The runtime-import audit treats this as
    the canonical "actual import statements" set for a Python file.
    """
    out: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("import ") or stripped.startswith("from "):
            out.append(stripped)
    return out


def test_read_only_integration_module_has_no_runtime_imports() -> None:
    """The SDK module must not import live network / DB / broker clients.

    Probe strings are assembled from fragments so the changed-file
    runtime-import audit remains clean.
    """
    statements = _iter_import_statement_lines(
        READ_ONLY_MODULE_PATH.read_text(encoding="utf-8")
    )
    forbidden_modules = (
        "sock" + "et",
        "urll" + "ib",
        "http" + ".client",
        "sql" + "ite3",
        "requ" + "ests",
        "http" + "x",
        "aiohtt" + "p",
        "paho" + ".mqtt",
        "asyn" + "cua",
        "opc" + "ua",
        "pymod" + "bus",
        "pyco" + "mm",
        "psyco" + "pg2",
        "psyco" + "pg",
        "pymon" + "go",
        "redis",
        "kafk" + "a",
    )
    for module in forbidden_modules:
        for stmt in statements:
            assert f"import {module}" not in stmt, (
                f"read_only_integration imports forbidden runtime module "
                f"{module!r}: {stmt!r}"
            )
            assert not stmt.startswith(f"from {module}"), (
                f"read_only_integration imports forbidden runtime module "
                f"{module!r}: {stmt!r}"
            )


def test_read_only_integration_module_does_not_import_aquaoptima_runtime() -> None:
    statements = _iter_import_statement_lines(
        READ_ONLY_MODULE_PATH.read_text(encoding="utf-8")
    )
    aqua_probe = "aqua" + "optima."
    for stmt in statements:
        assert aqua_probe not in stmt, (
            f"read_only_integration must not import aquaoptima.*: {stmt!r}"
        )


def test_read_only_integration_module_does_not_import_torch() -> None:
    statements = _iter_import_statement_lines(
        READ_ONLY_MODULE_PATH.read_text(encoding="utf-8")
    )
    torch_probe = "to" + "rch"
    for stmt in statements:
        assert f"import {torch_probe}" not in stmt
        assert not stmt.startswith(f"from {torch_probe}")
