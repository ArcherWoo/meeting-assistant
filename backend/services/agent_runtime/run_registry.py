from __future__ import annotations

import asyncio


class AgentRunRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._cancel_requests: set[str] = set()
        self._lock = asyncio.Lock()

    async def register(self, run_id: str, task: asyncio.Task) -> None:
        async with self._lock:
            self._tasks[run_id] = task
            if run_id in self._cancel_requests:
                task.cancel("cancel requested before task registration")

    async def unregister(self, run_id: str, task: asyncio.Task | None = None) -> None:
        async with self._lock:
            current = self._tasks.get(run_id)
            if current is None:
                return
            if task is not None and current is not task:
                return
            self._tasks.pop(run_id, None)

    async def request_cancel(self, run_id: str) -> bool:
        async with self._lock:
            self._cancel_requests.add(run_id)
            task = self._tasks.get(run_id)

        if task is None:
            return False

        task.cancel("cancel requested by user")
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        return True

    async def is_cancel_requested(self, run_id: str) -> bool:
        async with self._lock:
            return run_id in self._cancel_requests

    async def clear_cancel_request(self, run_id: str) -> None:
        async with self._lock:
            self._cancel_requests.discard(run_id)


run_registry = AgentRunRegistry()
