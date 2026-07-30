from cost import TokenUsage, estimate_cost_usd, format_summary

PRICING = {
    "usd_per_million": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    }
}


def test_token_usage_accumulates_across_calls():
    usage = TokenUsage()
    usage.add({"input_tokens": 1000, "output_tokens": 100})
    usage.add({"input_tokens": 500, "output_tokens": 50, "cache_read_input_tokens": 200})

    assert usage.input_tokens == 1500
    assert usage.output_tokens == 150
    assert usage.cache_creation_input_tokens == 0
    assert usage.cache_read_input_tokens == 200


def test_token_usage_add_tolerates_missing_keys():
    usage = TokenUsage()
    usage.add({})  # respuesta sin campos de usage (ej. boleta con error antes de llamar a la API)
    assert usage.total_tokens == 0


def test_token_usage_total_tokens_sums_all_four_components():
    usage = TokenUsage(
        input_tokens=1000,
        output_tokens=200,
        cache_creation_input_tokens=50,
        cache_read_input_tokens=25,
    )
    assert usage.total_tokens == 1275


def test_estimate_cost_usd_matches_formula():
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    # A un millón de tokens de cada tipo, el costo es exactamente la suma de precios.
    assert estimate_cost_usd(usage, PRICING) == 3.00 + 15.00 + 3.75 + 0.30


def test_estimate_cost_usd_real_world_numbers():
    # 12 boletas, ~1500 tokens de entrada y ~200 de salida cada una (orden de magnitud real).
    usage = TokenUsage(input_tokens=18000, output_tokens=2400)
    expected = (18000 / 1_000_000) * 3.00 + (2400 / 1_000_000) * 15.00
    assert estimate_cost_usd(usage, PRICING) == expected


def test_estimate_cost_usd_zero_usage_is_zero_cost():
    assert estimate_cost_usd(TokenUsage(), PRICING) == 0.0


def test_estimate_cost_usd_handles_missing_pricing_config():
    # Si config.yaml no trae pricing (o está vacío), no debe reventar: costo 0.
    assert estimate_cost_usd(TokenUsage(input_tokens=1000), {}) == 0.0


def test_format_summary_includes_all_fields_and_disclaimer():
    usage = TokenUsage(input_tokens=1500, output_tokens=200)
    summary = format_summary(1, usage, PRICING)

    assert "Resumen de ejecución" in summary
    assert "Boletas procesadas:    1" in summary
    assert "Tokens de entrada:     1,500" in summary
    assert "Tokens de salida:      200" in summary
    assert "Tokens totales:        1,700" in summary
    assert "estimado" in summary.lower()
    assert "config.yaml" in summary


def test_format_summary_shows_cache_lines_only_when_present():
    no_cache = format_summary(1, TokenUsage(input_tokens=100, output_tokens=10), PRICING)
    assert "caché" not in no_cache.lower()

    with_cache = format_summary(
        1,
        TokenUsage(input_tokens=100, output_tokens=10, cache_read_input_tokens=50),
        PRICING,
    )
    assert "caché" in with_cache.lower()
