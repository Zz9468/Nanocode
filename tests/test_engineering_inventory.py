from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INVENTORY_PATH = (
    ROOT / "Package" / "EngineeringStructure" / "Config" / "material-inventory.json"
)


def _load_inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def _load_repo_json(path_text: str) -> dict:
    return json.loads((ROOT / path_text).read_text(encoding="utf-8"))


def _assert_repo_path_exists(path_text: str) -> None:
    path = ROOT / path_text
    assert path.exists(), f"expected repo path to exist: {path_text}"


def _assert_repo_or_optional_material_path(path_text: str) -> None:
    path = ROOT / path_text
    if path.exists():
        return
    optional_roots = {
        material["path"].rstrip("/")
        for material in _load_inventory()["materials"]
        if material.get("presencePolicy") == "optional-workspace-material"
    }
    assert any(
        path_text == root or path_text.startswith(f"{root}/")
        for root in optional_roots
    ), f"expected repo or optional material path: {path_text}"


def test_material_inventory_tracks_current_product_app_entries() -> None:
    inventory = _load_inventory()

    assert inventory["schemaVersion"] == 2

    app = inventory["currentProductApp"]
    assert app["logicalBoundary"] == "product/app/nanocode_frontline"
    assert app["currentSourceRoot"] == "nanocode"
    assert app["status"] == "active"

    entries = {entry["name"]: entry for entry in app["entrySurfaces"]}
    assert entries["interactive-cli"]["path"] == "nanocode/main.py"
    assert entries["headless-runner"]["path"] == "nanocode/headless.py"
    assert entries["local-command-surface"]["path"] == "nanocode/cli_commands.py"
    assert entries["product-surfaces"]["path"] == "nanocode/product_surfaces.py"
    assert entries["readiness-gate"]["path"] == "nanocode/readiness.py"
    assert entries["readiness-gate"]["script"] == "nanocode-readiness"
    assert entries["release-readiness"]["path"] == "nanocode/release_readiness.py"

    for entry in app["entrySurfaces"]:
        _assert_repo_path_exists(entry["path"])

    for evidence in app["coverageEvidence"]:
        assert evidence["reason"]
        _assert_repo_path_exists(evidence["path"])


def test_material_inventory_covers_known_material_roots() -> None:
    inventory = _load_inventory()

    materials = {item["path"]: item for item in inventory["materials"]}
    assert {
        "ts-src/py-src",
        "ts-src",
        "Nanocode-fork",
        "Nanocode-main-work",
        "claude-code-src",
        "superpowers-zh",
        ".dead-modules-backup",
        "experiments",
        "outputs",
    }.issubset(materials)

    assert "py-src" in materials["ts-src/py-src"]["historicalAliases"]
    assert "paper_experiments" in materials["experiments"]["historicalAliases"]
    assert materials["ts-src"]["burndownManifest"] == (
        "Package/EngineeringStructure/Config/material-burndown/ts-src.json"
    )
    assert materials["Nanocode-fork"]["burndownManifest"] == (
        "Package/EngineeringStructure/Config/material-burndown/nanocode-fork.json"
    )
    assert materials["Nanocode-main-work"]["burndownManifest"] == (
        "Package/EngineeringStructure/Config/material-burndown/nanocode-main-work.json"
    )


def test_material_inventory_materials_are_observed_and_evidenced() -> None:
    inventory = _load_inventory()

    for material in inventory["materials"]:
        assert material["identity"]
        assert material["status"]
        assert material["callerSummary"]
        assert material["replacementTarget"]
        assert material["retirementCondition"]
        optional_workspace_material = (
            material.get("presencePolicy") == "optional-workspace-material"
        )
        if not optional_workspace_material:
            _assert_repo_path_exists(material["path"])

        assert material["observedEntries"], f"{material['path']} is missing observedEntries"
        for entry in material["observedEntries"]:
            assert entry["name"]
            assert entry["result"]
            if not optional_workspace_material:
                _assert_repo_path_exists(entry["path"])

        assert material["coverageEvidence"], f"{material['path']} is missing coverageEvidence"
        for evidence in material["coverageEvidence"]:
            assert evidence["reason"]
            _assert_repo_path_exists(evidence["path"])

        for caller in material["currentCallers"]:
            assert caller["reason"]
            _assert_repo_path_exists(caller["path"])

        for reference in material.get("historicalReferences", []):
            assert reference["reason"]
            _assert_repo_path_exists(reference["path"])

        if "burndownManifest" in material:
            _assert_repo_path_exists(material["burndownManifest"])


