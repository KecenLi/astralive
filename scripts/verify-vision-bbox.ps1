param(
    [int]$Runs = 5,
    [string]$Prompt = "Identify the main visible objects and return stable normalized 2D bboxes.",
    [string]$ImagePath = "",
    [string]$Provider = "",
    [switch]$SkipDependencySync
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = "."
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "common.ps1")

Import-DotEnvFile -Path (Join-Path $Root ".env")
Import-DotEnvFile -Path (Join-Path $Root "apps\server\.env")
if ($Provider) {
    $env:VISION_PROVIDER = $Provider
}

$Uv = Resolve-Uv
$Python = Resolve-Python
if (-not $Uv -and -not $Python) {
    throw "Python 3.11+ or uv is required."
}

if ($Uv -and -not $SkipDependencySync) {
    Push-Location (Join-Path $Root "apps\server")
    try {
        Invoke-CmdExecutable -Executable $Uv -Arguments @("sync", "--group", "dev")
    } finally {
        Pop-Location
    }
}

$Verifier = Join-Path $env:TEMP "modvii_verify_vision_bbox_$([guid]::NewGuid().ToString('N')).py"
$Code = @'
import asyncio
import base64
import json
import math
import mimetypes
import struct
import zlib
from collections import Counter
from pathlib import Path

from app.config import get_settings
from app.contracts.model_io import VisionInput
from app.providers.registry import ProviderRegistry

RUNS = __RUNS_JSON__
PROMPT = __PROMPT_JSON__
IMAGE_PATH = __IMAGE_PATH_JSON__


def png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def make_demo_png() -> bytes:
    width = 640
    height = 400
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            color = (245, 245, 240)
            if 70 <= x <= 280 and 90 <= y <= 260:
                color = (220, 32, 45)
            elif 360 <= x <= 560 and 120 <= y <= 310:
                color = (38, 95, 210)
            elif 40 <= x <= 600 and 330 <= y <= 360:
                color = (35, 35, 35)
            row.extend(color)
        rows.append(bytes(row))
    raw = b"".join(rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(raw, level=9))
        + png_chunk(b"IEND", b"")
    )


def load_image() -> tuple[str, str, str]:
    if IMAGE_PATH:
        path = Path(IMAGE_PATH)
        data = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        return base64.b64encode(data).decode("ascii"), mime, str(path)
    data = make_demo_png()
    return base64.b64encode(data).decode("ascii"), "image/png", "generated-demo-shapes.png"


def valid_bbox(value: object) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    try:
        y_min, x_min, y_max, x_max = [float(item) for item in value]
    except (TypeError, ValueError):
        return False
    return 0 <= y_min < y_max <= 1000 and 0 <= x_min < x_max <= 1000


async def main() -> None:
    image_base64, mime, image_source = load_image()
    settings = get_settings()
    provider = ProviderRegistry(settings).vision()
    rows = []
    label_sets = []
    parse_successes = 0
    valid_bbox_runs = 0

    for index in range(max(1, RUNS)):
        result = await provider.analyze(
            VisionInput(
                image_base64=image_base64,
                mime=mime,
                prompt=PROMPT,
                mode="focus",
                metadata={"verify": "vision_bbox", "run": index + 1},
            )
        )
        objects = [item.model_dump() for item in result.objects]
        valid_objects = [item for item in objects if valid_bbox(item.get("bbox"))]
        labels = sorted({str(item.get("label", "")).strip().lower() for item in valid_objects if item.get("label")})
        if result.raw.get("structured_parse_success"):
            parse_successes += 1
        if valid_objects:
            valid_bbox_runs += 1
        label_sets.append(labels)
        rows.append(
            {
                "run": index + 1,
                "summary": result.summary,
                "structured_parse_success": bool(result.raw.get("structured_parse_success")),
                "confidence": result.confidence,
                "need_focus": result.need_focus,
                "focus_reason": result.focus_reason,
                "object_count": len(objects),
                "valid_bbox_count": len(valid_objects),
                "labels_with_valid_bbox": labels,
            }
        )

    total_runs = max(1, RUNS)
    label_counts = Counter(label for labels in label_sets for label in labels)
    max_label_hits = max(label_counts.values(), default=0)
    label_consistency_rate = max_label_hits / max(1, valid_bbox_runs)
    parse_success_rate = parse_successes / total_runs
    stable_threshold = max(2, math.ceil(total_runs * 0.6))
    overlay_should_be_stable = (
        parse_success_rate >= 0.8
        and valid_bbox_runs >= stable_threshold
        and label_consistency_rate >= 0.6
    )
    report = {
        "provider": settings.vision_provider,
        "model": getattr(provider, "model", "mock"),
        "image_source": image_source,
        "mime": mime,
        "runs": total_runs,
        "parse_success_rate": round(parse_success_rate, 3),
        "valid_bbox_runs": valid_bbox_runs,
        "label_consistency_rate": round(label_consistency_rate, 3),
        "stable_labels": [
            label for label, count in sorted(label_counts.items()) if count >= stable_threshold
        ],
        "overlay_should_be_stable": overlay_should_be_stable,
        "bbox_convention": "[y_min, x_min, y_max, x_max], normalized 0-1000",
        "results": rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


asyncio.run(main())
'@
$Code = $Code.Replace("__RUNS_JSON__", ($Runs | ConvertTo-Json -Compress))
$Code = $Code.Replace("__PROMPT_JSON__", ($Prompt | ConvertTo-Json -Compress))
$Code = $Code.Replace("__IMAGE_PATH_JSON__", ($ImagePath | ConvertTo-Json -Compress))
Set-Content -Path $Verifier -Value $Code -Encoding UTF8

Push-Location (Join-Path $Root "apps\server")
try {
    if ($Uv) {
        Invoke-CmdExecutable -Executable $Uv -Arguments @("run", "python", $Verifier)
    } else {
        Invoke-CmdExecutable -Executable $Python -Arguments @($Verifier)
    }
} finally {
    Pop-Location
    Remove-Item -Path $Verifier -Force -ErrorAction SilentlyContinue
}
