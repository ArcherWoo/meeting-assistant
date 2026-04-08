from __future__ import annotations

import argparse
import asyncio
import time

import httpx

from loadtest_common import (
    Sample,
    add_shared_args,
    build_nonstream_chat_payload,
    make_headers,
    print_summary,
    run_loadtest,
    sample_from_exception,
)


async def _single_request(
    client: httpx.AsyncClient,
    token: str,
    *,
    model: str,
    prompt: str,
    role_id: str,
) -> Sample:
    headers = make_headers(token)
    payload = build_nonstream_chat_payload(model=model, prompt=prompt, role_id=role_id)

    started_at = time.perf_counter()
    try:
        response = await client.post("/api/chat/completions", headers=headers, json=payload)
        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        if response.status_code >= 400:
            detail = response.text
            try:
                detail = str(response.json())
            except Exception:
                pass
            return Sample(False, response.status_code, elapsed_ms, detail)
        return Sample(True, response.status_code, elapsed_ms, chat_elapsed_ms=elapsed_ms)
    except Exception as exc:  # noqa: BLE001
        return sample_from_exception(started_at, exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="普通非流式 chat 压测")
    add_shared_args(parser)
    parser.add_argument("--prompt", default="请用两三句话介绍一下你能做什么。", help="每次请求的提示词")
    args = parser.parse_args()

    async def request_factory(client: httpx.AsyncClient, token: str, _index: int) -> Sample:
        return await _single_request(
            client,
            token,
            model=args.model,
            prompt=args.prompt,
            role_id=args.role_id,
        )

    results = asyncio.run(run_loadtest(args=args, request_factory=request_factory))
    return print_summary(title="Chat 压测结果", args=args, results=results)


if __name__ == "__main__":
    raise SystemExit(main())