def test_archive_approved_materials_have_no_current_callers() -> None:
    inventory = _load_inventory()
    materials = {item["path"]: item for item in inventory["materials"]}

    for path in ("ts-src", "Nanocode-fork", "Nanocode-main-work"):
        material = materials[path]
        assert material["status"].startswith("archive-approved-")
        assert material["currentCallers"] == []

    for path in ("ts-src", "Nanocode-fork"):
        assert materials[path]["historicalReferences"] == []
        references = materials[path]["archivedDocumentationReferences"]
        assert any(
            reference["collection"] == "historicalReferences"
            and reference["path"] == "Docs/Documentation/CODE_WIKI.md"
            and reference["reason"]
            for reference in references
        )


def test_material_inventory_focused_gates_remain_portable() -> None:
    inventory = _load_inventory()

    gates = {gate["name"]: gate for gate in inventory["focusedGates"]}
    assert "compileall" in gates
    assert "product-entry-gates" in gates
    assert "structure-compliance" in gates
    assert "structure-compliance-artifact" in gates
    assert "readiness-gate" in gates
    assert "readiness-fallback-examples" in gates
    assert "readiness-doctor" in gates
    assert "readiness-repair-plan" in gates
    assert "readiness-patch-preview" in gates
    assert "readiness-bundle" in gates
    assert "readiness-artifact-manifest" in gates
    assert "readiness-patch-preview-gate" in gates
    assert "readiness-fallback-simulation-gate" in gates
    assert "fallback-switch-smoke" in gates
    assert "readiness-bundle-gate" in gates

    assert gates["readiness-fallback-simulation-gate"]["command"] == (
        "python -m nanocode.release_readiness --check-fallback-simulation "
        ".temp/readiness-bundle/readiness-fallback-simulations.json"
    )
    assert "release-fallback-evidence-gate" in gates
    assert "release-report-gate" in gates
    assert "release-markdown-report-gate" in gates
    assert "paper-a-retrieval-probe-gate" in gates
    assert "benchmarks" in gates["compileall"]["command"]
    assert "Main" in gates["compileall"]["command"]
    assert "Package" in gates["compileall"]["command"]
    assert (
        gates["paper-a-retrieval-probe-gate"]["command"]
        == "python -m pytest -q tests/test_paper_a_retrieval_probe_eval.py"
    )
    assert "AppProjection.Test.py" in gates["product-entry-gates"]["command"]
    assert "NanocodeFrontline.Test.py" in gates["product-entry-gates"]["command"]
    assert "LocalCommandSurface.Test.py" in gates["product-entry-gates"]["command"]
    assert "RuntimeLifecycleSurface.Test.py" in gates["product-entry-gates"]["command"]
    assert "CurrentRuntimeProjection.Test.py" in gates["product-entry-gates"]["command"]
    assert "RuntimeCapabilityInventory.Test.py" in gates["product-entry-gates"]["command"]
    assert "ProductRootProjection.Test.py" in gates["product-entry-gates"]["command"]
    assert "StructureCompliance.Test.py" in gates["product-entry-gates"]["command"]
    assert "--import-mode=importlib" in gates["product-entry-gates"]["command"]
    assert "tests/test_engineering_structure.py" in gates["product-entry-gates"]["command"]
    assert (
        gates["structure-compliance"]["command"]
        == "python -m nanocode.structure_check --root . --hotspots 5 --max-dependency-upstream 4 --check-material-inventory --report .temp/structure-compliance.json"
    )
    assert (
        gates["structure-compliance-artifact"]["command"]
        == "python -m nanocode.release_readiness --check-structure-compliance-artifact .temp/structure-compliance.json"
    )
    assert (
        gates["readiness-gate"]["command"]
        == "python -m nanocode.readiness --json --fail-on blocked"
    )
    assert (
        gates["readiness-fallback-examples"]["command"]
        == "python -m nanocode.readiness --examples-out .temp/readiness-fallback-examples.json --fail-on blocked"
    )
    assert (
        gates["readiness-doctor"]["command"]
        == "python -m nanocode.readiness --doctor-out .temp/readiness-doctor.md --fail-on blocked"
    )
    assert (
        gates["readiness-repair-plan"]["command"]
        == "python -m nanocode.readiness --repair-plan-out .temp/readiness-repair-plan.json --fail-on blocked"
    )
    assert (
        gates["readiness-patch-preview"]["command"]
        == "python -m nanocode.readiness --patch-preview-out .temp/readiness-fallback-patch-preview.json --fail-on blocked"
    )
    assert (
        gates["readiness-bundle"]["command"]
        == "python -m nanocode.readiness --bundle-out .temp/readiness-bundle --fail-on blocked"
    )
    assert (
        gates["readiness-artifact-manifest"]["command"]
        == "python -m nanocode.release_readiness --check-artifact-manifest .temp/readiness-artifact-manifest.json"
    )
    assert (
        gates["readiness-patch-preview-gate"]["command"]
        == "python -m nanocode.release_readiness --check-fallback-patch-preview .temp/readiness-fallback-patch-preview.json"
    )
    assert (
        gates["fallback-switch-smoke"]["command"]
        == "python -m nanocode.release_readiness --check-fallback-switch-smoke"
    )
    assert (
        gates["readiness-bundle-gate"]["command"]
        == "python -m nanocode.release_readiness --check-readiness-bundle .temp/readiness-bundle"
    )
    assert (
        gates["release-fallback-evidence-gate"]["command"]
        == "python -m nanocode.release_readiness --check-fallback-evidence benchmarks/release_readiness_results.json"
    )
    assert (
        gates["release-report-gate"]["command"]
        == "python -m nanocode.release_readiness --check-release-report benchmarks/release_readiness_results.json"
    )
    assert (
        gates["release-markdown-report-gate"]["command"]
        == "python -m nanocode.release_readiness --check-release-markdown benchmarks/release_readiness_results.md --release-json benchmarks/release_readiness_results.json"
    )

    for gate in gates.values():
        assert gate["command"].startswith("python -m ")
        assert gate["portableFallback"].startswith("python3 -m ")


