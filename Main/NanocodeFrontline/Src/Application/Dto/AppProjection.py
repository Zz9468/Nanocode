from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EntrySurface:
    name: str
    currentPoint: str
    observableResult: str
    appRole: str


LOGICAL_PRODUCT_APP = "product/app/nanocode_frontline"
CURRENT_IMPLEMENTATION_ROOT = "nanocode"


ENTRY_SURFACES = (
    EntrySurface(
        name="interactive-cli",
        currentPoint="nanocode | nanocode-py | python -m nanocode.main",
        observableResult=(
            "terminal coding session with tools, permissions, model runtime, "
            "transcript, session commands, checkpoints, and rewind"
        ),
        appRole="product app lifecycle entry",
    ),
    EntrySurface(
        name="headless-runner",
        currentPoint="nanocode-headless | nanocode-headless | python -m nanocode.headless",
        observableResult="single prompt execution with optional message trace",
        appRole="product app automation entry",
    ),
    EntrySurface(
        name="readiness-checker",
        currentPoint="nanocode-readiness | nanocode-readiness | python -m nanocode.readiness",
        observableResult="provider/runtime readiness report with risk scope and next actions",
        appRole="product app diagnostic entry",
    ),
    EntrySurface(
        name="local-command-surface",
        currentPoint="nanocode/cli_commands.py",
        observableResult=(
            "/session, /session-replay, /sessions, /checkpoints, /rewind, "
            "/readiness, and /extensions"
        ),
        appRole="product app operation surface",
    ),
    EntrySurface(
        name="product-snapshot",
        currentPoint="nanocode/product_surfaces.py",
        observableResult=(
            "instruction, hook, delegation, extension, readiness, and prompt "
            "bundle summaries"
        ),
        appRole="product app observability surface",
    ),
    EntrySurface(
        name="release-readiness",
        currentPoint="nanocode/release_readiness.py",
        observableResult=(
            "compile, test, smoke, runtime profile, and provider diagnostics "
            "summary"
        ),
        appRole="product app quality gate evidence",
    ),
)
