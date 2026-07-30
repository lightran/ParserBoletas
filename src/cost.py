"""Acumulación de uso de tokens de la API de Claude y estimación de costo de la corrida.

El costo es siempre una ESTIMACIÓN: depende de los precios configurados en
config.yaml (pricing), que hay que mantener al día contra la página oficial
de precios de Anthropic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def add(self, usage: dict) -> None:
        """Suma el `usage` crudo de una respuesta de la API (dict con las 4 claves,
        cualquiera de ellas puede faltar según la respuesta)."""
        self.input_tokens += int(usage.get("input_tokens", 0) or 0)
        self.output_tokens += int(usage.get("output_tokens", 0) or 0)
        self.cache_creation_input_tokens += int(usage.get("cache_creation_input_tokens", 0) or 0)
        self.cache_read_input_tokens += int(usage.get("cache_read_input_tokens", 0) or 0)

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )


def estimate_cost_usd(usage: TokenUsage, pricing_cfg: dict) -> float:
    prices = (pricing_cfg or {}).get("usd_per_million", {})
    return (
        (usage.input_tokens / 1_000_000) * float(prices.get("input", 0) or 0)
        + (usage.output_tokens / 1_000_000) * float(prices.get("output", 0) or 0)
        + (usage.cache_creation_input_tokens / 1_000_000) * float(prices.get("cache_write", 0) or 0)
        + (usage.cache_read_input_tokens / 1_000_000) * float(prices.get("cache_read", 0) or 0)
    )


def format_summary(n_processed: int, usage: TokenUsage, pricing_cfg: dict) -> str:
    cost = estimate_cost_usd(usage, pricing_cfg)
    lines = [
        "── Resumen de ejecución ──",
        f"Boletas procesadas:    {n_processed}",
        f"Tokens de entrada:     {usage.input_tokens:,}",
        f"Tokens de salida:      {usage.output_tokens:,}",
    ]
    if usage.cache_creation_input_tokens or usage.cache_read_input_tokens:
        lines.append(f"Tokens de caché (escritura): {usage.cache_creation_input_tokens:,}")
        lines.append(f"Tokens de caché (lectura):   {usage.cache_read_input_tokens:,}")
    lines.append(f"Tokens totales:        {usage.total_tokens:,}")
    lines.append(f"Costo estimado (USD):  ${cost:.4f}  (estimado — verificar precios en config.yaml)")
    return "\n".join(lines)
