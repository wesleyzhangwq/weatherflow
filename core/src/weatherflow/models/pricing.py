from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class BillingOrigin(StrEnum):
    """User-confirmed MiniMax billing product and region.

    An API hostname is deliberately not represented here: the same endpoint can
    accept keys backed by pay-as-you-go, Token Plan, or Credits.  Only the user
    (or a future provider billing API) can authoritatively select this value.
    """

    MINIMAX_GLOBAL_PAYGO = "minimax_global_paygo"
    MINIMAX_CN_PAYGO = "minimax_cn_paygo"
    MINIMAX_GLOBAL_TOKEN_PLAN = "minimax_global_token_plan"
    MINIMAX_CN_TOKEN_PLAN = "minimax_cn_token_plan"


CostCurrency = Literal["USD", "CNY"]
CostScope = Literal["model_usage_only"]
COST_SCOPE: CostScope = "model_usage_only"

MINIMAX_GLOBAL_PAYGO_CATALOG_VERSION = "minimax-global-paygo-usd-2026-07-21"
MINIMAX_CN_PAYGO_CATALOG_VERSION = "minimax-cn-paygo-cny-2026-07-21"
MINIMAX_GLOBAL_PAYGO_SOURCE_URLS = (
    "https://platform.minimax.io/docs/guides/pricing-paygo",
    "https://platform.minimax.io/docs/api-reference/text-prompt-caching",
)
MINIMAX_CN_PAYGO_SOURCE_URLS = ("https://platform.minimaxi.com/docs/guides/pricing-paygo",)
MINIMAX_TOKEN_PLAN_SOURCE_URLS = (
    "https://platform.minimax.io/docs/guides/pricing-token-plan",
    "https://platform.minimaxi.com/docs/token-plan/intro",
)


@dataclass(frozen=True, slots=True)
class TokenPriceTier:
    input_per_million: float
    cache_read_per_million: float
    output_per_million: float
    max_input_tokens: int | None = None

    def contains(self, input_tokens: int) -> bool:
        return self.max_input_tokens is None or input_tokens <= self.max_input_tokens


@dataclass(frozen=True, slots=True)
class ModelTokenPrice:
    provider: str
    model: str
    billing_origin: BillingOrigin
    currency: CostCurrency
    tiers: tuple[TokenPriceTier, ...]
    catalog_version: str
    source_urls: tuple[str, ...]
    cost_scope: CostScope = COST_SCOPE

    def estimate(
        self,
        *,
        input_tokens: int,
        cache_read_input_tokens: int | None,
        output_tokens: int,
    ) -> float | None:
        if (
            cache_read_input_tokens is None
            or cache_read_input_tokens < 0
            or cache_read_input_tokens > input_tokens
        ):
            return None
        tier = next((item for item in self.tiers if item.contains(input_tokens)), None)
        if tier is None:
            return None
        uncached_input_tokens = input_tokens - cache_read_input_tokens
        return (
            uncached_input_tokens * tier.input_per_million
            + cache_read_input_tokens * tier.cache_read_per_million
            + output_tokens * tier.output_per_million
        ) / 1_000_000

    def estimate_usd(
        self,
        *,
        input_tokens: int,
        cache_read_input_tokens: int | None,
        output_tokens: int,
    ) -> float | None:
        """Return an amount only for a native USD catalog; never apply FX."""

        if self.currency != "USD":
            return None
        return self.estimate(
            input_tokens=input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            output_tokens=output_tokens,
        )


def _price(
    model: str,
    *,
    billing_origin: BillingOrigin,
    currency: CostCurrency,
    catalog_version: str,
    source_urls: tuple[str, ...],
    input_per_million: float,
    cache_read_per_million: float,
    output_per_million: float,
) -> ModelTokenPrice:
    return ModelTokenPrice(
        provider="minimax",
        model=model,
        billing_origin=billing_origin,
        currency=currency,
        tiers=(
            TokenPriceTier(
                input_per_million=input_per_million,
                cache_read_per_million=cache_read_per_million,
                output_per_million=output_per_million,
            ),
        ),
        catalog_version=catalog_version,
        source_urls=source_urls,
    )