def test_material_inventory_release_gates_are_documented_in_readmes() -> None:
    inventory = _load_inventory()
    gates = {gate["name"]: gate for gate in inventory["focusedGates"]}
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    for gate_name in (
        "release-fallback-evidence-gate",
        "release-report-gate",
        "release-markdown-report-gate",
    ):
        command = gates[gate_name]["command"]
        assert command in readme
        assert command in readme_zh


def test_ts_src_py_src_burndown_manifest_tracks_legacy_only_modules() -> None:
    manifest = _load_repo_json("Package/EngineeringStructure/Config/material-burndown/ts-src-py-src.json")

    assert manifest["materialRoot"] == "ts-src/py-src"
    assert manifest["summary"]["legacyOnlyRelativePathCount"] == 11
    assert manifest["summary"]["sharedLegacyTestFileCount"] == 16

    entries = {entry["legacyRelativePath"]: entry for entry in manifest["entries"]}
    assert len(entries) == 11

    assert entries["async_context.py"]["status"] == "legacy-only-no-current-caller"
    assert manifest["summary"]["currentNameResidueCount"] == 0
    assert manifest["summary"]["retiredLegacyOnlyModuleCount"] == 11
    assert manifest["dispositionPolicy"].startswith("Legacy-only modules are retired")
    assert entries["tools/multi_edit.py"]["status"] == "legacy-only-no-current-caller"
    assert entries["tools/run_with_debug.py"]["status"] == "legacy-only-no-current-caller"
    assert not entries["tools/multi_edit.py"]["currentReferences"]
    assert not entries["tools/run_with_debug.py"]["currentReferences"]
    assert entries["tools/multi_edit.py"]["disposition"] == "retired"
    assert entries["tools/multi_edit.py"]["replacementEvidence"][0]["path"] == (
        "nanocode/tools/patch_file.py"
    )
    assert entries["sub_agents.py"]["replacementEvidence"][0]["path"] == (
        "nanocode/tools/task.py"
    )

    for entry in manifest["entries"]:
        _assert_repo_path_exists(entry["legacyPath"])
        assert entry["disposition"] == "retired"
        for current in entry["currentReferences"]:
            assert current["reason"]
            _assert_repo_path_exists(current["path"])
        for evidence in entry["replacementEvidence"]:
            assert evidence["reason"]
            _assert_repo_path_exists(evidence["path"])


def test_legacy_only_tool_names_are_not_live_current_code_heuristics() -> None:
    stale_tool_names = {
        "api_tester",
        "db_explorer",
        "docker_helper",
        "multi_edit",
        "run_with_debug",
    }
    current_sources = [
        ROOT / "nanocode" / "tooling.py",
        ROOT / "nanocode" / "context_manager.py",
    ]

    for source_path in current_sources:
        source = source_path.read_text(encoding="utf-8")
        for tool_name in stale_tool_names:
            assert tool_name not in source, f"stale legacy tool name in {source_path}"


