from __future__ import annotations

from Main.NanocodeFrontline.Src.Application.Entry.RuntimeLifecycleSurface import (
    RUNTIME_LIFECYCLE_ENTRIES,
    lifecycle_contract_payload,
    lifecycle_script_targets,
)


def test_runtime_lifecycle_surface_declares_console_entries() -> None:
    assert lifecycle_script_targets() == {
        "nanocode": "nanocode.main:main",
        "nanocode-headless": "nanocode.headless:main",
        "nanocode-readiness": "nanocode.readiness:main",
        "nanocode-py": "nanocode.main:main",
    }


def test_runtime_lifecycle_surface_payload_tracks_product_identity() -> None:
    payload = lifecycle_contract_payload()

    assert payload["logicalProductApp"] == "product/app/nanocode_frontline"
    assert payload["entryCount"] == 3
    assert all(entry.lifecycleRole for entry in RUNTIME_LIFECYCLE_ENTRIES)