# These are independent official catalogs.  Values are maintained in the
# currency published by each source; no exchange-rate conversion is applied.
MINIMAX_GLOBAL_PAYGO_PRICES: dict[str, ModelTokenPrice] = {
    "MiniMax-M3": ModelTokenPrice(
        provider="minimax",
        model="MiniMax-M3",
        billing_origin=BillingOrigin.MINIMAX_GLOBAL_PAYGO,
        currency="USD",
        tiers=(
            TokenPriceTier(
                input_per_million=0.3,
                cache_read_per_million=0.06,
                output_per_million=1.2,
                max_input_tokens=512_000,
            ),
            TokenPriceTier(
                input_per_million=0.6,
                cache_read_per_million=0.12,
                output_per_million=2.4,
                max_input_tokens=1_000_000,
            ),
        ),
        catalog_version=MINIMAX_GLOBAL_PAYGO_CATALOG_VERSION,
        source_urls=MINIMAX_GLOBAL_PAYGO_SOURCE_URLS,
    ),
    "MiniMax-M2.7": _price(
        "MiniMax-M2.7",
        billing_origin=BillingOrigin.MINIMAX_GLOBAL_PAYGO,
        currency="USD",
        catalog_version=MINIMAX_GLOBAL_PAYGO_CATALOG_VERSION,
        source_urls=MINIMAX_GLOBAL_PAYGO_SOURCE_URLS,
        input_per_million=0.3,
        cache_read_per_million=0.06,
        output_per_million=1.2,
    ),
    "MiniMax-M2.7-highspeed": _price(
        "MiniMax-M2.7-highspeed",
        billing_origin=BillingOrigin.MINIMAX_GLOBAL_PAYGO,
        currency="USD",
        catalog_version=MINIMAX_GLOBAL_PAYGO_CATALOG_VERSION,
        source_urls=MINIMAX_GLOBAL_PAYGO_SOURCE_URLS,
        input_per_million=0.6,
        cache_read_per_million=0.06,
        output_per_million=2.4,
    ),
    "MiniMax-M2.5": _price(
        "MiniMax-M2.5",
        billing_origin=BillingOrigin.MINIMAX_GLOBAL_PAYGO,
        currency="USD",
        catalog_version=MINIMAX_GLOBAL_PAYGO_CATALOG_VERSION,
        source_urls=MINIMAX_GLOBAL_PAYGO_SOURCE_URLS,
        input_per_million=0.3,
        cache_read_per_million=0.03,
        output_per_million=1.2,
    ),
    "MiniMax-M2.5-highspeed": _price(
        "MiniMax-M2.5-highspeed",
        billing_origin=BillingOrigin.MINIMAX_GLOBAL_PAYGO,
        currency="USD",
        catalog_version=MINIMAX_GLOBAL_PAYGO_CATALOG_VERSION,
        source_urls=MINIMAX_GLOBAL_PAYGO_SOURCE_URLS,
        input_per_million=0.6,
        cache_read_per_million=0.03,
        output_per_million=2.4,
    ),
    "MiniMax-M2.1": _price(
        "MiniMax-M2.1",
        billing_origin=BillingOrigin.MINIMAX_GLOBAL_PAYGO,
        currency="USD",
        catalog_version=MINIMAX_GLOBAL_PAYGO_CATALOG_VERSION,
        source_urls=MINIMAX_GLOBAL_PAYGO_SOURCE_URLS,
        input_per_million=0.3,
        cache_read_per_million=0.03,
        output_per_million=1.2,
    ),
    "MiniMax-M2.1-highspeed": _price(
        "MiniMax-M2.1-highspeed",
        billing_origin=BillingOrigin.MINIMAX_GLOBAL_PAYGO,
        currency="USD",
        catalog_version=MINIMAX_GLOBAL_PAYGO_CATALOG_VERSION,
        source_urls=MINIMAX_GLOBAL_PAYGO_SOURCE_URLS,
        input_per_million=0.6,
        cache_read_per_million=0.03,
        output_per_million=2.4,
    ),
    "MiniMax-M2": _price(
        "MiniMax-M2",
        billing_origin=BillingOrigin.MINIMAX_GLOBAL_PAYGO,
        currency="USD",
        catalog_version=MINIMAX_GLOBAL_PAYGO_CATALOG_VERSION,
        source_urls=MINIMAX_GLOBAL_PAYGO_SOURCE_URLS,
        input_per_million=0.3,
        cache_read_per_million=0.03,
        output_per_million=1.2,
    ),
}

