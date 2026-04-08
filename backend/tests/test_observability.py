import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

import services.observability as observability
from services.observability import RuntimeMetricsRegistry, new_request_id
from services.storage import storage


class ObservabilityTests(unittest.TestCase):
    def test_request_id_has_stable_prefix(self):
        request_id = new_request_id("chat")
        self.assertTrue(request_id.startswith("chat-"))
        self.assertGreater(len(request_id), len("chat-"))

    def test_runtime_metrics_snapshot_tracks_chat_and_agent(self):
        registry = RuntimeMetricsRegistry()

        registry.record_chat_started(stream=True)
        registry.record_chat_finished(
            status="completed",
            timings={
                "llm_first_token_ms": 1200,
                "llm_total_ms": 6400,
                "end_to_end_ms": 7000,
                "retrieval_ms": 180,
            },
        )
        registry.record_chat_rejection(reason="llm_busy")
        registry.record_agent_started()
        registry.record_agent_finished(status="cancelled")

        snapshot = registry.snapshot()
        self.assertEqual(snapshot["scope"], "worker")
        self.assertEqual(snapshot["counters"]["chat_started_total"], 1)
        self.assertEqual(snapshot["counters"]["chat_completed_total"], 1)
        self.assertEqual(snapshot["counters"]["chat_rejected_total"], 1)
        self.assertEqual(snapshot["counters"]["llm_busy_total"], 1)
        self.assertEqual(snapshot["counters"]["agent_started_total"], 1)
        self.assertEqual(snapshot["counters"]["agent_cancelled_total"], 1)
        self.assertEqual(snapshot["inflight"]["chat"], 0)
        self.assertEqual(snapshot["inflight"]["agent"], 0)
        self.assertEqual(snapshot["averages_ms"]["chat_llm_first_token_ms"], 1200.0)
        self.assertEqual(snapshot["averages_ms"]["chat_llm_total_ms"], 6400.0)
        self.assertEqual(snapshot["averages_ms"]["chat_end_to_end_ms"], 7000.0)
        self.assertEqual(snapshot["averages_ms"]["chat_retrieval_ms"], 180.0)
        self.assertIn("latency_sums_ms", snapshot)
        self.assertIn("latency_counts", snapshot)


class AggregatedObservabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_db_path = storage._db_path
        self.temp_dir = Path(BACKEND_ROOT) / ".tmp-test-data" / f"observability-{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        if storage._db is not None:
            await storage.close()

        storage._db_path = self.temp_dir / "test.db"
        await storage.initialize()
        self.original_runtime_metrics = observability.runtime_metrics
        observability.runtime_metrics = RuntimeMetricsRegistry()

    async def asyncTearDown(self):
        observability.runtime_metrics = self.original_runtime_metrics
        await storage.close()
        storage._db_path = self.original_db_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_application_runtime_snapshot_aggregates_multiple_instances(self):
        observability.runtime_metrics.record_chat_started(stream=False)
        observability.runtime_metrics.record_chat_finished(
            status="completed",
            timings={
                "llm_first_token_ms": 1000,
                "llm_total_ms": 2000,
                "end_to_end_ms": 2500,
                "retrieval_ms": 120,
            },
        )

        with patch.dict(
            os.environ,
            {
                "MEETING_ASSISTANT_PORT": "7001",
                "MEETING_ASSISTANT_INSTANCE_INDEX": "0",
                "MEETING_ASSISTANT_INSTANCE_MODE": "windows-cluster",
                "MEETING_ASSISTANT_INSTANCE_ID": "test-host:7001:0:111",
            },
            clear=False,
        ):
            await observability.publish_runtime_metrics(force=True, storage_service=storage)

        second_snapshot = {
            "scope": "worker",
            "instance": {
                "instance_id": "test-host:7002:1:999",
                "instance_index": "1",
                "instance_mode": "windows-cluster",
                "host": "test-host",
                "port": "7002",
                "pid": "999",
            },
            "counters": {
                "chat_started_total": 2,
                "chat_completed_total": 2,
                "chat_failed_total": 0,
                "chat_rejected_total": 1,
                "chat_stream_started_total": 0,
                "chat_non_stream_started_total": 2,
                "agent_started_total": 0,
                "agent_completed_total": 0,
                "agent_failed_total": 0,
                "agent_cancelled_total": 0,
                "llm_busy_total": 1,
                "conversation_busy_total": 0,
            },
            "inflight": {"chat": 1, "agent": 0},
            "averages_ms": {},
            "latency_sums_ms": {
                "chat_llm_first_token_ms": 4000,
                "chat_llm_total_ms": 8000,
                "chat_end_to_end_ms": 9000,
                "chat_retrieval_ms": 300,
            },
            "latency_counts": {
                "chat_llm_first_token_ms": 2,
                "chat_llm_total_ms": 2,
                "chat_end_to_end_ms": 2,
                "chat_retrieval_ms": 2,
            },
        }
        await storage.upsert_runtime_application_metrics(
            second_snapshot["instance"]["instance_id"],
            observability.json.dumps(second_snapshot, ensure_ascii=False, sort_keys=True),
        )

        with patch.dict(
            os.environ,
            {
                "MEETING_ASSISTANT_PORT": "7001",
                "MEETING_ASSISTANT_INSTANCE_INDEX": "0",
                "MEETING_ASSISTANT_INSTANCE_MODE": "windows-cluster",
                "MEETING_ASSISTANT_INSTANCE_ID": "test-host:7001:0:111",
            },
            clear=False,
        ):
            result = await observability.get_application_runtime_snapshot(storage_service=storage)

        self.assertEqual(result["scope"], "cluster")
        self.assertEqual(result["instance_count"], 2)
        self.assertEqual(result["counters"]["chat_started_total"], 3)
        self.assertEqual(result["counters"]["chat_completed_total"], 3)
        self.assertEqual(result["counters"]["chat_rejected_total"], 1)
        self.assertEqual(result["inflight"]["chat"], 1)
        self.assertEqual(result["averages_ms"]["chat_llm_first_token_ms"], round((1000 + 4000) / 3, 2))
        self.assertEqual(result["averages_ms"]["chat_llm_total_ms"], round((2000 + 8000) / 3, 2))


if __name__ == "__main__":
    unittest.main()
