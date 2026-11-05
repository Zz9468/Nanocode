"""Cost and usage tracking for API calls.

Tracks token usage, API costs, and code changes across the session.
Inspired by Claude Code's cost-tracker.ts implementation.
"""

from __future__ import annotations

import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal

# Precomputed Decimal constants for performance
_DECIMAL_1M = Decimal("1000000")
_DECIMAL_2 = Decimal("2")

# ---------------------------------------------------------------------------
# Pricing (approximate, per 1M tokens)
# ---------------------------------------------------------------------------

from nanocode.model_policy import MODEL_PRICING, PriceQuote, resolve_model_policy


# ---------------------------------------------------------------------------
# Cost calculation (standalone function for use outside CostTracker)
# ---------------------------------------------------------------------------

def calculate_cost(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float | None:
    """Calculate cost for a single API call.
    
    Args:
        model: Model name
        input_tokens: Input token count
        output_tokens: Output token count
        cache_read_tokens: Cache read token count
        cache_creation_tokens: Cache write token count
    
    Returns:
        Legacy USD quote, or None when this model/channel is unpriced
    """
    quote = resolve_model_policy(model).price
    if quote is None or quote.currency != "USD":
        return None
    return float(quote.calculate(input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ModelUsage:
    """Usage statistics for a specific model."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    call_count: int = 0
    error_count: int = 0
    total_duration_ms: int = 0
    estimated_calls: int = 0
    unreported_calls: int = 0
    unpriced_calls: int = 0
    amounts: dict[str, Decimal] = field(default_factory=dict)
    
    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )
    
    @property
    def avg_duration_ms(self) -> float:
        """Average API call duration."""
        if self.call_count == 0:
            return 0.0
        return self.total_duration_ms / self.call_count


@dataclass
class CostTracker:
    """Tracks API costs and usage across the session.
    
    Inspired by Claude Code's cost-tracker.ts
    """
    # Global totals
    total_cost_usd: float = 0.0
    total_api_duration_ms: int = 0
    total_lines_added: int = 0
    total_lines_removed: int = 0
    total_lines_modified: int = 0
    
    # Per-model usage
    model_usage: dict[str, ModelUsage] = field(default_factory=dict)
    totals_by_currency: dict[str, Decimal] = field(default_factory=dict)
    records: list[dict] = field(default_factory=list)
    
    # Session info
    session_start: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    
    def add_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        *,
        usage_source: str = "provider",
        runtime: dict | None = None,
        endpoint: str | None = None,
        request_hash: str = "",
        raw_usage: dict | None = None,
    ) -> float:
        """Record API usage.
        
        Args:
            model: Model name
            input_tokens: Input token count
            output_tokens: Output token count
            duration_ms: API call duration
            cache_read_tokens: Cache read token count
            cache_write_tokens: Cache write token count
        
        Returns:
            Calculated cost in USD
        """
        policy = resolve_model_policy(model, runtime, endpoint=endpoint)
        try:
            quote = policy.price.for_input(input_tokens + cache_read_tokens + cache_write_tokens) if policy.price else None
        except ValueError:
            quote = None
        amount = quote.calculate(input_tokens, output_tokens, cache_read_tokens, cache_write_tokens) if quote and usage_source != "unavailable" else None
        cost = float(amount) if amount is not None and quote.currency == "USD" else 0.0
        self.records.append({"id": uuid.uuid4().hex, "recorded_at": time.time(), "model": model,
            "endpoint": policy.endpoint,
            "request_hash": request_hash, "usage_source": usage_source, "raw_usage": deepcopy(raw_usage or {}),
            "tokens": {"input": input_tokens, "output": output_tokens, "cache_read": cache_read_tokens, "cache_write": cache_write_tokens},
            "pricing": quote.to_dict() if quote else None, "amount": str(amount) if amount is not None else None,
            "currency": quote.currency if quote else None})

        # Update model usage
        if model not in self.model_usage:
            self.model_usage[model] = ModelUsage()
        
        usage = self.model_usage[model]
        usage.input_tokens += input_tokens
        usage.output_tokens += output_tokens
        usage.cache_read_tokens += cache_read_tokens
        usage.cache_write_tokens += cache_write_tokens
        usage.cost_usd += cost
        usage.call_count += 1
        usage.unpriced_calls += int(amount is None)
        if amount is not None:
            usage.amounts[quote.currency] = usage.amounts.get(quote.currency, Decimal(0)) + amount
            self.totals_by_currency[quote.currency] = self.totals_by_currency.get(quote.currency, Decimal(0)) + amount
        usage.estimated_calls += int(usage_source == "estimated")
        usage.unreported_calls += int(usage_source == "unavailable")
        usage.total_duration_ms += duration_ms
        
        # Update totals
        self.total_cost_usd += cost
        self.total_api_duration_ms += duration_ms
        self.last_updated = time.time()
        
        return cost
    
    def record_error(self, model: str) -> None:
        """Record an API error.
        
        Args:
            model: Model name
        """
        if model not in self.model_usage:
            self.model_usage[model] = ModelUsage()
        
        self.model_usage[model].error_count += 1
        self.last_updated = time.time()
    
    def record_code_changes(
        self,
        lines_added: int = 0,
        lines_removed: int = 0,
    ) -> None:
        """Record code changes.
        
        Args:
            lines_added: Lines added
            lines_removed: Lines removed
        """
        self.total_lines_added += lines_added
        self.total_lines_removed += lines_removed
        self.total_lines_modified += lines_added + lines_removed
        self.last_updated = time.time()
    
    def get_model_usage(self, model: str) -> ModelUsage:
        """Get usage for a specific model.
        
        Args:
            model: Model name
        
        Returns:
            ModelUsage instance
        """
        return self.model_usage.get(model, ModelUsage())
    
    def get_total_tokens(self) -> int:
        """Get total tokens across all models."""
        return sum(u.total_tokens for u in self.model_usage.values())
    
    def get_total_calls(self) -> int:
        """Get total API calls."""
        return sum(u.call_count + u.error_count for u in self.model_usage.values())
    
    def get_total_errors(self) -> int:
        """Get total API errors."""
        return sum(u.error_count for u in self.model_usage.values())
    
    # -----------------------------------------------------------------------
    # Formatting
    # -----------------------------------------------------------------------
    
    def format_cost_report(self, detailed: bool = False) -> str:
        def amounts(values):
            return ", ".join(f"{currency} {amount:.6f}" for currency, amount in sorted(values.items())) or "none priced"
        unpriced = sum(u.unpriced_calls for u in self.model_usage.values())
        lines = ["Cost & Usage Report", "=" * 60,
            "Scope: current process; restored sessions start new counters.",
            "Cost: versioned local tariff estimate; currency totals are never combined.",
            "Input excludes cache read/write; total tokens include each exactly once.",
            "Internal retries and auxiliary model requests may be excluded.", "", "Summary:",
            f"  Total cost: {amounts(self.totals_by_currency)}",
            f"  Unpriced responses: {unpriced}",
            f"  Total API calls: {self.get_total_calls()}", f"  Total API errors: {self.get_total_errors()}",
            f"  Total tokens: {self.get_total_tokens():,}",
            f"  Estimated token usage: {sum(u.estimated_calls for u in self.model_usage.values())} response(s)",
            f"  Without token usage: {sum(u.unreported_calls for u in self.model_usage.values())}",
            f"  Total API duration: {self.total_api_duration_ms / 1000:.1f}s", "", "Code Changes (recorded only):",
            f"  Lines added: {self.total_lines_added:,}", f"  Lines removed: {self.total_lines_removed:,}",
            f"  Total modified: {self.total_lines_modified:,}"]
        if detailed:
            lines += ["", "Per-Model Breakdown:", "-" * 60]
            for model, usage in self.model_usage.items():
                quotes = [r for r in self.records if r["model"] == model]
                price = quotes[-1]["pricing"] if quotes else None
                versions = sorted({r["pricing"]["version"] for r in quotes if r["pricing"]})
                lines += ["", f"  {model}:", f"    Cost: {amounts(usage.amounts)}",
                    f"    Pricing: {price['version'] if price else 'unpriced (model/channel price unavailable)'}",
                    f"    Price versions recorded: {', '.join(versions) or 'none'}",
                    f"    Currency: {price['currency'] if price else 'unknown'}",
                    f"    Source: {price['source_url'] if price else 'none'}",
                    f"    Verified: {price['verified_at'] if price else 'none'}",
                    f"    Calls: {usage.call_count}", f"    Errors: {usage.error_count}",
                    f"    Tokens: {usage.total_tokens:,}", f"      Input: {usage.input_tokens:,}",
                    f"      Output: {usage.output_tokens:,}", f"      Cache read: {usage.cache_read_tokens:,}",
                    f"      Cache write: {usage.cache_write_tokens:,}", f"    Avg duration: {usage.avg_duration_ms:.0f}ms"]
        minutes = (time.time() - self.session_start) / 60
        rates = {currency: amount / Decimal(str(max(1, minutes))) for currency, amount in self.totals_by_currency.items()}
        lines += ["", "-" * 60, f"Session duration: {minutes:.1f} minutes", f"Cost per minute: {amounts(rates)}"]
        return "\n".join(lines)

    def format_short_summary(self) -> str:
        parts = [f"{currency} {amount:.6f}" for currency, amount in sorted(self.totals_by_currency.items())]
        unknown = sum(u.unpriced_calls for u in self.model_usage.values())
        if unknown:
            parts.append(f"{unknown} unpriced")
        return "Cost: " + (", ".join(parts) if parts else "no usage")
