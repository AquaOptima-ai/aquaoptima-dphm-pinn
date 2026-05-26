"""Sprint 52 AMAX vendor PAC inventory contract tests."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from aquaoptima_contracts import (
    AMAX5000IOCapability,
    AMAXPlatformCapability,
    AMAXProductOffering,
    AMAXVendorEvidenceSource,
    AMAXVendorPACInventory,
    AquaOptimaIntegrationBoundary,
    default_amax_vendor_pac_inventory,
    diagnose_amax_vendor_pac_inventory,
)
from aquaoptima_contracts.edge.vendor_pac_inventory import (
    AMAX_VENDOR_PAC_INVENTORY_ID,
    IO_FAMILY_ANALOG_IO,
    IO_FAMILY_COUNTER_ENCODER,
    IO_FAMILY_DIGITAL_IO,
    IO_FAMILY_POWER_COUPLER,
    IO_FAMILY_RELAY,
    IO_FAMILY_TIMESTAMP_IO,
    OWNER_AMAX_CODESYS_PAC,
    OWNER_AQUAOPTIMA_SIDECAR,
    OWNER_OPERATOR_HMI,
    OWNER_SITE_PLC,
    PRODUCT_CATEGORY_CODESYS_READY_PAC,
    PRODUCT_CATEGORY_CONTROL_IPC_BAREBONE,
    VENDOR_CONFIRMATION_NOT_PROVEN_BY_DRIVER_PACKAGE,
)

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "src/aquaoptima_contracts/edge/vendor_pac_inventory.py"
DOC_PATH = ROOT / "docs/hardware/amax-5580-vendor-pac-software-inventory.md"
ROADMAP_PATH = ROOT / "docs/sprint-roadmap.md"
README_PATH = ROOT / "README.md"


def test_dataclass_round_trips_are_deterministic() -> None:
    inventory = default_amax_vendor_pac_inventory()
    round_trip = AMAXVendorPACInventory.from_dict(inventory.to_dict())
    assert round_trip == inventory
    assert AMAXVendorEvidenceSource.from_dict(inventory.sources[0].to_dict()) == inventory.sources[0]
    assert AMAXProductOffering.from_dict(inventory.product_offerings[0].to_dict()) == inventory.product_offerings[0]
    assert AMAXPlatformCapability.from_dict(inventory.platform_capabilities[0].to_dict()) == inventory.platform_capabilities[0]
    assert AMAX5000IOCapability.from_dict(inventory.io_capabilities[0].to_dict()) == inventory.io_capabilities[0]
    assert AquaOptimaIntegrationBoundary.from_dict(inventory.integration_boundaries[0].to_dict()) == inventory.integration_boundaries[0]


def test_default_inventory_sources_include_manuals_and_linux_driver() -> None:
    inventory = default_amax_vendor_pac_inventory()
    assert inventory.inventory_id == AMAX_VENDOR_PAC_INVENTORY_ID
    source_ids = {source.document_id for source in inventory.sources}
    assert "amax_5580_user_manual_ed2" in source_ids
    assert "amax_5000_io_manual_ed5" in source_ids
    assert "amax_5580_linux_driver_v2_24_1" in source_ids


def test_default_inventory_includes_barebone_and_codesys_ready_pac() -> None:
    inventory = default_amax_vendor_pac_inventory()
    categories = {offering.category for offering in inventory.product_offerings}
    assert PRODUCT_CATEGORY_CONTROL_IPC_BAREBONE in categories
    assert PRODUCT_CATEGORY_CODESYS_READY_PAC in categories

    ready_pac = next(
        offering
        for offering in inventory.product_offerings
        if offering.category == PRODUCT_CATEGORY_CODESYS_READY_PAC
    )
    assert "AMAX-658-67CW00A" in ready_pac.part_numbers
    assert "Windows 10 LTSC" in ready_pac.os
    assert "128 GB M.2" in ready_pac.cpu_ram_storage
    assert "2 MB NVRAM" in ready_pac.nvram_mram
    assert "CODESYS V3 Pure Control with Visu" in ready_pac.software_bundle


def test_linux_driver_capabilities_and_caveat_are_explicit() -> None:
    inventory = default_amax_vendor_pac_inventory()
    domains = {capability.domain for capability in inventory.platform_capabilities}
    for domain in {"watchdog", "hwmon", "led", "gpio", "eeprom"}:
        assert domain in domains

    caveats = [
        capability
        for capability in inventory.platform_capabilities
        if capability.vendor_confirmation_status
        == VENDOR_CONFIRMATION_NOT_PROVEN_BY_DRIVER_PACKAGE
    ]
    assert caveats
    caveat_text = "\n".join(
        "\n".join(capability.notes + (capability.safety_posture,))
        for capability in caveats
    )
    assert "Linux driver package does not prove CODESYS Linux availability" in caveat_text


def test_amax_5000_io_capability_map_covers_required_families() -> None:
    inventory = default_amax_vendor_pac_inventory()
    families = {capability.module_family for capability in inventory.io_capabilities}
    assert {
        IO_FAMILY_POWER_COUPLER,
        IO_FAMILY_ANALOG_IO,
        IO_FAMILY_DIGITAL_IO,
        IO_FAMILY_RELAY,
        IO_FAMILY_COUNTER_ENCODER,
        IO_FAMILY_TIMESTAMP_IO,
    }.issubset(families)


def test_integration_boundary_assigns_pac_authority_away_from_aquaoptima() -> None:
    inventory = default_amax_vendor_pac_inventory()
    owner_by_area = {
        boundary.capability_area: boundary.owner
        for boundary in inventory.integration_boundaries
    }
    assert owner_by_area["hard_real_time_control"] == OWNER_AMAX_CODESYS_PAC
    assert owner_by_area["ethercat_field_io"] == OWNER_AMAX_CODESYS_PAC
    assert owner_by_area["hmi_visu"] == OWNER_OPERATOR_HMI
    assert owner_by_area["interlocks_permissives"] == OWNER_SITE_PLC
    assert owner_by_area["actuator_authority"] == OWNER_SITE_PLC
    assert owner_by_area["model_inference"] == OWNER_AQUAOPTIMA_SIDECAR
    assert owner_by_area["validation"] == OWNER_AQUAOPTIMA_SIDECAR
    assert owner_by_area["dry_run_proposals"] == OWNER_AQUAOPTIMA_SIDECAR
    assert owner_by_area["advisory_evidence_records"] == OWNER_AQUAOPTIMA_SIDECAR
    assert owner_by_area["read_only_health_status"] == OWNER_AQUAOPTIMA_SIDECAR


def test_default_inventory_diagnostics_are_clean() -> None:
    inventory = default_amax_vendor_pac_inventory()
    diagnostics = diagnose_amax_vendor_pac_inventory(inventory)
    assert diagnostics.is_clean
    assert diagnostics.to_dict() == {"warnings": [], "errors": []}


def test_diagnostics_catch_missing_codesys_ready_pac() -> None:
    inventory = default_amax_vendor_pac_inventory()
    broken = AMAXVendorPACInventory(
        inventory_id=inventory.inventory_id,
        sources=inventory.sources,
        product_offerings=tuple(
            offering
            for offering in inventory.product_offerings
            if offering.category != PRODUCT_CATEGORY_CODESYS_READY_PAC
        ),
        platform_capabilities=inventory.platform_capabilities,
        io_capabilities=inventory.io_capabilities,
        integration_boundaries=inventory.integration_boundaries,
        safety_notes=inventory.safety_notes,
    )
    diagnostics = diagnose_amax_vendor_pac_inventory(broken)
    assert any("CODESYS Ready PAC" in error for error in diagnostics.errors)


def test_diagnostics_catch_missing_linux_driver_caveat_and_timestamp_io() -> None:
    inventory = default_amax_vendor_pac_inventory()
    broken = AMAXVendorPACInventory(
        inventory_id=inventory.inventory_id,
        sources=inventory.sources,
        product_offerings=inventory.product_offerings,
        platform_capabilities=tuple(
            capability
            for capability in inventory.platform_capabilities
            if capability.vendor_confirmation_status
            != VENDOR_CONFIRMATION_NOT_PROVEN_BY_DRIVER_PACKAGE
        ),
        io_capabilities=tuple(
            capability
            for capability in inventory.io_capabilities
            if capability.module_family != IO_FAMILY_TIMESTAMP_IO
        ),
        integration_boundaries=inventory.integration_boundaries,
        safety_notes=inventory.safety_notes,
    )
    diagnostics = diagnose_amax_vendor_pac_inventory(broken)
    assert any("Linux driver caveat" in error for error in diagnostics.errors)
    assert any(IO_FAMILY_TIMESTAMP_IO in error for error in diagnostics.errors)


def test_diagnostics_catch_unsafe_aquaoptima_pac_ownership() -> None:
    inventory = default_amax_vendor_pac_inventory()
    unsafe = AquaOptimaIntegrationBoundary(
        responsibility_id="unsafe_owner",
        capability_area="hard_real_time_control",
        owner=OWNER_AQUAOPTIMA_SIDECAR,
        aquaoptima_mode="advisory",
        allowed_actions=("review evidence only",),
        forbidden_actions=("no live OT binding",),
    )
    broken = AMAXVendorPACInventory(
        inventory_id=inventory.inventory_id,
        sources=inventory.sources,
        product_offerings=inventory.product_offerings,
        platform_capabilities=inventory.platform_capabilities,
        io_capabilities=inventory.io_capabilities,
        integration_boundaries=inventory.integration_boundaries + (unsafe,),
        safety_notes=inventory.safety_notes,
    )
    diagnostics = diagnose_amax_vendor_pac_inventory(broken)
    assert any("PAC/control" in error for error in diagnostics.errors)


def test_constructor_rejects_unsafe_sidecar_allowed_actions() -> None:
    with pytest.raises(Exception):
        AquaOptimaIntegrationBoundary(
            responsibility_id="unsafe_action",
            capability_area="model_inference",
            owner=OWNER_AQUAOPTIMA_SIDECAR,
            aquaoptima_mode="advisory",
            allowed_actions=("direct actuator",),
        )


def test_docs_and_source_preserve_required_safety_boundary() -> None:
    corpus = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (MODULE_PATH, DOC_PATH, ROADMAP_PATH, README_PATH)
        if path.exists()
    )
    assert "no live OT binding" in corpus
    assert "no PLC/PAC/SCADA write" in corpus
    assert "no command emission" in corpus
    assert "no setpoint output" in corpus
    assert "CODESYS V3 Pure Control with Visu" in corpus
    assert "Windows 10 LTSC" in corpus
    assert "Linux driver package does not prove CODESYS Linux availability" in corpus


def test_module_does_not_import_runtime_network_dependencies() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    statements = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            statements.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            statements.append(node.module)
    forbidden_modules = (
        "sock" + "et",
        "urll" + "ib",
        "requ" + "ests",
        "htt" + "px",
        "fast" + "api",
        "fl" + "ask",
        "djan" + "go",
        "sqlal" + "chemy",
        "re" + "dis",
        "pi" + "ka",
        "kaf" + "ka",
    )
    for module in forbidden_modules:
        assert module not in statements
