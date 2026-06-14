from collections.abc import Mapping
from typing import Any


def raw_usage_payload(response: Any) -> dict:
    usage = _get_field(response, "usage")
    if usage is not None:
        return {"usage": to_plain_data(usage)}

    usage_metadata = _get_field(response, "usage_metadata")
    if usage_metadata is None:
        usage_metadata = _get_field(response, "usageMetadata")
    if usage_metadata is not None:
        return {"usage_metadata": to_plain_data(usage_metadata)}

    return {}


def to_plain_data(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): to_plain_data(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list | tuple):
        return [to_plain_data(item) for item in value if item is not None]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return to_plain_data(model_dump(by_alias=True, exclude_none=True))
        except TypeError:
            return to_plain_data(model_dump())

    if hasattr(value, "__dict__"):
        return {
            key: to_plain_data(item)
            for key, item in vars(value).items()
            if not key.startswith("_") and item is not None
        }

    return str(value)


def _get_field(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)
