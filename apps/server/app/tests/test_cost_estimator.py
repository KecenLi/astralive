import json

import pytest

from app.config import Settings
from app.core.cost_estimator import CostEstimator
from app.core.cost_meter import CostMeter


def test_openai_stream_final_usage_wins_without_delta_double_counting() -> None:
    estimator = CostEstimator(
        price_table_json=json.dumps(
            {
                "openai_compatible:gpt-stream": {
                    "input_per_million": 1.0,
                    "output_per_million": 10.0,
                }
            }
        )
    )

    estimate = estimator.estimate(
        raw={
            "provider": "openai_compatible",
            "model": "gpt-stream",
            "chunks": [
                {"choices": [{"delta": {"content": "first"}}]},
                {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
                {"usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18}},
            ],
        },
        input_text="fallback input should not be used" * 20,
        output_text="fallback output should not be used" * 20,
    )

    assert estimate.source == "usage"
    assert estimate.input_tokens == 12
    assert estimate.output_tokens == 6
    assert estimate.cost_usd == pytest.approx(0.000072)


def test_vertex_stream_final_usage_metadata_from_settings_price_table() -> None:
    settings = Settings(
        cost_price_table_json=json.dumps(
            {
                "vertex_ai": {
                    "gemini-stream": {
                        "input_per_million": 2.0,
                        "output_per_million": 4.0,
                    }
                }
            }
        )
    )
    estimator = CostEstimator.from_settings(settings)

    estimate = estimator.estimate(
        raw={
            "provider": "vertex_ai",
            "model": "gemini-stream",
            "stream_chunks": [
                {"candidates": [{"content": {"parts": [{"text": "delta"}]}}]},
                {
                    "usageMetadata": {
                        "promptTokenCount": 8,
                        "candidatesTokenCount": 3,
                        "totalTokenCount": 11,
                    }
                },
            ],
        },
        input_text="fallback input should not be used",
        output_text="fallback output should not be used",
    )

    assert estimate.source == "usage"
    assert estimate.input_tokens == 8
    assert estimate.output_tokens == 3
    assert estimate.cost_usd == pytest.approx(0.000028)


def test_gemini_live_usage_metadata_is_read_once() -> None:
    estimator = CostEstimator(
        price_table={
            "gemini:gemini-live": {
                "input_per_million": 3.0,
                "output_per_million": 9.0,
            }
        }
    )

    estimate = estimator.estimate(
        raw={
            "provider": "gemini",
            "model": "gemini-live",
            "usage_metadata": {
                "input_token_count": 7,
                "output_token_count": 4,
                "total_token_count": 11,
            },
        },
        input_text="fallback input should not be used",
        output_text="fallback output should not be used",
    )

    assert estimate.source == "usage"
    assert estimate.input_tokens == 7
    assert estimate.output_tokens == 4
    assert estimate.cost_usd == pytest.approx(0.000057)


def test_fallback_uses_text_length_when_usage_is_missing() -> None:
    estimator = CostEstimator(
        price_table={
            "openai_compatible:gpt-fallback": {
                "input_per_million": 1.0,
                "output_per_million": 1.0,
            }
        }
    )

    estimate = estimator.estimate(
        raw={"provider": "openai_compatible", "model": "gpt-fallback"},
        input_text="hello",
        output_text="你好",
    )

    assert estimate.source == "fallback"
    assert estimate.input_tokens > 0
    assert estimate.output_tokens > 0
    assert estimate.cost_usd is not None


@pytest.mark.parametrize("provider", ["mock", "ollama", "local_whisper", "cosyvoice3"])
def test_local_providers_are_zero_cost(provider: str) -> None:
    estimator = CostEstimator(
        price_table={
            f"{provider}:expensive": {
                "input_per_million": 999.0,
                "output_per_million": 999.0,
            }
        }
    )

    estimate = estimator.estimate(
        raw={
            "provider": provider,
            "model": "expensive",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 2000},
        }
    )

    assert estimate.source == "usage"
    assert estimate.input_tokens == 1000
    assert estimate.output_tokens == 2000
    assert estimate.cost_usd == 0.0
    assert estimate.price_source == "local-zero"


def test_cost_meter_add_estimate_accumulates_tokens_cost_and_call_type() -> None:
    estimate = CostEstimator(
        price_table={"openai_compatible:gpt-meter": {"input_per_million": 1.0, "output_per_million": 2.0}}
    ).estimate(
        raw={
            "provider": "openai_compatible",
            "model": "gpt-meter",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
    )

    meter = CostMeter()
    meter.add_estimate(estimate, call_type="llm")

    assert meter.llm_calls == 1
    assert meter.estimated_input_tokens == 100
    assert meter.estimated_output_tokens == 50
    assert meter.estimated_cost_usd == pytest.approx(0.0002)
