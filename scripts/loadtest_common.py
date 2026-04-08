from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import httpx


@dataclass
class Sample:
    ok: bool
    status_code: int
    elapsed_ms: int
    error: str = ""
    first_token_ms: int = 0
    attachment_extract_ms: int = 0
    chat_elapsed_ms: int = 0


def add_shared_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default="http://127.0.0.1:5173", help="服务基地址")
    parser.add_argument("--username", required=True, help="登录用户名")
    parser.add_argument("--password", required=True, help="登录密码")
    parser.add_argument("--role-id", default="copilot", help="聊天角色 ID")
    parser.add_argument("--model", default="gpt-4o", help="请求里使用的模型名")
    parser.add_argument("--requests", type=int, default=20, help="总请求数")
    parser.add_argument("--concurrency", type=int, default=10, help="并发数")
    parser.add_argument("--timeout-sec", type=float, default=120.0, help="单请求读取超时秒数")


def build_client(*, base_url: str, concurrency: int, timeout_sec: float) -> httpx.AsyncClient:
    limits = httpx.Limits(
        max_connections=max(concurrency * 2, 20),
        max_keepalive_connections=max(concurrency, 10),
    )
    timeout = httpx.Timeout(connect=10.0, read=timeout_sec, write=20.0, pool=10.0)
    return httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, limits=limits)


async def login(client: httpx.AsyncClient, username: str, password: str) -> str:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    response.raise_for_status()
    payload = response.json()
    return str(payload["token"])


def percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


async def run_loadtest(
    *,
    args,
    request_factory: Callable[[httpx.AsyncClient, str, int], Awaitable[Sample]],
) -> list[Sample]:
    async with build_client(
        base_url=args.base_url,
        concurrency=args.concurrency,
        timeout_sec=args.timeout_sec,
    ) as client:
        token = await login(client, args.username, args.password)
        semaphore = asyncio.Semaphore(args.concurrency)
        results: list[Sample] = []

        async def worker(index: int) -> None:
            async with semaphore:
                results.append(await request_factory(client, token, index))

        await asyncio.gather(*(worker(index) for index in range(1, args.requests + 1)))
        return results


def print_summary(*, title: str, args, results: list[Sample]) -> int:
    success = [sample for sample in results if sample.ok]
    failed = [sample for sample in results if not sample.ok]
    success_latencies = [sample.elapsed_ms for sample in success]
    first_token_latencies = [sample.first_token_ms for sample in success if sample.first_token_ms > 0]
    attachment_latencies = [sample.attachment_extract_ms for sample in success if sample.attachment_extract_ms > 0]
    chat_latencies = [sample.chat_elapsed_ms for sample in success if sample.chat_elapsed_ms > 0]

    print("")
    print(title)
    print(f"目标地址:        {args.base_url}")
    print(f"总请求数:        {len(results)}")
    print(f"并发数:          {args.concurrency}")
    print(f"成功数:          {len(success)}")
    print(f"失败数:          {len(failed)}")

    if success_latencies:
        print(f"平均耗时:        {round(statistics.mean(success_latencies), 2)} ms")
        print(f"中位耗时:        {percentile(success_latencies, 0.50)} ms")
        print(f"P95 耗时:        {percentile(success_latencies, 0.95)} ms")
        print(f"最大耗时:        {max(success_latencies)} ms")

    if first_token_latencies:
        print(f"平均首字:        {round(statistics.mean(first_token_latencies), 2)} ms")
        print(f"P95 首字:        {percentile(first_token_latencies, 0.95)} ms")

    if attachment_latencies:
        print(f"平均附件提取:    {round(statistics.mean(attachment_latencies), 2)} ms")
        print(f"P95 附件提取:    {percentile(attachment_latencies, 0.95)} ms")

    if chat_latencies:
        print(f"平均聊天耗时:    {round(statistics.mean(chat_latencies), 2)} ms")
        print(f"P95 聊天耗时:    {percentile(chat_latencies, 0.95)} ms")

    if failed:
        print("")
        print("失败样本:")
        for sample in failed[:10]:
            print(f"- status={sample.status_code} elapsed={sample.elapsed_ms}ms error={sample.error}")

    return 0 if not failed else 1


def make_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def build_nonstream_chat_payload(*, model: str, prompt: str, role_id: str) -> dict:
    return {
        "messages": [{"role": "user", "content": prompt}],
        "model": model,
        "temperature": 0.2,
        "max_tokens": 256,
        "stream": False,
        "role_id": role_id,
    }


def attachment_context(*, filename: str, text: str, char_count: int | None = None, index: int = 0, total: int = 1) -> str:
    count = char_count if char_count is not None else len(text)
    suffix = f" #{index + 1}" if total > 1 else ""
    return f'\n\n---\n📎 附件{suffix}“{filename}”内容（{count} 字符）：\n\n{text}'


def read_file_bytes(path: str) -> tuple[bytes, str]:
    resolved = Path(path).expanduser().resolve()
    return resolved.read_bytes(), resolved.name


async def post_extract_text(
    client: httpx.AsyncClient,
    token: str,
    *,
    file_name: str,
    file_bytes: bytes,
    fast_mode: bool = True,
) -> dict:
    headers = make_headers(token)
    files = {"files": (file_name, file_bytes)}
    data = {"fast_mode": "true" if fast_mode else "false"}
    response = await client.post(
        "/api/knowledge/extract-text",
        headers=headers,
        files=files,
        data=data,
    )
    response.raise_for_status()
    return response.json()


def sample_from_exception(started_at: float, exc: Exception) -> Sample:
    elapsed_ms = round((time.perf_counter() - started_at) * 1000)
    status_code = getattr(exc, "response", None).status_code if isinstance(exc, httpx.HTTPStatusError) else 0
    error = str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            error = json.dumps(exc.response.json(), ensure_ascii=False)
        except Exception:
            error = exc.response.text or error
    return Sample(False, status_code, elapsed_ms, error)
