from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from Main.NanocodeFrontline.Src.Application.Dto.AppProjection import (
    CURRENT_IMPLEMENTATION_ROOT,
    LOGICAL_PRODUCT_APP,
)


@dataclass(frozen=True, slots=True)
class RuntimeCapabilitySlice:
    capability: str
    currentPath: str
    capabilityKind: str
    currentRole: str
    migrationCandidate: str
    priority: int
    evidence: str
    exists: bool


_CAPABILITY_SLICES = (
    RuntimeCapabilitySlice(
        capability="interactive lifecycle entry",
        currentPath="nanocode/main.py",
        capabilityKind="entry",
        currentRole="interactive CLI/TUI startup and session command routing",
        migrationCandidate="Main/NanocodeFrontline/Src/Boot",
        priority=1,
        evidence="console scripts nanocode/nanocode-py and python -m nanocode.main",
        exists=False,
    ),
    RuntimeCapabilitySlice(
        capability="headless lifecycle entry",
        currentPath="nanocode/headless.py",
        capabilityKind="entry",
        currentRole="non-interactive automation startup",
        migrationCandidate="Main/NanocodeFrontline/Src/Boot",
        priority=1,
        evidence="console scripts nanocode-headless/nanocode-headless and python -m nanocode.headless",
        exists=False,
    ),
    RuntimeCapabilitySlice(
        capability="readiness lifecycle entry",
        currentPath="nanocode/readiness.py",
        capabilityKind="entry",
        currentRole="non-interactive provider readiness diagnostics",
        migrationCandidate="Main/NanocodeFrontline/Src/Boot",
        priority=1,
        evidence="console scripts nanocode-readiness/nanocode-readiness and python -m nanocode.readiness",
        exists=False,
    ),
    RuntimeCapabilitySlice(
        capability="local command surface",
        currentPath="nanocode/cli_commands.py",
        capabilityKind="operation-surface",
        currentRole="session, replay, rewind, readiness, and extension commands",
        migrationCandidate="Main/NanocodeFrontline/Src/Application/Entry",
        priority=2,
        evidence="product slash-command tests and current entry contract",
        exists=False,
    ),
    RuntimeCapabilitySlice(
        capability="session state and rewind",
        currentPath="nanocode/session.py",
        capabilityKind="state-session",
        currentRole="durable session metadata, transcript, checkpoints, and rewind data",
        migrationCandidate="Main/NanocodeFrontline/Src/Domain/Model",
        priority=2,
        evidence="session inspection, replay, checkpoint, and rewind tests",
        exists=False,
    ),
    RuntimeCapabilitySlice(
        capability="runtime configuration",
        currentPath="nanocode/config.py",
        capabilityKind="config-provider",
        currentRole="provider configuration, fallback readiness, and profile paths",
        migrationCandidate="Main/NanocodeFrontline/Src/Application/Dto",
        priority=3,
        evidence="readiness and product surface tests",
        exists=False,
    ),
    RuntimeCapabilitySlice(
        capability="product observability snapshot",
        currentPath="nanocode/product_surfaces.py",
        capabilityKind="observability",
        currentRole="instruction, hook, delegation, extension, and readiness surfaces",
        migrationCandidate="Main/NanocodeFrontline/Src/Application/Query",
        priority=2,
        evidence="product surface tests and runtime projection",
        exists=False,
    ),
    RuntimeCapabilitySlice(
        capability="release readiness gate",
        currentPath="nanocode/release_readiness.py",
        capabilityKind="quality-gate",
        currentRole="compile, test, smoke, runtime profile, and provider diagnostics summary",
        migrationCandidate="Main/NanocodeFrontline/Src/Application/Query",
        priority=4,
        evidence="focused inventory and release readiness references",
        exists=False,
    ),
    RuntimeCapabilitySlice(
        capability="tool orchestration registry",
        currentPath="nanocode/tooling.py",
        capabilityKind="tool-orchestration",
        currentRole="tool context, tool registry, and execution wrapper",
        migrationCandidate="Package/ToolingSupport",
        priority=5,
        evidence="default tool registry and integration tests",
        exists=False,
    ),
    RuntimeCapabilitySlice(
        capability="research retrieval probe",
        currentPath="nanocode/paper_a_retrieval_probe_eval.py",
        capabilityKind="research-tool-residue",
        currentRole="research benchmark support code retained beside product app",
        migrationCandidate="Tool/ResearchEvaluation",
        priority=6,
        evidence="paper-a retrieval probe focused gate",
        exists=False,
    ),
)


def build_runtime_capability_inventory(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    slices = [
        RuntimeCapabilitySlice(
            capability=item.capability,
            currentPath=item.currentPath,
            capabilityKind=item.capabilityKind,
            currentRole=item.currentRole,
            migrationCandidate=item.migrationCandidate,
            priority=item.priority,
            evidence=item.evidence,
            exists=(root_path / item.currentPath).is_file(),
        )
        for item in _CAPABILITY_SLICES
    ]
    missing = [item.currentPath for item in slices if not item.exists]
    by_kind: dict[str, int] = {}
    for item in slices:
        by_kind[item.capabilityKind] = by_kind.get(item.capabilityKind, 0) + 1

    return {
        "logicalProductApp": LOGICAL_PRODUCT_APP,
        "currentImplementationRoot": CURRENT_IMPLEMENTATION_ROOT,
        "sliceCount": len(slices),
        "missingEvidence": missing,
        "capabilityKindCounts": dict(sorted(by_kind.items())),
        "nextMigrationCandidates": [
            asdict(item) for item in sorted(slices, key=lambda value: value.priority)[:3]
        ],
        "slices": [asdict(item) for item in slices],
    }
