from __future__ import annotations

from pathlib import Path

from Main.NanocodeFrontline.Src.Application.Query.RuntimeCapabilityInventory import (
    build_runtime_capability_inventory,
)


def test_runtime_capability_inventory_covers_core_current_app_files() -> None:
    inventory = build_runtime_capability_inventory(Path.cwd())

    assert inventory["logicalProductApp"] == "product/app/nanocode_frontline"
    assert inventory["currentImplementationRoot"] == "nanocode"
    assert inventory["missingEvidence"] == []
    assert inventory["sliceCount"] >= 9
    assert {
        item["currentPath"] for item in inventory["slices"]
    } >= {
        "nanocode/main.py",
        "nanocode/headless.py",
        "nanocode/readiness.py",
        "nanocode/cli_commands.py",
        "nanocode/session.py",
        "nanocode/config.py",
        "nanocode/product_surfaces.py",
        "nanocode/release_readiness.py",
    }


def test_runtime_capability_inventory_names_next_migration_candidates() -> None:
    inventory = build_runtime_capability_inventory(Path.cwd())
    candidates = inventory["nextMigrationCandidates"]

    assert [item["currentPath"] for item in candidates] == [
        "nanocode/main.py",
        "nanocode/headless.py",
        "nanocode/readiness.py",
    ]
    assert candidates[0]["migrationCandidate"] == "Main/NanocodeFrontline/Src/Boot"
    assert "entry" in inventory["capabilityKindCounts"]
