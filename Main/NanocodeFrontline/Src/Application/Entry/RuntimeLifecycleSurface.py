from __future__ import annotations

from dataclasses import dataclass

from Main.NanocodeFrontline.Src.Application.Dto.AppProjection import (
    LOGICAL_PRODUCT_APP,
)


@dataclass(frozen=True, slots=True)
class RuntimeLifecycleEntry:
    name: str
    scriptName: str
    moduleTarget: str
    commandSurface: str
    lifecycleRole: str


RUNTIME_LIFECYCLE_ENTRIES = (
    RuntimeLifecycleEntry(
        name="interactive-cli",
        scriptName="nanocode",
        moduleTarget="nanocode.main:main",
        commandSurface="python -m nanocode.main",
        lifecycleRole="interactive product app lifecycle",
    ),
    RuntimeLifecycleEntry(
        name="headless-runner",
        scriptName="nanocode-headless",
        moduleTarget="nanocode.headless:main",
        commandSurface="python -m nanocode.headless",
        lifecycleRole="non-interactive automation lifecycle",
    ),
    RuntimeLifecycleEntry(
        name="readiness-checker",
        scriptName="nanocode-readiness",
        moduleTarget="nanocode.readiness:main",
        commandSurface="python -m nanocode.readiness",
        lifecycleRole="provider readiness diagnostic lifecycle",
    ),
)

ALIAS_SCRIPT_TARGETS = {
    "nanocode-py": "nanocode.main:main",
}


def lifecycle_script_targets() -> dict[str, str]:
    primary_targets = {
        entry.scriptName: entry.moduleTarget
        for entry in RUNTIME_LIFECYCLE_ENTRIES
    }
    return {**primary_targets, **ALIAS_SCRIPT_TARGETS}


def lifecycle_contract_payload() -> dict[str, object]:
    return {
        "logicalProductApp": LOGICAL_PRODUCT_APP,
        "entryCount": len(RUNTIME_LIFECYCLE_ENTRIES),
        "scripts": lifecycle_script_targets(),
    }
