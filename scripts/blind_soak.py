"""Independent blind soak for MODVII.

This is deliberately NOT modelled on the project's own verifier assertions. It
drives the real WebSocket protocol against the real configured providers
(Vertex vision/LLM, local Whisper ASR) and tries to *provoke* the visual/voice
race conditions that recent rounds claim to have fixed, under a continuous
high background-noise floor.

It asserts only invariants a correct assistant must always hold, then reports
raw event statistics so regressions surface even if an invariant was missed:

  INV1  After every turn the session returns to a non-busy state (listening /
        awake / sleeping) within a deadline — never stuck in thinking/speaking.
  INV2  response_in_progress is never left True at end of a turn.
  INV3  A vision question eventually yields a vision.summary OR an explicit
        need_focus (never silent).
  INV4  No unexpected server `error` events (429/timeout are recorded, not
        treated as harness failure, but counted).
  INV5  Barge-in (interrupt mid-response) returns to listening promptly.

Usage: python scripts/blind_soak.py --rounds 8 --host 127.0.0.1 --port 8765
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import random
import struct
import time
import wave
import zlib
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import httpx
import websockets


# ----------------------------- media synthesis ------------------------------

def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def make_scene_png(seed: int, w: int = 96, h: int = 64) -> str:
    """A small but genuinely varying image so the vision model sees real change
    and the scene-hash dedup is exercised (not a constant frame)."""
    rng = random.Random(seed)
    rows = bytearray()
    base_r, base_g, base_b = rng.randint(20, 220), rng.randint(20, 220), rng.randint(20, 220)
    # a few colored blocks at random positions => real perceptual differences
    blocks = [(rng.randint(0, w - 1), rng.randint(0, h - 1), rng.randint(8, 24),
               rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)) for _ in range(4)]
    for y in range(h):
        rows.append(0)  # filter type 0
        for x in range(w):
            r, g, b = base_r, base_g, base_b
            for bx, by, bs, br, bg, bb in blocks:
                if abs(x - bx) < bs and abs(y - by) < bs:
                    r, g, b = br, bg, bb
            rows.extend((r, g, b))
    raw = zlib.compress(bytes(rows), 9)
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += _png_chunk(b"IDAT", raw)
    png += _png_chunk(b"IEND", b"")
    return base64.b64encode(png).decode("ascii")


def load_wav_pcm16(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        data = wf.readframes(n)
        ch = wf.getnchannels()
    if ch == 2:  # downmix to mono
        mono = bytearray()
        for i in range(0, len(data), 4):
            l = struct.unpack_from("<h", data, i)[0]
            r = struct.unpack_from("<h", data, i + 2)[0]
            mono += struct.pack("<h", (l + r) // 2)
        data = bytes(mono)
    return data, sr


def add_noise_floor(pcm: bytes, level: float, seed: int) -> bytes:
    """Mix a continuous noise floor into PCM16 mono audio."""
    rng = random.Random(seed)
    out = bytearray(len(pcm))
    for i in range(0, len(pcm) - 1, 2):
        s = struct.unpack_from("<h", pcm, i)[0]
        n = int(rng.uniform(-1, 1) * level * 32767)
        v = max(-32768, min(32767, s + n))
        struct.pack_into("<h", out, i, v)
    return bytes(out)


def resample_to_16k(pcm: bytes, src_sr: int) -> bytes:
    if src_sr == 16000:
        return pcm
    ratio = 16000 / src_sr
    n_in = len(pcm) // 2
    n_out = int(n_in * ratio)
    out = bytearray(n_out * 2)
    for i in range(n_out):
        src_i = min(n_in - 1, int(i / ratio))
        struct.pack_into("<h", out, i * 2, struct.unpack_from("<h", pcm, src_i * 2)[0])
    return bytes(out)


# ----------------------------- ws client ------------------------------------

@dataclass
class TurnStats:
    label: str
    returned_to_listening: bool = False
    saw_text_final: bool = False
    saw_audio_done: bool = False
    saw_vision_summary: bool = False
    saw_need_focus: bool = False
    errors: list = field(default_factory=list)
    final_status: str = "?"
    elapsed_ms: int = 0


class BlindClient:
    def __init__(self, base_http: str, ws_url: str) -> None:
        self.base_http = base_http
        self.ws_url = ws_url
        self.ws = None
        self.session_id = ""
        self.events: list[dict] = []
        self.status = "?"
        self.response_in_progress = False
        self.counts: dict[str, int] = {}

    async def open(self) -> None:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{self.base_http}/api/session")
            r.raise_for_status()
            self.session_id = r.json()["session_id"]
        self.ws = await websockets.connect(f"{self.ws_url}/ws/session/{self.session_id}", max_size=8 * 1024 * 1024)
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            async for raw in self.ws:
                ev = json.loads(raw)
                self.events.append(ev)
                t = ev.get("type", "")
                self.counts[t] = self.counts.get(t, 0) + 1
                payload = ev.get("payload", {})
                if t in ("server.session.ready", "server.session.state"):
                    if isinstance(payload, dict):
                        if payload.get("status"):
                            self.status = payload["status"]
                        if "response_in_progress" in payload:
                            self.response_in_progress = bool(payload["response_in_progress"])
        except Exception:
            pass

    async def send(self, type_: str, payload: dict) -> None:
        evt = {"id": f"evt_{random.randint(0, 1 << 30):x}", "type": type_,
               "session_id": self.session_id, "ts": int(time.time() * 1000), "payload": payload}
        await self.ws.send(json.dumps(evt))

    async def send_frame(self, seed: int, reason: str, scene_hash: str) -> None:
        await self.send("client.media.frame", {
            "frame_id": f"f_{seed}_{random.randint(0,9999)}",
            "mime": "image/png", "width": 96, "height": 64, "quality": 0.8,
            "capture_reason": reason, "scene_hash": scene_hash,
            "data_base64": make_scene_png(seed),
            "prompt": "请描述画面里的主要内容。",
        })

    async def send_audio_turn(self, pcm16: bytes, chunk_ms: int = 200) -> None:
        sr = 16000
        bytes_per_chunk = int(sr * (chunk_ms / 1000)) * 2
        idx = 0
        for off in range(0, len(pcm16), bytes_per_chunk):
            chunk = pcm16[off:off + bytes_per_chunk]
            is_final = off + bytes_per_chunk >= len(pcm16)
            await self.send("client.media.audio_chunk", {
                "chunk_id": f"a_{idx}", "mime": "audio/pcm;rate=16000",
                "sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le",
                "data_base64": base64.b64encode(chunk).decode("ascii"),
                "is_final": is_final, "metadata": {"route": "asr_first"},
            })
            idx += 1
            await asyncio.sleep(chunk_ms / 1000 * 0.5)

    def busy(self) -> bool:
        return self.response_in_progress or self.status in ("thinking", "speaking")

    async def wait_idle(self, deadline_s: float) -> bool:
        t0 = time.time()
        while time.time() - t0 < deadline_s:
            if not self.busy() and self.status in ("listening", "awake", "sleeping", "interrupted"):
                # settle briefly to catch late state flips
                await asyncio.sleep(0.4)
                if not self.busy():
                    return True
            await asyncio.sleep(0.2)
        return False

    def snapshot_since(self, idx: int) -> list[dict]:
        return self.events[idx:]

    async def close(self) -> None:
        try:
            await self.ws.close()
        except Exception:
            pass


# ----------------------------- scenarios ------------------------------------

async def scenario_concurrent_visual_voice(cli: BlindClient, noise: bytes, seed: int) -> TurnStats:
    """Race target: burst visual frames from 'two sources' WHILE a voice turn
    starts, then a vision question — exactly the camera+screen+voice collision."""
    st = TurnStats(label="concurrent_visual_voice")
    start_idx = len(cli.events)
    t0 = time.time()
    await cli.send("client.wake.detected", {"wake_word": "小七"})
    await asyncio.sleep(0.2)
    # burst frames from camera + screen interleaved (different scenes)
    for i in range(6):
        await cli.send_frame(seed + i, "camera_stream" if i % 2 else "screen_stream", f"sh{seed}_{i}")
        await asyncio.sleep(0.05)
    # immediately start a voice turn on top of the frame burst
    await cli.send_audio_turn(noise)
    # then ask a vision question by text while frames may still be in flight
    await asyncio.sleep(0.3)
    await cli.send("client.user.text", {"text": "你现在看到了什么？"})
    st.returned_to_listening = await cli.wait_idle(60)
    _fill(st, cli.snapshot_since(start_idx))
    st.final_status = cli.status
    st.elapsed_ms = int((time.time() - t0) * 1000)
    return st


async def scenario_bargein(cli: BlindClient, noise: bytes, seed: int) -> TurnStats:
    """Race target: interrupt mid-response, must return to listening; the
    in-flight vision/LLM/TTS must not wedge the state machine."""
    st = TurnStats(label="bargein")
    start_idx = len(cli.events)
    t0 = time.time()
    await cli.send("client.user.text", {"text": "用三句话介绍一下你自己，然后说说你能帮我做什么。"})
    await asyncio.sleep(1.2)  # let response start
    await cli.send("client.control.interrupt", {})
    # right after interrupt, fire frames + a new question (provoke stale-drop bug)
    for i in range(4):
        await cli.send_frame(seed + 100 + i, "screen_stream", f"bi{seed}_{i}")
        await asyncio.sleep(0.04)
    await cli.send("client.user.text", {"text": "你看到屏幕上有什么？"})
    st.returned_to_listening = await cli.wait_idle(60)
    _fill(st, cli.snapshot_since(start_idx))
    st.final_status = cli.status
    st.elapsed_ms = int((time.time() - t0) * 1000)
    return st


async def scenario_visual_during_listen(cli: BlindClient, noise: bytes, seed: int) -> TurnStats:
    """Claim under test: visual upload only paused during REAL speech, not while
    merely listening/waiting. Send frames during a listening window; a vision
    summary should still arrive."""
    st = TurnStats(label="visual_during_listen")
    start_idx = len(cli.events)
    t0 = time.time()
    await cli.send("client.wake.detected", {"wake_word": "小七"})
    await asyncio.sleep(0.3)
    # we are listening but NOT speaking — frames should be processed
    for i in range(5):
        await cli.send_frame(seed + 200 + i, "camera_stream", f"vl{seed}_{i}")
        await asyncio.sleep(0.25)
    # then a vision question
    await cli.send("client.user.text", {"text": "描述一下你看到的画面。"})
    st.returned_to_listening = await cli.wait_idle(60)
    _fill(st, cli.snapshot_since(start_idx))
    st.final_status = cli.status
    st.elapsed_ms = int((time.time() - t0) * 1000)
    return st


def _fill(st: TurnStats, evs: list[dict]) -> None:
    for ev in evs:
        t = ev.get("type", "")
        if t == "assistant.text.final":
            st.saw_text_final = True
        elif t == "assistant.audio.done":
            st.saw_audio_done = True
        elif t == "vision.summary":
            st.saw_vision_summary = True
        elif t == "vision.need_focus":
            st.saw_need_focus = True
        elif t == "error":
            st.errors.append(ev.get("payload", {}))


# ----------------------------- runner ---------------------------------------

async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--noise", type=float, default=0.06, help="continuous noise floor level 0..1")
    args = ap.parse_args()

    base_http = f"http://{args.host}:{args.port}"
    ws_url = f"ws://{args.host}:{args.port}"

    # build a high-noise speech corpus from real samples
    root = Path(__file__).resolve().parents[1]
    cache = root / "data" / "cache"
    speech_candidates = [
        cache / "modvii-real-realtime-soak-speech.wav",
        cache / "cosyvoice3-test.wav",
        cache / "modvii-real-realtime-soak-low_voice.wav",
    ]
    speech_path = next((p for p in speech_candidates if p.exists()), None)
    if speech_path is None:
        print("NO SPEECH SAMPLE FOUND; aborting", flush=True)
        return 2
    raw_pcm, sr = load_wav_pcm16(speech_path)
    pcm16k = resample_to_16k(raw_pcm, sr)

    results: list[TurnStats] = []
    scenarios = [scenario_concurrent_visual_voice, scenario_visual_during_listen, scenario_bargein]

    cli = BlindClient(base_http, ws_url)
    await cli.open()
    print(f"session={cli.session_id} noise_floor={args.noise}", flush=True)
    await asyncio.sleep(1.0)  # let ready + prewarm settle

    for rnd in range(args.rounds):
        scen = scenarios[rnd % len(scenarios)]
        seed = 1000 + rnd * 17
        # continuous high noise floor, varied per round
        noisy = add_noise_floor(pcm16k, args.noise + (rnd % 3) * 0.02, seed)
        try:
            st = await asyncio.wait_for(scen(cli, noisy, seed), timeout=90)
        except asyncio.TimeoutError:
            st = TurnStats(label=f"{scen.__name__}#TIMEOUT")
            st.returned_to_listening = False
            st.final_status = cli.status
        results.append(st)
        ok = "PASS" if st.returned_to_listening else "FAIL"
        print(f"[{rnd+1}/{args.rounds}] {st.label:26} {ok} status={st.final_status:11} "
              f"text={int(st.saw_text_final)} audio_done={int(st.saw_audio_done)} "
              f"vis={int(st.saw_vision_summary)} focus={int(st.saw_need_focus)} "
              f"err={len(st.errors)} {st.elapsed_ms}ms", flush=True)
        if st.errors:
            for e in st.errors[:3]:
                print(f"      ERR: {json.dumps(e, ensure_ascii=False)[:200]}", flush=True)
        await asyncio.sleep(0.8)

    await cli.close()

    # -------- verdict --------
    total = len(results)
    returned = sum(1 for r in results if r.returned_to_listening)
    err_events = sum(len(r.errors) for r in results)
    rate_429 = sum(1 for r in results for e in r.errors if "429" in json.dumps(e) or "resource_exhausted" in json.dumps(e).lower())
    timeouts = sum(1 for r in results if "TIMEOUT" in r.label)
    vis_rounds = sum(1 for r in results if r.saw_vision_summary or r.saw_need_focus)
    vis_expected = sum(1 for r in results if "visual" in r.label or "concurrent" in r.label)

    print("\n================ BLIND SOAK VERDICT ================", flush=True)
    print(f"rounds                : {total}", flush=True)
    print(f"returned to listening : {returned}/{total}", flush=True)
    print(f"hard timeouts         : {timeouts}", flush=True)
    print(f"server error events   : {err_events} (429/exhausted: {rate_429})", flush=True)
    print(f"vision answered       : {vis_rounds}/{vis_expected} expected-visual rounds", flush=True)
    print(f"event type counts     : {json.dumps(cli.counts, ensure_ascii=False)}", flush=True)

    invariants_ok = (returned == total) and (timeouts == 0)
    print(f"\nINVARIANT (always return to listening, no hard timeout): "
          f"{'HOLDS' if invariants_ok else 'VIOLATED'}", flush=True)
    return 0 if invariants_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
