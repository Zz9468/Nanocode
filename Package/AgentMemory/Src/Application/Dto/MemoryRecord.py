"""Public representation of one persisted memory and its evidence."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryRecord:
    id: str
    namespace_id: str
    scope: str
    kind: str
    content: str
    status: str = "active"
    tier: str = "short_term"
    revision: int = 1
    tags: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    source_type: str = "explicit"
    created_at: float = 0
    updated_at: float = 0
    usage_count: int = 0
    score: float = 0
