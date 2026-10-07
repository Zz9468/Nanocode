"""Public data contracts for persistent, evidence-backed agent memory."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from Package.AgentMemory.Src.Application.Dto.MemoryRecord import MemoryRecord


@dataclass
class WriteResult:
    saved_ids: list[str] = field(default_factory=list)
    skipped: int = 0
    pending: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class RetrievalResult:
    records: list[MemoryRecord] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemorySettings:
    workspace: str
    database: dict[str, Any]
    models: dict[str, Any] = field(default_factory=dict)
    owner_id: str = "default"
    machine_id: str = "local"
    project_id: str = ""
    data_dir: str = ""
    ledger_path: str = ""
    candidate_top_k: int = 20
    max_candidate_top_k: int = 50
    rrf_k: int = 60
    rerank_enabled: bool = True
    fail_open: bool = True
    budget_cny: float = 25.0
    curator_interval: int = 10

