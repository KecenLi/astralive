#!/usr/bin/env python3
"""Generate deterministic MODVII fake microphone WAV fixtures with noise beds."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import struct
import sys
import wave
from pathlib import Path
from typing import Callable


TARGET_RATE = 16000
PROFILES = ("quiet", "low_noise", "white_noise", "fan_low", "keyboard_bursts", "low_voice")
PROFILE_SEEDS = {
    "quiet": 0x4D4F4401,
    "low_noise": 0x4D4F4402,
    "white_noise": 0x4D4F4403,
    "fan_low": 0x4D4F4404,
    "keyboard_bursts": 0x4D4F4405,
    "low_voice": 0x4D4F4406,
}


def pcm16_samples(audio_bytes: bytes) -> list[int]:
    sample_count = len(audio_bytes) // 2
    if sample_count <= 0:
        return []
    return list(struct.unpack("<" + "h" * sample_count, audio_bytes[: sample_count * 2]))


def pack_pcm16(samples: list[int]) -> bytes:
    if not samples:
        return b""
    return struct.pack("<" + "h" * len(samples), *samples)


def clamp_int16(value: float | int) -> int:
    return max(-32768, min(32767, int(round(value))))


def resample(samples: list[int], source_rate: int, target_rate: int) -> list[int]:
    if source_rate == target_rate:
        return samples
    if not samples:
        return []
    target_count = max(1, int(len(samples) * target_rate / source_rate))
    ratio = source_rate / target_rate
    output: list[int] = []
    for index in range(target_count):
        position = index * ratio
        left_index = min(int(math.floor(position)), len(samples) - 1)
        right_index = min(left_index + 1, len(samples) - 1)
        fraction = position - left_index
        value = samples[left_index] + (samples[right_index] - samples[left_index]) * fraction
        output.append(clamp_int16(value))
    return output


def mix_channels(samples: list[int], channels: int) -> list[int]:
    if channels <= 1:
        return samples
    mixed: list[int] = []
    for index in range(0, len(samples), channels):
        frame = samples[index : index + channels]
        if frame:
            mixed.append(clamp_int16(sum(frame) / len(frame)))
    return mixed


def read_wav(path: Path, target_rate: int = TARGET_RATE) -> tuple[list[int], dict]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        source_rate = wav.getframerate()
        frame_count = wav.getnframes()
        frames = wav.readframes(frame_count)
    if sample_width != 2:
        raise RuntimeError(f"WAV must be PCM16, got sample width {sample_width}: {path}")
    samples = resample(mix_channels(pcm16_samples(frames), channels), source_rate, target_rate)
    return samples, {
        "path": str(path),
        "sample_rate": target_rate,
        "source_sample_rate": source_rate,
        "channels": 1,
        "source_channels": channels,
        "duration_ms": round(len(samples) / target_rate * 1000),
        "bytes": path.stat().st_size if path.exists() else len(frames),
    }


def read_wav_bytes(audio_bytes: bytes, target_rate: int = TARGET_RATE) -> tuple[list[int], dict]:
    import io

    with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        source_rate = wav.getframerate()
        frame_count = wav.getnframes()
        frames = wav.readframes(frame_count)
    if sample_width != 2:
        raise RuntimeError(f"WAV bytes must be PCM16, got sample width {sample_width}.")
    samples = resample(mix_channels(pcm16_samples(frames), channels), source_rate, target_rate)
    return samples, {
        "sample_rate": target_rate,
        "source_sample_rate": source_rate,
        "channels": 1,
        "source_channels": channels,
        "duration_ms": round(len(samples) / target_rate * 1000),
        "bytes": len(audio_bytes),
    }


def write_wav(path: Path, samples: list[int], sample_rate: int = TARGET_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pack_pcm16(samples))


def normalize(samples: list[int], target_peak: float = 0.72) -> list[int]:
    peak = max((abs(value) for value in samples), default=0)
    if peak <= 0:
        return samples
    gain = min(6.0, (32767 * target_peak) / peak)
    return [clamp_int16(value * gain) for value in samples]


def deterministic_rng(seed: int) -> Callable[[], float]:
    state = seed & 0xFFFFFFFF

    def next_value() -> float:
        nonlocal state
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= state >> 17
        state ^= (state << 5) & 0xFFFFFFFF
        state &= 0xFFFFFFFF
        return (state / 0xFFFFFFFF) * 2 - 1

    return next_value


def envelope(index: int, total: int, attack: float, release: float, rate: int) -> float:
    if total <= 0:
        return 0.0
    t = index / rate
    remaining = (total - index) / rate
    return max(0.0, min(1.0, t / attack if attack else 1.0, remaining / release if release else 1.0))


def synthetic_speech_samples(text: str, sample_rate: int = TARGET_RATE) -> list[int]:
    # This fallback is speech-like enough for transport/VAD checks, but not a
    # substitute for ASR-quality speech. Prefer --generate-tts for real API runs.
    duration = max(4.2, min(10.0, 0.18 * len(text) + 1.2))
    total = int(sample_rate * duration)
    rng = deterministic_rng(0xC071CE)
    samples: list[int] = []
    for index in range(total):
        t = index / sample_rate
        syllable = 0.55 + 0.45 * max(0.0, math.sin(2 * math.pi * 4.1 * t))
        wobble = 28 * math.sin(2 * math.pi * 3.0 * t) + 11 * rng()
        base = 180 + wobble
        formants = (
            math.sin(2 * math.pi * base * t) * 0.42
            + math.sin(2 * math.pi * (base * 2.05) * t) * 0.22
            + math.sin(2 * math.pi * (base * 3.6) * t) * 0.09
        )
        gate = envelope(index, total, 0.08, 0.18, sample_rate)
        samples.append(clamp_int16(formants * syllable * gate * 0.42 * 32767))
    return samples


def profile_noise(profile: str, sample_rate: int, total_samples: int) -> list[int]:
    rng = deterministic_rng(PROFILE_SEEDS[profile])
    noise: list[int] = []
    click_events = set()
    if profile == "keyboard_bursts":
        for burst_start_ms in range(900, int(total_samples / sample_rate * 1000), 700):
            for _ in range(3 + int(abs(rng()) * 5)):
                click_index = int((burst_start_ms + abs(rng()) * 240) / 1000 * sample_rate)
                click_events.add(click_index)

    for index in range(total_samples):
        t = index / sample_rate
        value = 0.0
        if profile == "quiet":
            value = rng() * 0.0015
        elif profile == "low_noise":
            value = rng() * 0.006 + math.sin(2 * math.pi * 60 * t) * 0.0014
        elif profile == "white_noise":
            value = rng() * 0.026
        elif profile == "fan_low":
            slow = 0.7 + 0.3 * math.sin(2 * math.pi * 0.45 * t)
            hum = math.sin(2 * math.pi * 96 * t) * 0.006 + math.sin(2 * math.pi * 192 * t) * 0.003
            value = hum + rng() * 0.009 * slow
        elif profile == "keyboard_bursts":
            value = rng() * 0.004
            for click_index in range(index - 5, index + 1):
                if click_index in click_events:
                    age = index - click_index
                    value += math.exp(-age / 2.0) * (0.20 + abs(rng()) * 0.08) * (1 if rng() >= 0 else -1)
        elif profile == "low_voice":
            mumble = (
                math.sin(2 * math.pi * (125 + 10 * math.sin(2 * math.pi * 0.7 * t)) * t) * 0.015
                + math.sin(2 * math.pi * 245 * t) * 0.006
            )
            gate = 0.35 + 0.65 * max(0.0, math.sin(2 * math.pi * 2.2 * t + 0.6))
            value = rng() * 0.004 + mumble * gate
        noise.append(clamp_int16(value * 32767))
    return noise


def mix_with_noise(
    speech: list[int],
    profile: str,
    sample_rate: int,
    lead_seconds: float,
    tail_seconds: float,
    speech_gain: float,
) -> tuple[list[int], dict]:
    lead_samples = max(0, int(lead_seconds * sample_rate))
    tail_samples = max(0, int(tail_seconds * sample_rate))
    total_samples = lead_samples + len(speech) + tail_samples
    noise = profile_noise(profile, sample_rate, total_samples)
    output = noise[:]
    for index, sample in enumerate(speech):
        output[lead_samples + index] = clamp_int16(output[lead_samples + index] + sample * speech_gain)
    return output, {
        "lead_noise_ms": round(lead_samples / sample_rate * 1000),
        "tail_noise_ms": round(tail_samples / sample_rate * 1000),
        "speech_start_ms": round(lead_samples / sample_rate * 1000),
        "speech_end_ms": round((lead_samples + len(speech)) / sample_rate * 1000),
        "duration_ms": round(total_samples / sample_rate * 1000),
    }


async def synthesize_tts(text: str, target_rate: int, cache_path: Path | None) -> tuple[list[int], dict]:
    sys.path.insert(0, str(Path.cwd()))
    from app.config import get_settings
    from app.contracts.model_io import TTSInput
    from app.providers.registry import ProviderRegistry

    settings = get_settings()
    provider = ProviderRegistry(settings).tts()
    try:
        result = await provider.synthesize(TTSInput(text=text))
    finally:
        close = getattr(provider, "close", None)
        if close is not None:
            maybe = close()
            if hasattr(maybe, "__await__"):
                await maybe
    if not result.audio_base64:
        raise RuntimeError("TTS returned no audio data for MODVII fake microphone corpus.")

    audio_bytes = base64.b64decode(result.audio_base64)
    encoding = (result.encoding or "").lower()
    mime = (result.mime or "").lower()
    if encoding == "wav" or "wav" in mime or audio_bytes[:4] == b"RIFF":
        samples, source = read_wav_bytes(audio_bytes, target_rate)
    elif encoding == "pcm_s16le":
        samples = resample(mix_channels(pcm16_samples(audio_bytes), int(result.channels or 1)), int(result.sample_rate or 24000), target_rate)
        source = {
            "sample_rate": target_rate,
            "source_sample_rate": int(result.sample_rate or 24000),
            "channels": 1,
            "source_channels": int(result.channels or 1),
            "duration_ms": round(len(samples) / target_rate * 1000),
            "bytes": len(audio_bytes),
        }
    else:
        raise RuntimeError(f"Unsupported TTS audio encoding for corpus generation: {result.encoding}")

    samples = normalize(samples)
    if cache_path:
        write_wav(cache_path, samples, target_rate)
    return samples, {
        "mode": "tts",
        "provider": getattr(provider, "provider_name", None) or getattr(settings, "tts_provider", "unknown"),
        "model": getattr(provider, "model", None) or source.get("model") or "unknown",
        "text": text,
        **source,
        **({"cache_path": str(cache_path)} if cache_path else {}),
    }


async def load_or_create_speech(args: argparse.Namespace) -> tuple[list[int], dict]:
    text = args.text or f"{args.wake_word}，{args.request_text}"
    speech_cache = Path(args.speech_cache) if args.speech_cache else None
    if args.source_wav:
        samples, source = read_wav(Path(args.source_wav), args.sample_rate)
        return normalize(samples), {"mode": "source-wav", "text": text, **source}
    if speech_cache and speech_cache.exists() and not args.refresh_speech_cache:
        samples, source = read_wav(speech_cache, args.sample_rate)
        return normalize(samples), {"mode": "speech-cache", "text": text, **source}
    if args.generate_tts:
        return await synthesize_tts(text, args.sample_rate, speech_cache)
    if args.allow_synthetic_tone:
        samples = synthetic_speech_samples(text, args.sample_rate)
        if speech_cache:
            write_wav(speech_cache, samples, args.sample_rate)
        return samples, {
            "mode": "synthetic-speechlike",
            "text": text,
            "sample_rate": args.sample_rate,
            "channels": 1,
            "duration_ms": round(len(samples) / args.sample_rate * 1000),
            "warning": "Synthetic speech-like audio is deterministic but is not an ASR-quality speech corpus.",
            **({"cache_path": str(speech_cache)} if speech_cache else {}),
        }
    raise RuntimeError(
        "No speech source available. Use --generate-tts, --source-wav, --speech-cache, "
        "or --allow-synthetic-tone."
    )


async def async_main() -> None:
    parser = argparse.ArgumentParser(description="Generate MODVII noisy fake microphone WAV fixtures.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--profile", required=True, choices=PROFILES)
    parser.add_argument("--text", default="")
    parser.add_argument("--wake-word", default="小七")
    parser.add_argument("--request-text", default="请简短介绍一下你现在能做什么。")
    parser.add_argument("--source-wav", default="")
    parser.add_argument("--speech-cache", default="")
    parser.add_argument("--refresh-speech-cache", action="store_true")
    parser.add_argument("--generate-tts", action="store_true")
    parser.add_argument("--allow-synthetic-tone", action="store_true")
    parser.add_argument("--lead-seconds", type=float, default=1.0)
    parser.add_argument("--tail-seconds", type=float, default=1.8)
    parser.add_argument("--speech-gain", type=float, default=0.92)
    parser.add_argument("--sample-rate", type=int, default=TARGET_RATE)
    parser.add_argument("--metadata-output", default="")
    args = parser.parse_args()

    if args.sample_rate != TARGET_RATE:
        raise RuntimeError("MODVII realtime fixtures must be generated at 16000 Hz.")

    output = Path(args.output)
    speech, speech_info = await load_or_create_speech(args)
    mixed, timing = mix_with_noise(
        speech,
        args.profile,
        args.sample_rate,
        max(0.0, args.lead_seconds),
        max(0.0, args.tail_seconds),
        max(0.0, min(1.8, args.speech_gain)),
    )
    write_wav(output, mixed, args.sample_rate)
    metadata = {
        "mode": "modvii-noisy-fake-mic",
        "path": str(output),
        "profile": args.profile,
        "wake_word": args.wake_word,
        "request_text": args.request_text,
        "text": args.text or f"{args.wake_word}，{args.request_text}",
        "sample_rate": args.sample_rate,
        "channels": 1,
        "bytes": output.stat().st_size,
        "speech": speech_info,
        **timing,
    }
    if args.metadata_output:
        Path(args.metadata_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.metadata_output).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False))


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
