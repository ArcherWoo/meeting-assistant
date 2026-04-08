from __future__ import annotations

import argparse
import asyncio
import time

import httpx

from loadtest_common import (
    Sample,
    add_shared_args,
    attachment_context,
    build_nonstream_chat_payload,
    make_headers,
    post_extract_text,
    print_summary,
    read_file_bytes,
    run_loadtest,
    sample_from_exception,
)


async def _single_attachment_request(
    client: httpx.AsyncClient,
    token: str,
    *,
    model: str,
    prompt: str,
    role_id: str,
    file_name: str,
    file_bytes: bytes,
    fast_mode: bool,
) -> Sample:
    started_at = time.perf_counter()
    try:
        extract_started_at = time.perf_counter()
        extracted = await post_extract_text(
            client,
            token,
            file_name=file_name,
            file_bytes=file_bytes,
            fast_mode=fast_mode,
        )
        extract_elapsed_ms = round((time.perf_counter() - extract_started_at) * 1000)

        files = extracted.get("files") or []
        if not files:
            errors = extracted.get("errors") or []
            detail = errors[0]["error"] if errors else "extract-text returned no files"
            return Sample(
                False,
                0,
                round((time.perf_counter() - started_at) * 1000),
                str(detail),
                attachment_extract_ms=extract_elapsed_ms,
            )

        first = files[0]
        prompt_with_attachment = (
            prompt
            + attachment_context(
                filename=str(first.get("filename") or file_name),
                text=str(first.get("text") or ""),
                char_count=int(first.get("char_count") or 0),
            )
        )
        payload = build_nonstream_chat_payload(model=model, prompt=prompt_with_attachment, role_id=role_id)
        headers = make_headers(token)

        chat_started_at = time.perf_counter()
        response = await client.post("/api/chat/completions", headers=headers, json=payload)
        chat_elapsed_ms = round((time.perf_counter() - chat_started_at) * 1000)
        total_elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        if response.status_code >= 400:
            detail = response.text
            try:
                detail = str(response.json())
            except Exception:
                pass
            return Sample(
                False,
                response.status_code,
                total_elapsed_ms,
                detail,
                attachment_extract_ms=extract_elapsed_ms,
                chat_elapsed_ms=chat_elapsed_ms,
            )
        return Sample(
            True,
            response.status_code,
            total_elapsed_ms,
            attachment_extract_ms=extract_elapsed_ms,
            chat_elapsed_ms=chat_elapsed_ms,
        )
    except Exception as exc:  # noqa: BLE001
        return sample_from_exception(started_at, exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="附件提取 + chat 压测")
    add_shared_args(parser)
    parser.add_argument("--file", required=True, help="要上传的本地附件路径")
    parser.add_argument("--prompt", default="请先概括附件内容，再给出三条关键结论。", help="附件分析提示词")
    parser.add_argument("--structured", action="store_true", help="关闭 fast_mode，改走结构化提取链路")
    args = parser.parse_args()

    file_bytes, file_name = read_file_bytes(args.file)

    async def request_factory(client: httpx.AsyncClient, token: str, _index: int) -> Sample:
        return await _single_attachment_request(
            client,
            token,
            model=args.model,
            prompt=args.prompt,
            role_id=args.role_id,
            file_name=file_name,
            file_bytes=file_bytes,
            fast_mode=not args.structured,
        )

    results = asyncio.run(run_loadtest(args=args, request_factory=request_factory))
    return print_summary(title="附件 Chat 压测结果", args=args, results=results)


if __name__ == "__main__":
    raise SystemExit(main())
