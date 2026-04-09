from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def build_handler(*, model_id: str, delay_ms: int):
    class MockOpenAIHandler(BaseHTTPRequestHandler):
        server_version = "MockOpenAI/1.0"

        def do_GET(self):  # noqa: N802
            if self.path.rstrip("/") == "/v1/models":
                self._send_json(
                    200,
                    {
                        "object": "list",
                        "data": [{"id": model_id, "object": "model"}],
                    },
                )
                return
            self._send_json(404, {"error": {"message": "not found"}})

        def do_POST(self):  # noqa: N802
            if self.path.rstrip("/") != "/v1/chat/completions":
                self._send_json(404, {"error": {"message": "not found"}})
                return

            length = int(self.headers.get("Content-Length", "0") or "0")
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except json.JSONDecodeError:
                self._send_json(400, {"error": {"message": "invalid json"}})
                return

            stream = bool(payload.get("stream"))
            include_usage = bool((payload.get("stream_options") or {}).get("include_usage"))
            requested_model = str(payload.get("model") or model_id).strip() or model_id
            if requested_model != model_id:
                self._send_json(400, {"error": {"message": f"model {requested_model} not available"}})
                return

            time.sleep(max(0, delay_ms) / 1000.0)

            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()

                chunks = [
                    f'data: {json.dumps({"choices": [{"delta": {"content": "你好，"}}]}, ensure_ascii=False)}\n\n',
                    f'data: {json.dumps({"choices": [{"delta": {"content": "我是本地压测模型。"}}]}, ensure_ascii=False)}\n\n',
                ]
                if include_usage:
                    chunks.append(
                        f'data: {json.dumps({"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}}, ensure_ascii=False)}\n\n'
                    )
                chunks.append("data: [DONE]\n\n")

                for chunk in chunks:
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
                return

            self._send_json(
                200,
                {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion",
                    "model": model_id,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "你好，我是本地压测模型。",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 8,
                        "total_tokens": 20,
                    },
                },
            )

        def log_message(self, format, *args):  # noqa: A003
            return

        def _send_json(self, status_code: int, payload: dict):
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return MockOpenAIHandler


def main() -> int:
    parser = argparse.ArgumentParser(description="Mock OpenAI-compatible server for local load testing")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5190)
    parser.add_argument("--model", default="mock-gpt")
    parser.add_argument("--delay-ms", type=int, default=350)
    args = parser.parse_args()

    handler_cls = build_handler(model_id=args.model, delay_ms=args.delay_ms)
    server = ThreadingHTTPServer((args.host, args.port), handler_cls)
    print(f"Mock OpenAI server listening on http://{args.host}:{args.port}/v1", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
