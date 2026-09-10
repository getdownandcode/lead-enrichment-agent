from lead_agent.llm import estimate_cost_usd


def test_estimate_cost_uses_flash_lite_pricing():
    assert estimate_cost_usd("gemini-3.5-flash-lite", 1_000_000, 1_000_000) == 0.5


def test_estimate_cost_scales_linearly():
    assert estimate_cost_usd("gemini-3.5-flash-lite", 7242, 380) == round(
        7242 / 1_000_000 * 0.10 + 380 / 1_000_000 * 0.40, 6
    )


def test_estimate_cost_unknown_model_falls_back_to_default_tier():
    assert estimate_cost_usd("gemini-9.9-ultra", 1_000_000, 0) == 0.1


def test_estimate_cost_zero_usage_is_zero():
    assert estimate_cost_usd("gemini-3.5-flash-lite", 0, 0) == 0.0
