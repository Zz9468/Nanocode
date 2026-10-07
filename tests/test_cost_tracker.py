from __future__ import annotations

import pytest

from nanocode.cost_tracker import calculate_cost


def test_calculate_cost_handles_float_pricing_for_unknown_model() -> None:
    cost = calculate_cost(
        "qwen3.7-plus",
        input_tokens=1_000,
        output_tokens=500,
        cache_read_tokens=250,
        cache_creation_tokens=100,
    )

    assert isinstance(cost, float)
    assert cost == pytest.approx(0.01095)
