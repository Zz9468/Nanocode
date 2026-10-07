"""Cross-process budget reservations survive crashes and uncertain billing."""
import json
import math
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

class BudgetExceeded(RuntimeError):
    pass

class CostLedger:
    _lock = threading.RLock()

    def __init__(self, path, limit=25):
        self.path = Path(path)
        configured_limit = float(limit)
        if not math.isfinite(configured_limit) or configured_limit < 0:
            raise ValueError("budget must be a finite nonnegative amount")
        self.limit = min(configured_limit, 25.0)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _state(self):
        with self._lock, open(str(self.path) + ".lock", "a+b") as lock:
            lock.seek(0)
            if os.name == "nt":
                import msvcrt
                if os.fstat(lock.fileno()).st_size == 0:
                    lock.write(b"0"); lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                state = json.loads(self.path.read_text("utf-8")) if self.path.exists() else {"calls": []}
                yield state
                temp = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
                with temp.open("w", encoding="utf-8") as stream:
                    json.dump(state, stream, ensure_ascii=False, indent=2)
                    stream.flush(); os.fsync(stream.fileno())
                os.replace(temp, self.path)
            finally:
                if os.name == "nt":
                    lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def reserve(self, kind, input_bound, output_bound=0):
        if kind not in {"generation", "embedding", "rerank"}:
            raise ValueError("unknown billable request kind")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (input_bound, output_bound)):
            raise ValueError("token bounds must be nonnegative integers")
        ceiling = (input_bound * (4 if kind == "generation" else 2) + output_bound * 12) / 1_000_000
        with self._state() as state:
            consumed = sum(c["accounted_cny"] for c in state["calls"])
            if consumed + ceiling > self.limit:
                raise BudgetExceeded("model request denied: total budget would exceed 25 CNY")
            key = uuid.uuid4().hex
            state["calls"].append({"id": key, "kind": kind, "time": time.time(), "accounted_cny": ceiling,
                "reserved_cny": ceiling, "estimated_cny": 0, "status": "reserved"})
            return key

    def settle(self, key, usage):
        with self._state() as state:
            call = next(c for c in state["calls"] if c["id"] == key)
            if call["status"] == "settled":
                return
            if not isinstance(usage, dict):
                return
            inputs = usage.get("prompt_tokens", usage.get("input_tokens", usage.get("total_tokens")))
            outputs = usage.get("completion_tokens", usage.get("output_tokens", 0))
            if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (inputs, outputs)):
                return
            kind = call["kind"]
            # Keep conservative prices, including unknown/failed attempts. Estimates use published prices.
            call["accounted_cny"] = max((inputs * (4 if kind == "generation" else 2) + outputs * 12) / 1_000_000, 0.000001)
            call["estimated_cny"] = (inputs * (.8 if kind == "generation" else .5) + outputs * (2.7 if kind == "generation" else 0)) / 1_000_000
            call.update(status="settled", input_tokens=inputs, output_tokens=outputs)

    def summary(self):
        with self._state() as state:
            return {"limit_cny": self.limit, "calls": len(state["calls"]),
                "accounted_cny": sum(c["accounted_cny"] for c in state["calls"]),
                "estimated_cny": sum(c["estimated_cny"] for c in state["calls"]),
                "uncertain_calls": sum(c["status"] != "settled" for c in state["calls"])}