def test_ts_src_burndown_manifest_tracks_reference_boundary() -> None:
    manifest = _load_repo_json("Package/EngineeringStructure/Config/material-burndown/ts-src.json")

    assert manifest["materialRoot"] == "ts-src"
    assert manifest["summary"]["activeProductCallerCount"] == 0
    assert manifest["summary"]["typescriptSourceFileCount"] == 45
    assert manifest["summary"]["delegatedNestedMaterialCount"] == 1
    assert manifest["summary"]["docsReferenceCallerCount"] == 0
    assert manifest["historicalSummary"]["docsReferenceCallerCount"] == 1
    assert manifest["archiveApproval"]["approvedAction"] == (
        "archival deletion allowed after inventory gates pass"
    )
    assert manifest["archiveApproval"]["retainedInPlace"] is True
    assert manifest["dispositionPolicy"].startswith(
        "Archive-approved reference material"
    )
    assert "current product-facing docs no longer link into ts-src" in (
        manifest["dispositionPolicy"]
    )

    entries = {entry["path"]: entry for entry in manifest["entries"]}
    assert entries["ts-src/package.json"]["status"] == (
        "legacy-node-package-no-product-caller"
    )
    assert entries["ts-src/src/index.ts"]["replacementEvidence"][0]["path"] == (
        "nanocode/main.py"
    )
    assert entries["ts-src/py-src"]["disposition"] == "delegated"
    assert entries["ts-src/py-src"]["currentReferences"][0]["path"] == (
        "Package/EngineeringStructure/Config/material-burndown/ts-src-py-src.json"
    )
    archived = {entry["path"]: entry for entry in manifest["archivedEntries"]}
    assert "ts-src/ARCHITECTURE_ZH.md" not in entries
    assert not archived["ts-src/ARCHITECTURE_ZH.md"]["currentReferences"]
    assert "ts-src/docs/index.html" in archived
    for name in ("README.md", "README.zh-CN.md"):
        readme = (ROOT / name).read_text(encoding="utf-8")
        assert "./Package/EngineeringStructure/Config/material-inventory.json" in readme
        assert "./Docs/" not in readme
        assert "./AGENTS.md" not in readme

    for entry in manifest["entries"]:
        _assert_repo_or_optional_material_path(entry["path"])
        assert entry["disposition"] in {"retained-reference", "delegated"}
        for current in entry["currentReferences"]:
            assert current["reason"]
            _assert_repo_or_optional_material_path(current["path"])
        for evidence in entry["replacementEvidence"]:
            assert evidence["reason"]
            _assert_repo_path_exists(evidence["path"])


def test_nanocode_fork_burndown_manifest_tracks_comparison_boundary() -> None:
    manifest = _load_repo_json("Package/EngineeringStructure/Config/material-burndown/nanocode-fork.json")

    assert manifest["materialRoot"] == "Nanocode-fork"
    assert manifest["summary"]["activeProductCallerCount"] == 0
    assert manifest["summary"]["typescriptSourceFileCount"] == 45
    assert manifest["summary"]["externalFileCountExcludingGit"] == 127
    assert manifest["archiveApproval"]["retainedInPlace"] is True
    assert manifest["dispositionPolicy"].startswith("Archive-approved")

    entries = {entry["path"]: entry for entry in manifest["entries"]}
    assert entries["Nanocode-fork/package.json"]["status"] == (
        "comparison-node-package-no-product-caller"
    )
    assert entries["Nanocode-fork/src/index.ts"]["replacementEvidence"][0]["path"] == (
        "nanocode/main.py"
    )
    assert entries["Nanocode-fork/external/Nanocode-Python"]["status"] == (
        "nested-external-reference"
    )

    for entry in manifest["entries"]:
        _assert_repo_or_optional_material_path(entry["path"])
        assert entry["disposition"] == "retained-reference"
        for current in entry["currentReferences"]:
            assert current["reason"]
            _assert_repo_or_optional_material_path(current["path"])
        for evidence in entry["replacementEvidence"]:
            assert evidence["reason"]
            _assert_repo_path_exists(evidence["path"])


