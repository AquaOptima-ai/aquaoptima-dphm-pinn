"""TDD slice F — Phase 1 fixture compatibility.

Acceptance: the Phase 1 fixture set decodes through the Sprint 41
types and re-encodes byte-for-byte where applicable. The SDK copies
remain byte-identical to the originals; the manifest snapshot
deterministically round-trips through the SDK canonical writer.

The Phase 1 import path is untouched — this test imports
``load_telemetry_tag_map_json`` from the existing
``aquaoptima.dphm`` surface to assert continued compatibility.
"""

from __future__ import annotations

from pathlib import Path

from aquaoptima_contracts import (
    ALLOWED_CAPABILITY_TOKENS,
    CANONICAL_SAFETY_FLAG_TOKENS,
    CapabilityDeclaration,
    ContractEnvelope,
    SDK_VERSION,
    SafetyFlagSet,
    dump_canonical_json,
    load_canonical_json,
)
from aquaoptima_contracts.testing.golden_files import (
    assert_byte_equal,
    assert_golden_roundtrip,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_PHASE1_DIR = REPO_ROOT / "tests" / "fixtures" / "shadow_phase1"
SDK_PHASE1_DIR = (
    REPO_ROOT
    / "src"
    / "aquaoptima_contracts"
    / "fixtures"
    / "phase1_shadow"
)


def test_sdk_tag_map_byte_equal_to_phase1_original() -> None:
    assert_byte_equal(
        SDK_PHASE1_DIR / "tag_map.json",
        ORIGINAL_PHASE1_DIR / "tag_map.json",
    )


def test_sdk_telemetry_csv_byte_equal_to_phase1_original() -> None:
    assert_byte_equal(
        SDK_PHASE1_DIR / "telemetry.csv",
        ORIGINAL_PHASE1_DIR / "telemetry.csv",
    )


def test_phase1_tag_map_loads_through_existing_phase1_api() -> None:
    # The SDK never imports aquaoptima.* internally. This test is a
    # one-way compatibility check from the test side: the Phase 1
    # fixture continues to load through the Sprint 34 public API.
    from aquaoptima.dphm import load_network_from_inp, load_telemetry_tag_map_json

    inp_fixture = REPO_ROOT / "docs" / "examples" / "epanet_reference_loop.inp"
    network = load_network_from_inp(inp_fixture, parser="fallback")
    tag_map = load_telemetry_tag_map_json(
        ORIGINAL_PHASE1_DIR / "tag_map.json", network
    )
    assert {tag.tag for tag in tag_map.tags} == {
        "PT_J1",
        "PT_J2",
        "FT_P1",
        "FT_P2",
    }


def test_manifest_snapshot_round_trips_through_sdk_writer() -> None:
    snapshot_path = SDK_PHASE1_DIR / "manifest_snapshot.json"
    raw_text = snapshot_path.read_text(encoding="utf-8")
    document = load_canonical_json(raw_text)

    # The snapshot is a packaging / audit-evidence bundle. Verify that
    # the envelope, safety_flag_set, and capability_declaration
    # subsets decode through the Sprint 41 SDK types.
    envelope = ContractEnvelope.from_dict(document["envelope"])
    assert envelope.schema_family == "manifest"
    assert envelope.schema_name == "Phase1ShadowDeploymentManifestSnapshot"
    assert envelope.sdk_version == SDK_VERSION

    flags = SafetyFlagSet.from_dict(document["safety_flag_set"])
    for name in CANONICAL_SAFETY_FLAG_TOKENS:
        assert getattr(flags, name) is True

    decl = CapabilityDeclaration.from_dict(document["capability_declaration"])
    assert decl.component == "edge_runtime"
    assert decl.declared == ALLOWED_CAPABILITY_TOKENS

    # Whole-document canonical equality.
    rendered = dump_canonical_json(document) + "\n"
    assert rendered == raw_text


def test_manifest_snapshot_round_trip_via_golden_helper() -> None:
    assert_golden_roundtrip(
        SDK_PHASE1_DIR / "manifest_snapshot.json",
        decoder=lambda doc: doc,
        encoder=lambda doc: doc,
    )
