SENSITIVE_EVENT_KEYS = {"data_base64", "audio_base64"}


def scrub_payload(payload: dict) -> dict:
    cleaned = dict(payload)
    for key in SENSITIVE_EVENT_KEYS:
        if key in cleaned:
            cleaned[key] = "<redacted>"
    return cleaned