MINIMAX_CN_PAYGO_PRICES: dict[str, ModelTokenPrice] = {
    "MiniMax-M3": ModelTokenPrice(
        provider="minimax",
        model="MiniMax-M3",
        billing_origin=BillingOrigin.MINIMAX_CN_PAYGO,
        currency="CNY",
        tiers=(
            TokenPriceTier(
                input_per_million=2.1,
                cache_read_per_million=0.42,
                output_per_million=8.4,
                max_input_tokens=512_000,
            ),
            TokenPriceTier(
                input_per_million=4.2,
                cache_read_per_million=0.84,
                output_per_million=16.8,
                max_input_tokens=1_000_000,
            ),
        ),
        catalog_version=MINIMAX_CN_PAYGO_CATALOG_VERSION,
        source_urls=MINIMAX_CN_PAYGO_SOURCE_URLS,
    ),
    "MiniMax-M2.7": _price(
        "MiniMax-M2.7",
        billing_origin=BillingOrigin.MINIMAX_CN_PAYGO,
        currency="CNY",
        catalog_version=MINIMAX_CN_PAYGO_CATALOG_VERSION,
        source_urls=MINIMAX_CN_PAYGO_SOURCE_URLS,
        input_per_million=2.1,
        cache_read_per_million=0.42,
        output_per_million=8.4,
    ),
    "MiniMax-M2.7-highspeed": _price(
        "MiniMax-M2.7-highspeed",
        billing_origin=BillingOrigin.MINIMAX_CN_PAYGO,
        currency="CNY",
        catalog_version=MINIMAX_CN_PAYGO_CATALOG_VERSION,
        source_urls=MINIMAX_CN_PAYGO_SOURCE_URLS,
        input_per_million=4.2,
        cache_read_per_million=0.42,
        output_per_million=16.8,
    ),
    "MiniMax-M2.5": _price(
        "MiniMax-M2.5",
        billing_origin=BillingOrigin.MINIMAX_CN_PAYGO,
        currency="CNY",
        catalog_version=MINIMAX_CN_PAYGO_CATALOG_VERSION,
        source_urls=MINIMAX_CN_PAYGO_SOURCE_URLS,
        input_per_million=2.1,
        cache_read_per_million=0.21,
        output_per_million=8.4,
    ),
    "MiniMax-M2.5-highspeed": _price(
        "MiniMax-M2.5-highspeed",
        billing_origin=BillingOrigin.MINIMAX_CN_PAYGO,
        currency="CNY",
        catalog_version=MINIMAX_CN_PAYGO_CATALOG_VERSION,
        source_urls=MINIMAX_CN_PAYGO_SOURCE_URLS,
        input_per_million=4.2,
        cache_read_per_million=0.21,
        output_per_million=16.8,
    ),
    "MiniMax-M2.1": _price(
        "MiniMax-M2.1",
        billing_origin=BillingOrigin.MINIMAX_CN_PAYGO,
        currency="CNY",
        catalog_version=MINIMAX_CN_PAYGO_CATALOG_VERSION,
        source_urls=MINIMAX_CN_PAYGO_SOURCE_URLS,
        input_per_million=2.1,
        cache_read_per_million=0.21,
        output_per_million=8.4,
    ),
    "MiniMax-M2.1-highspeed": _price(
        "MiniMax-M2.1-highspeed",
        billing_origin=BillingOrigin.MINIMAX_CN_PAYGO,
        currency="CNY",
        catalog_version=MINIMAX_CN_PAYGO_CATALOG_VERSION,
        source_urls=MINIMAX_CN_PAYGO_SOURCE_URLS,
        input_per_million=4.2,
        cache_read_per_million=0.21,
        output_per_million=16.8,
    ),
    "MiniMax-M2": _price(
        "MiniMax-M2",
        billing_origin=BillingOrigin.MINIMAX_CN_PAYGO,
        currency="CNY",
        catalog_version=MINIMAX_CN_PAYGO_CATALOG_VERSION,
        source_urls=MINIMAX_CN_PAYGO_SOURCE_URLS,
        input_per_million=2.1,
        cache_read_per_million=0.21,
        output_per_million=8.4,
    ),
}


def resolve_token_price(
    *,
    provider: str,
    model: str,
    billing_origin: BillingOrigin | str | None,
) -> ModelTokenPrice | None:
    """Resolve only an explicitly confirmed pay-as-you-go catalog entry."""

    if provider != "minimax" or billing_origin is None:
        return None
    try:
        origin = BillingOrigin(billing_origin)
    except ValueError:
        return None
    if origin is BillingOrigin.MINIMAX_GLOBAL_PAYGO:
        return MINIMAX_GLOBAL_PAYGO_PRICES.get(model)
    if origin is BillingOrigin.MINIMAX_CN_PAYGO:
        return MINIMAX_CN_PAYGO_PRICES.get(model)
    # Token Plan and Credits are request/quota/subscription products, not the
    # token-price catalogs above.  Their per-Run monetary cost stays unknown.
    return None
