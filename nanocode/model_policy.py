"""Channel-scoped model limits and versioned prices; no network or credentials."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit


# Historical table is moved here below. Compatibility imports share this object.
MODEL_PRICING = {
    # Anthropic models (USD per 1M tokens)
    "claude-sonnet-4-20250514": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-opus-4-20250514": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.50,
        "cache_write": 18.75,
    },
    "claude-haiku-3-20240307": {
        "input": 0.25,
        "output": 1.25,
        "cache_read": 0.03,
        "cache_write": 0.30,
    },
    # OpenAI models
    "gpt-4o": {
        "input": 2.50,
        "output": 10.0,
        "cache_read": 1.25,
        "cache_write": 2.50,
    },
    "gpt-4o-mini": {
        "input": 0.15,
        "output": 0.60,
        "cache_read": 0.08,
        "cache_write": 0.15,
    },
    "gpt-4-turbo": {
        "input": 10.0,
        "output": 30.0,
        "cache_read": 5.0,
        "cache_write": 10.0,
    },
    "o1": {
        "input": 15.0,
        "output": 60.0,
        "cache_read": 7.50,
        "cache_write": 15.0,
    },
    "o1-mini": {
        "input": 3.0,
        "output": 12.0,
        "cache_read": 1.50,
        "cache_write": 3.0,
    },
    "o3-mini": {
        "input": 1.10,
        "output": 4.40,
        "cache_read": 0.55,
        "cache_write": 1.10,
    },
    # OpenRouter models (pricing via OpenRouter, approximate)
    "openrouter/auto": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "anthropic/claude-sonnet-4": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "anthropic/claude-opus-4": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.50,
        "cache_write": 18.75,
    },
    "openai/gpt-4o": {
        "input": 2.50,
        "output": 10.0,
        "cache_read": 1.25,
        "cache_write": 2.50,
    },
    "openai/gpt-4o-mini": {
        "input": 0.15,
        "output": 0.60,
        "cache_read": 0.08,
        "cache_write": 0.15,
    },
    "google/gemini-2.5-pro": {
        "input": 1.25,
        "output": 10.0,
        "cache_read": 0.63,
        "cache_write": 1.25,
    },
    "google/gemini-2.5-flash": {
        "input": 0.15,
        "output": 0.60,
        "cache_read": 0.08,
        "cache_write": 0.15,
    },
    "meta-llama/llama-4-maverick": {
        "input": 0.20,
        "output": 0.60,
        "cache_read": 0.10,
        "cache_write": 0.20,
    },
    "deepseek/deepseek-r1": {
        "input": 0.55,
        "output": 2.19,
        "cache_read": 0.14,
        "cache_write": 0.55,
    },
    "deepseek/deepseek-chat": {
        "input": 0.14,
        "output": 0.28,
        "cache_read": 0.07,
        "cache_write": 0.14,
    },
    "qwen/qwen3-235b-a22b": {
        "input": 0.22,
        "output": 0.88,
        "cache_read": 0.11,
        "cache_write": 0.22,
    },
    "minimax/minimax-m1": {
        "input": 0.20,
        "output": 0.80,
        "cache_read": 0.10,
        "cache_write": 0.20,
    },

}


LEGACY_MODEL_LIMITS = {'claude-sonnet-4-20250514': {'context_window': 200000, 'max_output_tokens': 16384},
 'claude-opus-4-20250514': {'context_window': 200000, 'max_output_tokens': 16384},
 'claude-haiku-3-20240307': {'context_window': 100000, 'max_output_tokens': 4096},
 'gpt-4o': {'context_window': 128000, 'max_output_tokens': 16384},
 'gpt-4o-mini': {'context_window': 128000, 'max_output_tokens': 16384},
 'gpt-4-turbo': {'context_window': 128000, 'max_output_tokens': 4096},
 'gpt-5.5': {'context_window': 128000, 'max_output_tokens': 16384},
 'gpt5.5': {'context_window': 128000, 'max_output_tokens': 16384},
 'o1': {'context_window': 200000, 'max_output_tokens': 100000},
 'o1-mini': {'context_window': 128000, 'max_output_tokens': 65536},
 'o3-mini': {'context_window': 200000, 'max_output_tokens': 100000},
 'openrouter/auto': {'context_window': 200000},
 'anthropic/claude-sonnet-4': {'context_window': 200000, 'max_output_tokens': 16384},
 'anthropic/claude-opus-4': {'context_window': 200000, 'max_output_tokens': 16384},
 'openai/gpt-4o': {'context_window': 128000, 'max_output_tokens': 16384},
 'openai/gpt-4o-mini': {'context_window': 128000, 'max_output_tokens': 16384},
 'google/gemini-2.5-pro': {'context_window': 1000000, 'max_output_tokens': 8192},
 'google/gemini-2.5-flash': {'context_window': 1000000, 'max_output_tokens': 8192},
 'meta-llama/llama-4-maverick': {'context_window': 1000000, 'max_output_tokens': 8192},
 'deepseek/deepseek-r1': {'context_window': 128000, 'max_output_tokens': 8192},
 'deepseek/deepseek-chat': {'context_window': 128000, 'max_output_tokens': 8192},
 'deepseek-v4-pro[1m]': {'context_window': 128000, 'max_output_tokens': 8192},
 'qwen/qwen3-235b-a22b': {'context_window': 128000, 'max_output_tokens': 8192},
 'minimax/minimax-m1': {'context_window': 1000000, 'max_output_tokens': 8192}}
DEFAULT_CONTEXT_WINDOWS = {name: values["context_window"] for name, values in LEGACY_MODEL_LIMITS.items()}
DEFAULT_CONTEXT_WINDOWS["default"] = 128_000


class ModelContextWindow:
    __slots__ = ("context_window", "output_reserve", "effective_input")

    def __init__(self, context_window: int, output_reserve: int) -> None:
        self.context_window = context_window
        self.output_reserve = output_reserve
        self.effective_input = context_window - output_reserve


_UNKNOWN_MODEL_CONTEXT = (128_000, 8_000)

_MODEL_CONTEXT_RULES: list[tuple[list[str], int, int]] = [
    (["claude-opus-4-6", "claude opus 4.6", "opus-4-6"], 200_000, 16_000),
    (["claude-sonnet-4-6", "claude sonnet 4.6", "sonnet-4-6"], 200_000, 16_000),
    (["claude-haiku-4-5", "claude haiku 4.5", "haiku-4-5"], 200_000, 16_000),
    (["claude-opus-4-1", "claude opus 4.1", "opus-4-1", "claude-opus-4", "claude opus 4", "opus-4"], 200_000, 16_000),
    (["claude-sonnet-4", "claude sonnet 4", "sonnet-4"], 200_000, 16_000),
    (["claude-3-7-sonnet", "claude 3.7 sonnet", "3-7-sonnet"], 200_000, 8_192),
    (["claude-3-5-sonnet", "claude 3.5 sonnet", "3-5-sonnet", "claude-3-sonnet"], 200_000, 8_192),
    (["claude-3-5-haiku", "claude 3.5 haiku", "3-5-haiku"], 200_000, 8_192),
    (["claude-3-opus", "claude 3 opus"], 200_000, 4_096),
    (["claude-3-haiku", "claude 3 haiku"], 200_000, 4_096),
    (["gpt-5-codex", "gpt-5.4", "gpt-5.2", "gpt-5.1", "gpt-5"], 128_000, 16_000),
    (["o4-mini", "o3", "o1-pro", "o1"], 200_000, 16_000),
    (["gpt-4.1-mini", "gpt-4.1-nano", "gpt-4.1"], 1_047_576, 16_000),
    (["gpt-4o-mini", "gpt-4o"], 128_000, 16_384),
    (["gpt-4"], 128_000, 8_192),
    (["gemini-2.5-pro", "gemini 2.5 pro"], 1_048_576, 16_000),
    (["gemini-2.5-flash-lite", "gemini 2.5 flash-lite"], 1_048_576, 16_000),
    (["gemini-2.5-flash", "gemini 2.5 flash"], 1_048_576, 16_000),
    (["deepseek-reasoner"], 128_000, 16_000),
    (["deepseek-chat"], 128_000, 4_000),
]


def get_model_context_window(model: str) -> ModelContextWindow:
    """Resolve a model id to its context window + output reserve.

    Case-insensitive substring match (port of TS getModelContextWindow).
    Falls back to 128k / 8k reserve for unknown models.
    """
    normalized = (model or "").strip().lower()
    for patterns, context_window, output_reserve in _MODEL_CONTEXT_RULES:
        if any(pattern in normalized for pattern in patterns):
            return ModelContextWindow(context_window, output_reserve)
    context_window, output_reserve = _UNKNOWN_MODEL_CONTEXT
    return ModelContextWindow(context_window, output_reserve)



@dataclass(frozen=True)
class PriceQuote:
    currency: str
    input: str
    output: str
    cache_read: str = "0"
    cache_write: str = "0"
    unit_tokens: int = 1_000_000
    version: str = "unspecified"
    source_url: str = ""
    verified_at: str = ""
    tiers: tuple = ()
    tier_limit: int | None = None

    def for_input(self, input_tokens: int) -> "PriceQuote":
        for limit, input_rate, output_rate, read_rate, write_rate in self.tiers:
            if limit is None or input_tokens <= limit:
                return replace(self, input=input_rate, output=output_rate, cache_read=read_rate,
                               cache_write=write_rate, tiers=(), tier_limit=limit)
        if self.tiers:
            raise ValueError("Input exceeds the configured tariff tiers")
        return self

    def calculate(self, input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0) -> Decimal:
        if self.tiers:
            return self.for_input(input_tokens + cache_read_tokens + cache_write_tokens).calculate(input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)
        counts = (input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)
        rates = (self.input, self.output, self.cache_read, self.cache_write)
        if any(n < 0 for n in counts):
            raise ValueError("Token counts must be nonnegative")
        return sum((Decimal(n) * Decimal(r) for n, r in zip(counts, rates)), Decimal(0)) / self.unit_tokens

    def to_dict(self):
        return {**asdict(self), "tiers": [list(tier) for tier in self.tiers]}


@dataclass(frozen=True)
class ModelPolicy:
    model: str
    endpoint: str
    context_window: int = 128_000
    max_input_tokens: int = 120_000
    max_output_tokens: int = 8_192
    output_reserve: int = 8_000
    safety_margin: int = 2_048
    source: str = "conservative unknown-model limits"
    price: PriceQuote | None = None


def endpoint_origin(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if parsed.username or parsed.password:
        raise ValueError("Model endpoint must not contain embedded credentials")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}" if parsed.netloc else ""


def runtime_endpoint(runtime: dict[str, Any]) -> str:
    return str(runtime.get("customBaseUrl") or runtime.get("openaiBaseUrl") or runtime.get("baseUrl") or "")


def _price(data: dict[str, Any], *, require_source: bool = True) -> PriceQuote:
    currency = str(data.get("currency", "")).upper()
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        raise ValueError("Pricing currency must be a three-letter code")
    rates = [str(data[key]) for key in ("input", "output", "cacheRead", "cacheWrite")]
    if any(not Decimal(rate).is_finite() or Decimal(rate) < 0 for rate in rates):
        raise ValueError("Pricing rates must be finite and nonnegative")
    unit = int(data.get("unitTokens", 1_000_000))
    if unit <= 0:
        raise ValueError("Pricing unitTokens must be positive")
    if require_source and not all(data.get(k) for k in ("version", "sourceUrl", "verifiedAt")):
        raise ValueError("Configured pricing requires version, sourceUrl and verifiedAt")
    tiers = []
    previous = 0
    for index, tier in enumerate(data.get("tiers", [])):
        limit = tier.get("maxInputTokens")
        if limit is not None and (isinstance(limit, bool) or int(limit) <= previous):
            raise ValueError("Pricing tier limits must be strictly increasing")
        if limit is None and index != len(data["tiers"]) - 1:
            raise ValueError("An unlimited pricing tier must be last")
        quote = _price({**data, **tier, "tiers": []}, require_source=require_source)
        tiers.append((int(limit) if limit is not None else None, quote.input, quote.output, quote.cache_read, quote.cache_write))
        previous = int(limit) if limit is not None else previous
    return PriceQuote(currency, *rates, unit, str(data.get("version", "legacy-table")),
                      str(data.get("sourceUrl", "")), str(data.get("verifiedAt", "")), tuple(tiers))


def resolve_model_policy(model: str, runtime: dict[str, Any] | None = None, *, endpoint: str | None = None) -> ModelPolicy:
    runtime = runtime or {}
    endpoint = endpoint if endpoint is not None else runtime_endpoint(runtime)
    origin = endpoint_origin(endpoint)
    region = str(runtime.get("modelRegion") or ("cn-beijing" if origin == "https://dashscope.aliyuncs.com" else ""))
    scope = str(runtime.get("deploymentScope") or "")
    billing = str(runtime.get("billingMode") or "pay-as-you-go")
    window = get_model_context_window(model)
    policy = ModelPolicy(model, origin, window.context_window, window.context_window, max(window.output_reserve, 8192), window.output_reserve)
    known_limits = LEGACY_MODEL_LIMITS.get(model, {})
    if known_limits:
        total_window = known_limits.get("context_window", policy.context_window)
        maximum_output = known_limits.get("max_output_tokens", policy.max_output_tokens)
        reserve = min(policy.output_reserve, maximum_output)
        policy = replace(policy, context_window=total_window, max_input_tokens=total_window,
                         max_output_tokens=maximum_output, output_reserve=reserve, source="legacy model catalog limits")
    # Scope official tariffs to their actual channel, never to a model alias alone.
    if model == "qwen3.8-flash" and origin == "https://dashscope.aliyuncs.com":
        policy = ModelPolicy(model, origin, 1_000_000, 983_616, 131_072, 8_192, 2_048,
            "Alibaba Model Studio cn-beijing; verified 2026-11-05",
            PriceQuote("CNY", "0.8", "2.7", "0.1", "1.25", version="bailian-cn-beijing-2026-11-05",
                source_url="https://help.aliyun.com/en/model-studio/qwen3-8-flash", verified_at="2026-11-05") if region == "cn-beijing" and billing == "pay-as-you-go" else None)
    else:
        expected = ("api.anthropic.com" if model.startswith("claude-") else
                    "openrouter.ai" if "/" in model else "api.openai.com")
        host = urlsplit(endpoint).hostname
        rates = MODEL_PRICING.get(model) if host in (None, expected) else None
        if rates and model != "default":
            quote = PriceQuote("USD", str(rates["input"]), str(rates["output"]),
                               str(rates["cache_read"]), str(rates["cache_write"]), version="legacy-table")
            policy = replace(policy, price=quote)
    entries = runtime.get("modelPolicies", [])
    if not isinstance(entries, list):
        raise ValueError("modelPolicies must be a list")
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("model") == model
               and endpoint_origin(str(entry.get("endpoint", ""))) == origin
               and (not urlsplit(str(entry.get("endpoint", ""))).path.rstrip("/")
                    or urlsplit(endpoint).path.startswith(urlsplit(str(entry["endpoint"])).path.rstrip("/") + "/")
                    or urlsplit(endpoint).path.rstrip("/") == urlsplit(str(entry["endpoint"])).path.rstrip("/"))
               and entry.get("region", region) == region and entry.get("deploymentScope", scope) == scope
               and entry.get("billingMode", billing) == billing]
    if matches:
        specificity = max((sum(key in e for key in ("region", "deploymentScope", "billingMode")), len(urlsplit(str(e["endpoint"])).path)) for e in matches)
        matches = [e for e in matches if (sum(key in e for key in ("region", "deploymentScope", "billingMode")), len(urlsplit(str(e["endpoint"])).path)) == specificity]
    if len(matches) > 1:
        raise ValueError("Duplicate modelPolicies for the same model and endpoint")
    if matches:
        entry = matches[0]
        values = {"context_window": "contextWindow", "max_input_tokens": "maxInputTokens",
                  "max_output_tokens": "maxOutputTokens", "output_reserve": "outputReserve", "safety_margin": "safetyMargin"}
        limits = {name: int(entry.get(key, getattr(policy, name))) for name, key in values.items()}
        if any(value < (0 if name == "safety_margin" else 1) for name, value in limits.items()):
            raise ValueError("Model limits must be positive (safety margin may be zero)")
        if limits["max_input_tokens"] > limits["context_window"]:
            raise ValueError("maxInputTokens cannot exceed contextWindow")
        if limits["output_reserve"] > limits["max_output_tokens"] or limits["output_reserve"] + limits["safety_margin"] >= limits["context_window"]:
            raise ValueError("Model output reserve and safety margin leave no input budget")
        policy = ModelPolicy(model, origin, **limits, source="configured modelPolicies",
                             price=_price(entry["pricing"]) if "pricing" in entry else policy.price)
    return policy
