from dataclasses import dataclass
from urllib.parse import urlsplit

PRICING_CATALOG_VERSION = "minimax-paygo-2026-07-14"
PRICING_SOURCE_URLS = (
    "https://platform.minimax.io/docs/guides/pricing-paygo",
    "https://platform.minimax.io/subscribe/token-plan?tab=api-enterprise",
    "https://platform.minimaxi.com/docs/guides/pricing-paygo",
)

_OFFICIAL_MINIMAX_HOSTS = frozenset({"api.minimax.io", "api.minimaxi.com"})


@dataclass(frozen=True, slots=True)
class TokenPriceTier:
    input_usd_per_million: float
    output_usd_per_million: float
    max_input_tokens: int | None = None

    def contains(self, input_tokens: int) -> bool:
        return self.max_input_tokens is None or input_tokens <= self.max_input_tokens


@dataclass(frozen=True, slots=True)
class ModelTokenPrice:
    provider: str
    model: str
    tiers: tuple[TokenPriceTier, ...]
    catalog_version: str = PRICING_CATALOG_VERSION
    source_urls: tuple[str, ...] = PRICING_SOURCE_URLS

    def estimate_usd(self, *, input_tokens: int, output_tokens: int) -> float | None:
        tier = next((item for item in self.tiers if item.contains(input_tokens)), None)
        if tier is None:
            return None
        return (
            input_tokens * tier.input_usd_per_million + output_tokens * tier.output_usd_per_million
        ) / 1_000_000


def _price(
    model: str,
    *,
    input_usd_per_million: float,
    output_usd_per_million: float,
) -> ModelTokenPrice:
    return ModelTokenPrice(
        provider="minimax",
        model=model,
        tiers=(
            TokenPriceTier(
                input_usd_per_million=input_usd_per_million,
                output_usd_per_million=output_usd_per_million,
            ),
        ),
    )


MINIMAX_PAYGO_PRICES: dict[str, ModelTokenPrice] = {
    "MiniMax-M3": ModelTokenPrice(
        provider="minimax",
        model="MiniMax-M3",
        tiers=(
            TokenPriceTier(
                input_usd_per_million=0.3,
                output_usd_per_million=1.2,
                max_input_tokens=512_000,
            ),
            TokenPriceTier(
                input_usd_per_million=0.6,
                output_usd_per_million=2.4,
                max_input_tokens=1_000_000,
            ),
        ),
    ),
    "MiniMax-M2.7": _price(
        "MiniMax-M2.7",
        input_usd_per_million=0.3,
        output_usd_per_million=1.2,
    ),
    "MiniMax-M2.7-highspeed": _price(
        "MiniMax-M2.7-highspeed",
        input_usd_per_million=0.6,
        output_usd_per_million=2.4,
    ),
    "MiniMax-M2.5": _price(
        "MiniMax-M2.5",
        input_usd_per_million=0.3,
        output_usd_per_million=1.2,
    ),
    "MiniMax-M2.5-highspeed": _price(
        "MiniMax-M2.5-highspeed",
        input_usd_per_million=0.6,
        output_usd_per_million=2.4,
    ),
    "MiniMax-M2.1": _price(
        "MiniMax-M2.1",
        input_usd_per_million=0.3,
        output_usd_per_million=1.2,
    ),
    "MiniMax-M2.1-highspeed": _price(
        "MiniMax-M2.1-highspeed",
        input_usd_per_million=0.6,
        output_usd_per_million=2.4,
    ),
    "MiniMax-M2": _price(
        "MiniMax-M2",
        input_usd_per_million=0.3,
        output_usd_per_million=1.2,
    ),
}


def resolve_token_price(
    *,
    provider: str,
    model: str,
    base_url: str,
) -> ModelTokenPrice | None:
    try:
        hostname = urlsplit(base_url).hostname
    except ValueError:
        return None
    if provider != "minimax" or hostname not in _OFFICIAL_MINIMAX_HOSTS:
        return None
    return MINIMAX_PAYGO_PRICES.get(model)
