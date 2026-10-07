from __future__ import annotations

from pathlib import Path

from Main.NanocodeFrontline.Src.Application.Query.CurrentRuntimeProjection import (
    build_current_runtime_projection,
)


def test_current_runtime_projection_reports_all_entry_evidence() -> None:
    projection = build_current_runtime_projection(Path.cwd())

    assert projection["logicalProductApp"] == "product/app/nanocode_frontline"
    assert projection["currentImplementationRoot"] == "nanocode"
    assert projection["entryCount"] == 6
    assert projection["missingEvidence"] == []
    assert {
        entry["evidencePath"] for entry in projection["entries"]
    } == {
        "nanocode/main.py",
        "nanocode/headless.py",
        "nanocode/readiness.py",
        "nanocode/cli_commands.py",
        "nanocode/product_surfaces.py",
        "nanocode/release_readiness.py",
    }