def test_nanocode_main_work_burndown_manifest_tracks_parity_source_boundary() -> None:
    manifest = _load_repo_json("Package/EngineeringStructure/Config/material-burndown/nanocode-main-work.json")

    assert manifest["materialRoot"] == "Nanocode-main-work"
    assert manifest["summary"]["activeProductCallerCount"] == 0
    assert manifest["summary"]["activeParityCallerCount"] == 0
    assert manifest["summary"]["migratedParityProvenanceCount"] == 1
    assert manifest["summary"]["testSourceFileCount"] == 21
    assert manifest["summary"]["externalFileCountExcludingGit"] == 1029
    assert manifest["archiveApproval"]["retainedInPlace"] is True
    assert manifest["dispositionPolicy"].startswith("Archive-approved")

    entries = {entry["path"]: entry for entry in manifest["entries"]}
    assert entries["Nanocode-main-work/package.json"]["status"] == (
        "comparison-node-package-no-product-caller"
    )
    parity_entry = entries["Nanocode-main-work/test/input-parser.test.ts"]
    assert parity_entry["status"] == "parity-source-provenance-migrated"
    assert parity_entry["disposition"] == "retained-reference"
    assert not parity_entry["currentReferences"]
    assert {
        evidence["path"] for evidence in parity_entry["replacementEvidence"]
    } == {
        "tests/test_ts_ported.py",
        "Package/EngineeringStructure/Config/ts-parity-provenance.json",
    }

    provenance = _load_repo_json("Package/EngineeringStructure/Config/ts-parity-provenance.json")
    assert provenance["pythonTestPath"] == "tests/test_ts_ported.py"
    assert len(provenance["portedScenarios"]) == 5
    ts_ported = (ROOT / "tests" / "test_ts_ported.py").read_text(encoding="utf-8")
    assert "Nanocode-main-work" not in ts_ported

    for entry in manifest["entries"]:
        _assert_repo_or_optional_material_path(entry["path"])
        assert entry["disposition"] == "retained-reference"
        for current in entry["currentReferences"]:
            assert current["reason"]
            _assert_repo_or_optional_material_path(current["path"])
        for evidence in entry["replacementEvidence"]:
            assert evidence["reason"]
            _assert_repo_path_exists(evidence["path"])


def test_experiments_burndown_manifest_tracks_rebound_benchmark_surface() -> None:
    manifest = _load_repo_json("Package/EngineeringStructure/Config/material-burndown/experiments.json")

    assert manifest["materialRoot"] == "experiments"
    assert manifest["summary"]["experimentFileCount"] == 3
    assert (
        manifest["residualRisk"]
        == "The restored benchmark currently rebuilds report artifacts from committed canonical query rows instead of executing a live retrieval pipeline."
    )

    entries = {entry["path"]: entry for entry in manifest["entries"]}
    command_entry = entries["experiments/2026-06-21-paper-a-retrieval-probe/command.txt"]
    assert command_entry["status"] == "rebound-to-current-benchmark-surface"
    assert {
        current["path"] for current in command_entry["currentReferences"]
    } == {
        "benchmarks/paper_a_retrieval_probe_eval.py",
        "nanocode/paper_a_retrieval_probe_eval.py",
        "tests/test_paper_a_retrieval_probe_eval.py",
    }

    report_entry = entries["experiments/2026-06-21-paper-a-retrieval-probe/report.md"]
    assert report_entry["currentReferences"] == []
    assert report_entry["generatedArtifacts"][0]["path"] == (
        "benchmarks/paper_a_retrieval_probe_eval_results.md"
    )

    from nanocode.paper_a_retrieval_probe_eval import evaluate_retrieval_probe

    rows_path = ROOT / manifest["canonicalRowsPath"]
    assert rows_path.is_file()
    assert evaluate_retrieval_probe() == evaluate_retrieval_probe(rows_path)
    assert len(evaluate_retrieval_probe()) == 36

    for entry in manifest["entries"]:
        _assert_repo_or_optional_material_path(entry["path"])
        for current in entry["currentReferences"]:
            assert current["reason"]
            _assert_repo_or_optional_material_path(current["path"])


def test_published_inventory_keeps_active_bindings_independent_of_archived_docs() -> None:
    """Source and coverage remain required; archived documents are metadata only."""
    active_collections = {
        "entrySurfaces", "coverageEvidence", "currentCallers", "currentReferences",
        "replacementEvidence", "historicalReferences",
    }

    def check_records(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                check_records(item)
        elif isinstance(value, dict):
            for key, child in value.items():
                if key in {"archivedEntries", "archivedDocumentationReferences"}:
                    continue
                if key in active_collections:
                    for record in child:
                        path = record["path"]
                        assert not path.startswith(("Docs/", "openspec/", "ts-src/docs/"))
                        assert Path(path).suffix not in {".md", ".txt"} or Path(path).name.startswith("README")
                        _assert_repo_path_exists(path)
                check_records(child)

    config_root = INVENTORY_PATH.parent
    for config in config_root.rglob("*.json"):
        payload = json.loads(config.read_text(encoding="utf-8"))
        assert payload["publicationPolicy"]["documentation"] == "README files only"
        check_records(payload)
