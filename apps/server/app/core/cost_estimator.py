import json
import math
from dataclasses import dataclass
from typing import Any, Mapping


LOCAL_ZERO_COST_PROVIDERS = {
    "cosyvoice3",
    "local",
    "local_whisper",
    "mock",
    "none",
    "ollama",
}

# Public list prices (USD per 1M tokens) used only for on-screen estimation.
# These change more often than code, so COST_PRICE_TABLE_JSON overrides them.
# Numbers are vendor list prices, not a guarantee of billed amounts; the panel
# always labels them as estimates.
DEFAULT_PRICE_TABLE = {
    "vertex_ai:gemini-2.5-flash": {"input_per_million": 0.30, "output_per_million": 2.50},
    "gemini:gemini-2.5-flash": {"input_per_million": 0.30, "output_per_million": 2.50},
    # Common China-region OpenAI-compatible models (DashScope/Qwen list prices,
    # CNY converted at ~7.2). The China provider example ships qwen-plus, so
    # without these the cost panel would show $0 despite real spend.
    "openai_compatible:qwen-plus": {"input_per_million": 0.11, "output_per_million": 0.28},
    "openai_compatible:qwen-turbo": {"input_per_million": 0.04, "output_per_million": 0.08},
    "openai_compatible:qwen-max": {"input_per_million": 0.34, "output_per_million": 1.36},
    "openai_compatible:qwen-vl-plus": {"input_per_million": 0.21, "output_per_million": 0.21},
    # Generic OpenAI-style reference points for the common case.
    "openai_compatible:gpt-4o": {"input_per_million": 2.50, "output_per_million": 10.00},
    "openai_compatible:gpt-4o-mini": {"input_per_million": 0.15, "output_per_million": 0.60},
}

# Last-resort rate when token usage is known but no model price is configured.
# Deliberately conservative (a mid-range small-model price) so the panel shows a
# non-zero, honest estimate instead of a misleading $0. Tagged so the UI/logs
# can tell it apart from a real configured price.
GENERIC_FALLBACK_RATE_PER_MILLION = (0.20, 0.60)


@dataclass(frozen=True)
class CostEstimate:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    source: str
    price_source: str | None = None


@dataclass(frozen=True)
class _PriceRate:
    input_per_million: float
    output_per_million: float
    source: str


