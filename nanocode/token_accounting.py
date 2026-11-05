"""Measure complete prepared requests, with scoped provider anchors and preflight counting."""
from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

from nanocode.model_policy import endpoint_origin, resolve_model_policy


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def estimate_text_tokens(text: str) -> int:
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))
    return max(1, int(cjk / 1.5 + (len(text) - cjk) / 4)) if text else 0


@dataclass(frozen=True)
class TokenMeasurement:
    input_tokens: int
    source: str
    exact: bool
    request_hash: str
    estimated_tokens: int = 0
    reason: str = ""

    def to_dict(self):
        return asdict(self)


class RequestTokenAccounting:
    """One adapter/channel. Never treats billed reasoning as replayed history."""

    def __init__(self, runtime: dict, endpoint: str, protocol: str,
                 prepare: Callable[[list[dict]], dict], headers: Callable[[], dict]):
        self.runtime, self.endpoint, self.protocol = runtime, endpoint, protocol
        self.prepare, self.headers = prepare, headers
        self.policy = resolve_model_policy(str(runtime.get("model", "")), runtime, endpoint=endpoint)
        self.anchor: dict | None = None
        self.calibration = 1.0
        self.calibrations: dict[str, dict] = {}
        self.count_cache: dict[str, int] = {}
        self.last: TokenMeasurement | None = None
        self.last_usage: dict | None = None
        self.count_error = ""
        self.count_requests = 0

    def _parts(self, body: dict) -> tuple[dict, list]:
        static = {k: v for k, v in body.items() if k not in ("messages", "stream", "stream_options", "max_tokens", "max_completion_tokens")}
        return {"endpoint": self.endpoint, "protocol": self.protocol, **static}, body.get("messages", [])

    def _rough(self, value: Any) -> int:
        return estimate_text_tokens(json.dumps(value, ensure_ascii=False, sort_keys=True)) + 16

    def _byte_budget(self, value: Any) -> int:
        # Without a matching tokenizer/count API, avoid the known chars/4
        # underestimate. This is a conservative request budget, not an exact count.
        return len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")) + 128

    def request_hash(self, body: dict) -> str:
        static, messages = self._parts(body)
        return fingerprint([static, messages])

    def check_request_budget(self, messages: list[dict]) -> TokenMeasurement:
        measurement = self.measure(messages, allow_remote=True)
        reserve = int(self.runtime.get("maxOutputTokens") or self.policy.output_reserve)
        budget = min(self.policy.max_input_tokens, self.policy.context_window - reserve) - self.policy.safety_margin
        if measurement.input_tokens >= budget:
            raise ValueError(f"Prepared request exceeds effective input budget ({measurement.input_tokens}/{budget}); output is reserved")
        return measurement

    def observe(self, body: dict, raw_usage: dict, input_tokens: int) -> None:
        """input_tokens includes cache hits/writes exactly once; output is excluded."""
        static, messages = self._parts(body)
        self.anchor = {"static_hash": fingerprint(static), "prefix": [fingerprint(m) for m in messages],
                       "input_tokens": int(input_tokens)}
        key = fingerprint(static)
        rough = self._rough([static, messages])
        previous = self.calibrations.get(key)
        slope = previous["slope"] if previous else 1.0
        if previous and rough != previous["rough"]:
            observed_slope = (input_tokens - previous["actual"]) / (rough - previous["rough"])
            if observed_slope > 0:
                slope = max(1.0, observed_slope)
        overhead = max(0, input_tokens - rough * slope)
        self.calibrations[key] = {"rough": rough, "actual": input_tokens, "slope": slope, "overhead": overhead}
        self.calibration = slope
        self.count_error = ""
        self.last_usage = {"request_hash": fingerprint([static, messages]), "raw_usage": dict(raw_usage),
                           "input_tokens": int(input_tokens)}

    def _remote_count(self, body: dict) -> int | None:
        config = self.runtime.get("tokenCounting") or {}
        if config.get("enabled") is False:
            return None
        target = config.get("endpoint")
        if not target and self.protocol == "anthropic" and urlsplit(self.endpoint).hostname == "api.anthropic.com":
            target = self.endpoint.rstrip("/") + "/count_tokens"
        if not target:
            return None
        if endpoint_origin(str(target)) != endpoint_origin(self.endpoint):
            raise ValueError("Token counting endpoint must share the generation endpoint origin")
        payload = {k: v for k, v in body.items() if k not in ("stream", "stream_options", "max_tokens", "max_completion_tokens")}
        request = urllib.request.Request(str(target), data=json.dumps(payload).encode(), headers=self.headers(), method="POST")
        self.count_requests += 1
        with urllib.request.urlopen(request, timeout=float(config.get("timeoutSeconds", 5))) as response:
            data = json.load(response)
        count = data.get("input_tokens")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("Token counting endpoint did not return nonnegative input_tokens")
        return count

    def measure(self, messages: list[dict], *, allow_remote=False) -> TokenMeasurement:
        body = self.prepare(messages)
        static, prepared = self._parts(body)
        request_hash = fingerprint([static, prepared])
        hashes = [fingerprint(m) for m in prepared]
        calibration = self.calibrations.get(fingerprint(static), {"slope": 1.0, "overhead": 0})
        if self.anchor and self.anchor["static_hash"] == fingerprint(static) and hashes == self.anchor["prefix"]:
            result = TokenMeasurement(self.anchor["input_tokens"], "provider_usage", True, request_hash)
        elif request_hash in self.count_cache:
            result = TokenMeasurement(self.count_cache[request_hash], "official_preflight", False, request_hash,
                                      reason="Official preflight count; response usage remains authoritative")
        elif self.anchor and self.anchor["static_hash"] == fingerprint(static) and hashes[:len(self.anchor["prefix"])] == self.anchor["prefix"]:
            tail = prepared[len(self.anchor["prefix"]):]
            delta = max(math.ceil(self._rough(tail) * calibration["slope"] * 1.2), self._byte_budget(tail)) if tail else 0
            result = TokenMeasurement(self.anchor["input_tokens"] + delta,
                "provider_usage_plus_estimate" if tail else "provider_usage", not tail, request_hash, delta)
        else:
            count = max(math.ceil(self._rough([static, prepared]) * calibration["slope"] * 1.2 + calibration["overhead"]),
                        self._byte_budget([static, prepared]))
            result = TokenMeasurement(count, "calibrated_request_estimate" if fingerprint(static) in self.calibrations else "conservative_request_estimate",
                                      False, request_hash, count,
                                      "Complete prepared request estimate; no matching provider anchor")
        if allow_remote and result.source != "provider_usage":
            threshold = float((self.runtime.get("tokenCounting") or {}).get("thresholdRatio", 0.5))
            if result.input_tokens >= self.policy.context_window * threshold:
                try:
                    count = self._remote_count(body)
                    if count is not None:
                        if len(self.count_cache) >= 32:
                            self.count_cache.clear()
                        self.count_cache[request_hash] = count
                        result = TokenMeasurement(count, "official_preflight", False, request_hash,
                                                  reason="Official preflight count; response usage remains authoritative")
                except Exception as error:
                    # Preserve conservative protection and surface failure; never report an exact zero.
                    self.count_error = f"{type(error).__name__}: counting unavailable"
                    result = TokenMeasurement(result.input_tokens, result.source, False, request_hash,
                                              result.estimated_tokens, self.count_error)
        if self.count_error and result.source not in ("provider_usage", "official_preflight"):
            result = TokenMeasurement(result.input_tokens, result.source, result.exact, result.request_hash,
                                      result.estimated_tokens, self.count_error)
        self.last = result
        return result


def preserve_constraints(before: list[dict], after: list[dict]) -> list[dict]:
    """Retain the initial user constraints and active user task verbatim."""
    users = [m for m in before if m.get("role") == "user"]
    protected = ([users[0], users[-1]] if users else [])
    result = list(after)
    for message in reversed(protected):
        if not any(fingerprint(m) == fingerprint(message) for m in result):
            index = next((i for i, m in enumerate(result) if m.get("role") != "system"), len(result))
            result.insert(index, dict(message))
    return result
