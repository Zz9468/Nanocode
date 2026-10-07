from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from Main.NanocodeFrontline.Src.Application.Dto.AppProjection import (
    CURRENT_IMPLEMENTATION_ROOT,
    ENTRY_SURFACES,
    LOGICAL_PRODUCT_APP,
)


@dataclass(frozen=True, slots=True)
class RuntimeEntryProjection:
    name: str
    currentPoint: str
    observableResult: str
    appRole: str
    evidencePath: str
    evidenceExists: bool


_ENTRY_EVIDENCE_PATHS = {
    "interactive-cli": "nanocode/main.py",
    "headless-runner": "nanocode/headless.py",
    "readiness-checker": "nanocode/readiness.py",
    "local-command-surface": "nanocode/cli_commands.py",
    "product-snapshot": "nanocode/product_surfaces.py",
    "release-readiness": "nanocode/release_readiness.py",
}


def build_current_runtime_projection(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    entries = []
    for surface in ENTRY_SURFACES:
        evidence_path = _ENTRY_EVIDENCE_PATHS[surface.name]
        entries.append(
            RuntimeEntryProjection(
                name=surface.name,
                currentPoint=surface.currentPoint,
                observableResult=surface.observableResult,
                appRole=surface.appRole,
                evidencePath=evidence_path,
                evidenceExists=(root_path / evidence_path).is_file(),
            )
        )

    return {
        "logicalProductApp": LOGICAL_PRODUCT_APP,
        "currentImplementationRoot": CURRENT_IMPLEMENTATION_ROOT,
        "entryCount": len(entries),
        "missingEvidence": [
            entry.evidencePath for entry in entries if not entry.evidenceExists
        ],
        "entries": [asdict(entry) for entry in entries],
    }