class CostEstimator:
    """Estimate provider token usage and USD cost from raw response metadata.

    Real provider usage wins over local text fallback. Price tables are intentionally
    externalized because public model pricing changes more often than backend code.
    """

    def __init__(
        self,
        price_table_json: str | None = None,
        price_table: Mapping[str, Any] | None = None,
    ) -> None:
        self._price_table: dict[str, _PriceRate] = {}
        self._price_table.update(_normalize_price_table(DEFAULT_PRICE_TABLE, "builtin-gemini-2.5-flash-2026-06"))
        if price_table:
            self._price_table.update(_normalize_price_table(price_table, "provided"))
        if price_table_json:
            self._price_table.update(_normalize_price_table(_parse_price_json(price_table_json), "env"))

    @classmethod
    def from_settings(cls, settings: Any) -> "CostEstimator":
        return cls(price_table_json=getattr(settings, "cost_price_table_json", ""))

    def estimate(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        raw: Any = None,
        input_text: Any = None,
        output_text: Any = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> CostEstimate:
        resolved_provider = _normalized_provider(provider or _string_field(raw, "provider"))
        resolved_model = str(model or _string_field(raw, "model") or "")

        usage_tokens = _usage_tokens_from_raw(raw)
        if usage_tokens is not None:
            estimated_input_tokens, estimated_output_tokens = usage_tokens
            source = "usage"
        elif input_tokens is not None or output_tokens is not None:
            estimated_input_tokens = _safe_int(input_tokens)
            estimated_output_tokens = _safe_int(output_tokens)
            source = "explicit"
        else:
            estimated_input_tokens = _estimate_text_tokens(input_text)
            estimated_output_tokens = _estimate_text_tokens(output_text)
            source = "fallback"

        rate = self._price_for(resolved_provider, resolved_model)
        cost_usd = None
        price_source = None
        if rate is not None:
            cost_usd = (
                estimated_input_tokens * rate.input_per_million
                + estimated_output_tokens * rate.output_per_million
            ) / 1_000_000
            price_source = rate.source

        return CostEstimate(
            provider=resolved_provider,
            model=resolved_model,
            input_tokens=estimated_input_tokens,
            output_tokens=estimated_output_tokens,
            cost_usd=cost_usd,
            source=source,
            price_source=price_source,
        )

    def _price_for(self, provider: str, model: str) -> _PriceRate | None:
        if provider in LOCAL_ZERO_COST_PROVIDERS:
            return _PriceRate(input_per_million=0.0, output_per_million=0.0, source="local-zero")

        provider_key = provider.lower()
        model_key = model.lower()
        candidates = [
            f"{provider_key}:{model_key}" if provider_key and model_key else "",
            model_key,
            f"{provider_key}:*" if provider_key else "",
            provider_key,
            "*",
        ]
        for key in candidates:
            if key and key in self._price_table:
                return self._price_table[key]
        # Known cloud provider with no configured price: fall back to a
        # conservative generic rate so the panel reports an honest non-zero
        # estimate rather than a misleading $0. Tagged distinctly.
        if provider_key:
            generic_input, generic_output = GENERIC_FALLBACK_RATE_PER_MILLION
            return _PriceRate(
                input_per_million=generic_input,
                output_per_million=generic_output,
                source="generic-fallback",
            )
        return None


def _parse_price_json(price_table_json: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(price_table_json)
    except json.JSONDecodeError as exc:
        raise ValueError("COST_PRICE_TABLE_JSON must be valid JSON.") from exc
    if not isinstance(parsed, Mapping):
        raise ValueError("COST_PRICE_TABLE_JSON must be a JSON object.")
    prices = parsed.get("prices")
    if isinstance(prices, Mapping):
        return prices
    return parsed


def _normalize_price_table(raw_table: Mapping[str, Any], source: str) -> dict[str, _PriceRate]:
    table: dict[str, _PriceRate] = {}
    for raw_key, raw_value in raw_table.items():
        key = str(raw_key).strip().lower()
        if not key:
            continue
        if isinstance(raw_value, Mapping) and _looks_like_price(raw_value):
            table[key] = _price_rate(raw_value, source)
            continue
        if isinstance(raw_value, Mapping):
            for model, nested_value in raw_value.items():
                if isinstance(nested_value, Mapping) and _looks_like_price(nested_value):
                    table[f"{key}:{str(model).strip().lower()}"] = _price_rate(
                        nested_value,
                        source,
                    )
    return table


def _looks_like_price(value: Mapping[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "input",
            "input_per_1k",
            "input_per_1m_tokens",
            "input_per_million",
            "input_usd_per_million",
            "input_cost_per_token",
            "output",
            "output_per_1k",
            "output_per_1m_tokens",
            "output_per_million",
            "output_usd_per_million",
            "output_cost_per_token",
            "prompt",
            "prompt_per_1k",
            "prompt_per_million",
            "prompt_cost_per_token",
            "completion",
            "completion_per_1k",
            "completion_per_million",
            "completion_cost_per_token",
        )
    )


def _price_rate(value: Mapping[str, Any], source: str) -> _PriceRate:
    input_per_million = _price_value(
        value,
        (
            "input_per_million",
            "input_per_1m_tokens",
            "input_usd_per_million",
            "prompt_per_million",
            "prompt_per_1m_tokens",
            "input",
            "prompt",
        ),
    )
    output_per_million = _price_value(
        value,
        (
            "output_per_million",
            "output_per_1m_tokens",
            "output_usd_per_million",
            "completion_per_million",
            "completion_per_1m_tokens",
            "output",
            "completion",
        ),
    )

    input_per_1k = _price_value(value, ("input_per_1k", "prompt_per_1k"), default=None)
    output_per_1k = _price_value(value, ("output_per_1k", "completion_per_1k"), default=None)
    if input_per_1k is not None:
        input_per_million = input_per_1k * 1000
    if output_per_1k is not None:
        output_per_million = output_per_1k * 1000

    input_per_token = _price_value(
        value,
        ("input_cost_per_token", "prompt_cost_per_token"),
        default=None,
    )
    output_per_token = _price_value(
        value,
        ("output_cost_per_token", "completion_cost_per_token"),
        default=None,
    )
    if input_per_token is not None:
        input_per_million = input_per_token * 1_000_000
    if output_per_token is not None:
        output_per_million = output_per_token * 1_000_000
    return _PriceRate(
        input_per_million=max(0.0, input_per_million),
        output_per_million=max(0.0, output_per_million),
        source=source,
    )


def _price_value(
    value: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    default: float | None = 0.0,
) -> float | None:
    for key in keys:
        raw = value.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return default


def _usage_tokens_from_raw(raw: Any) -> tuple[int, int] | None:
    if raw is None:
        return None
    for key in (
        "usage",
        "usage_metadata",
        "usageMetadata",
        "aggregated_usage",
        "aggregatedUsage",
        "live_usage",
        "live_usage_metadata",
        "liveUsageMetadata",
    ):
        usage = _get_field(raw, key)
        tokens = _usage_tokens(usage)
        if tokens is not None:
            return tokens
    for key in (
        "aggregated_raw",
        "aggregatedRaw",
        "chunks",
        "events",
        "messages",
        "responses",
        "stream",
        "stream_chunks",
        "streamChunks",
    ):
        stream = _get_field(raw, key)
        tokens = _usage_tokens(stream)
        if tokens is not None:
            return tokens
    return _usage_tokens(raw)


def _usage_tokens(usage: Any) -> tuple[int, int] | None:
    if usage is None:
        return None
    if isinstance(usage, list | tuple):
        latest_tokens: tuple[int, int] | None = None
        for item in usage:
            item_tokens = _usage_tokens_from_raw(item)
            if item_tokens is not None:
                latest_tokens = item_tokens
        return latest_tokens

    input_tokens = _first_int(
        usage,
        (
            "prompt_tokens",
            "input_tokens",
            "promptTokenCount",
            "prompt_token_count",
            "inputTokenCount",
            "input_token_count",
        ),
    )
    output_tokens = _first_int(
        usage,
        (
            "completion_tokens",
            "output_tokens",
            "candidatesTokenCount",
            "candidates_token_count",
            "responseTokenCount",
            "response_token_count",
            "outputTokenCount",
            "output_token_count",
        ),
    )
    total_tokens = _first_int(
        usage,
        (
            "total_tokens",
            "totalTokenCount",
            "total_token_count",
        ),
    )

    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None
    if input_tokens is None:
        input_tokens = max(0, total_tokens - output_tokens) if total_tokens and output_tokens else 0
    if output_tokens is None:
        output_tokens = max(0, total_tokens - input_tokens) if total_tokens else 0
    if total_tokens is not None and input_tokens == 0 and output_tokens == 0:
        input_tokens = total_tokens
    return max(0, input_tokens), max(0, output_tokens)


def _first_int(value: Any, names: tuple[str, ...]) -> int | None:
    for name in names:
        raw = _get_field(value, name)
        parsed = _optional_int(raw)
        if parsed is not None:
            return parsed
    return None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    parsed = _optional_int(value)
    return parsed if parsed is not None else 0


def _estimate_text_tokens(value: Any) -> int:
    text = _text_content(value)
    char_count = sum(1 for char in text if not char.isspace())
    if char_count == 0:
        return 0
    return max(1, math.ceil(char_count * 1.1))


def _text_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        chunks = [_text_content(item) for item in value.values()]
        return " ".join(chunk for chunk in chunks if chunk)
    if isinstance(value, list | tuple):
        chunks = [_text_content(item) for item in value]
        return " ".join(chunk for chunk in chunks if chunk)
    return str(value)


def _string_field(value: Any, name: str) -> str:
    field = _get_field(value, name)
    return str(field) if field is not None else ""


def _get_field(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _normalized_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized == "vertex":
        return "vertex_ai"
    return normalized
