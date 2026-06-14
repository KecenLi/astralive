from collections.abc import AsyncIterator
import ssl

import certifi
import httpx


# Build the TLS context once from certifi's bundled CA file. In a PyInstaller
# exe, ssl.create_default_context() (httpx's default) can raise
# FileNotFoundError: [Errno 2] when the OS CA bundle path is missing. Pointing
# explicitly at certifi.where() makes HTTPS work regardless of how the exe was
# packaged — defense in depth alongside bundling certifi in the .spec.
try:
    _SSL_CONTEXT: ssl.SSLContext | bool = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001 - fall back to httpx's own default if certifi is unavailable
    _SSL_CONTEXT = True


def make_streaming_client(timeout: float) -> httpx.AsyncClient:
    """An httpx.AsyncClient that verifies TLS using certifi's CA bundle."""
    return httpx.AsyncClient(timeout=timeout, verify=_SSL_CONTEXT)


async def iter_sse_data(response: httpx.Response) -> AsyncIterator[str]:
    data_lines: list[str] = []
    async for raw_line in response.aiter_lines():
        line = raw_line.rstrip("\r")
        if not line:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield "\n".join(data_lines)


async def iter_jsonl_data(response: httpx.Response) -> AsyncIterator[str]:
    async for raw_line in response.aiter_lines():
        line = raw_line.strip()
        if line:
            yield line


def content_to_text(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                chunks.append(str(item.get("text") or item.get("content") or ""))
            else:
                chunks.append(str(item))
        return "".join(chunks)
    return str(content)
