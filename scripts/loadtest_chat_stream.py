from __future__ import annotations

import argparse
import asyncio
import json
import time

import httpx

from loadtest_common import (
    Sample,
    add_shared_args,
    make_headers,
    print_summary,
    run_loadtest,
    sample_from_exception,
)


def _extract_content_from_sse_line(line: str) -> str:
    stripped = line.strip()
    if not stripped.startswith("data: "):
        return ""
    payload_text = stripped[6:].strip()
    if not payload_text or payload_text == "[DONE]":
        return ""
    payload = json.loads(payload_text)
    if not isinstance(payload, dict) or payload.get("type") or payload.get("stream_error"):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
    if not isinstance(delta, dict):
        return ""
    return str(delta.get("content") or "")


async def _single_stream_request(
    client: httpx.AsyncClient,
    token: str,
    *,
    model: str,
    prompt: str,
    role_id: str,
) -> Sample:
    headers = make_headers(token)
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "model": model,
        "temperature": 0.2,
        "max_tokens": 256,
        "stream": True,
        "role_id": role_id,
    }

    started_at = time.perf_counter()
    first_token_ms = 0
    buffer = ""
    saw_done = False
    try:
        async with client.stream(
            "POST",
            "/api/chat/completions",
            headers=headers,
            json=payload,
        ) as response:
            if response.status_code >= 400:
                detail = await response.aread()
                detail_text = detail.decode("utf-8", errors="ignore")
                return Sample(
                    False,
                    response.status_code,
                    round((time.perf_counter() - started_at) * 1000),
                    detail_text,
                )

            async for chunk in response.aiter_text():
                buffer += chunk
                lines = buffer.split("\n")
                buffer = lines.pop() or ""
                for line in lines:
                    stripped = line.strip()
                    if stripped == "data: [DONE]":
                        saw_done = True
                        continue
                    try:
                        content = _extract_content_from_sse_line(stripped)
                    except Exception:
                        content = ""
                    if content and first_token_ms == 0:
                        first_token_ms = round((time.perf_counter() - started_at) * 1000)

        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        if not saw_done:
            return Sample(False, 0, elapsed_ms, "stream finished before [DONE]", first_token_ms=first_token_ms)
        return Sample(True, 200, elapsed_ms, first_token_ms=first_token_ms, chat_elapsed_ms=elapsed_ms)
    except Exception as exc:  # noqa: BLE001
        return sample_from_exception(started_at, exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="流式 chat 压测")
    add_shared_args(parser)
    parser.add_argument("--prompt", default="请用两三句话介绍一下你能做什么。", help="每次请求的提示词")
    args = parser.parse_args()

    async def request_factory(client: httpx.AsyncClient, token: str, _index: int) -> Sample:
        return await _single_stream_request(
            client,
            token,
            model=args.model,
            prompt=args.prompt,
            role_id=args.role_id,
        )

    results = asyncio.run(run_loadtest(args=args, request_factory=request_factory))
    return print_summary(title="流式 Chat 压测结果", args=args, results=results)


if __name__ == "__main__":
    raise SystemExit(main())
