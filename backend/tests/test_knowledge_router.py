import io
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from starlette.datastructures import UploadFile


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from routers import knowledge as knowledge_router


def make_upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(content))


class KnowledgeRouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.user = {"id": "tester", "system_role": "admin", "group_id": None}

    async def test_extract_text_single_file_keeps_legacy_response_shape(self):
        upload = make_upload("note.txt", b"meeting notes")

        with patch.object(
            knowledge_router.knowledge_service,
            "extract_text",
            AsyncMock(return_value={
                "filename": "note.txt",
                "file_type": "txt",
                "text": "meeting notes",
                "char_count": 13,
            }),
        ) as extract_mock:
            result = await knowledge_router.extract_text(file=upload, files=None)

        self.assertEqual(result["filename"], "note.txt")
        self.assertNotIn("files", result)
        extract_mock.assert_awaited_once()

    async def test_extract_text_batch_returns_envelope(self):
        uploads = [
            make_upload("first.txt", b"A"),
            make_upload("second.txt", b"B"),
        ]

        with patch.object(
            knowledge_router.knowledge_service,
            "extract_text",
            AsyncMock(side_effect=[
                {"filename": "first.txt", "file_type": "txt", "text": "A", "char_count": 1},
                {"filename": "second.txt", "file_type": "txt", "text": "B", "char_count": 1},
            ]),
        ):
            result = await knowledge_router.extract_text(file=None, files=uploads)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["failed_count"], 0)
        self.assertEqual([item["filename"] for item in result["files"]], ["first.txt", "second.txt"])

    async def test_ingest_file_batch_returns_partial_failures_without_raising(self):
        uploads = [
            make_upload("valid.txt", b"valid content"),
            make_upload("invalid.exe", b"binary"),
        ]

        with patch.object(knowledge_router.storage, "get_setting", AsyncMock(return_value="")):
            with patch.object(
                knowledge_router.knowledge_service,
                "ingest_file",
                AsyncMock(return_value={
                    "import_id": "import-1",
                    "status": "completed",
                    "file_type": "text",
                    "extracted_count": 0,
                    "chunks_count": 1,
                    "char_count": 13,
                }),
            ) as ingest_mock:
                result = await knowledge_router.ingest_file(file=None, files=uploads, user=self.user)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["results"][0]["import_id"], "import-1")
        self.assertEqual(result["errors"][0]["filename"], "invalid.exe")
        ingest_mock.assert_awaited_once()

    async def test_ingest_file_single_invalid_upload_still_raises_http_error(self):
        upload = make_upload("invalid.exe", b"binary")

        with patch.object(knowledge_router.storage, "get_setting", AsyncMock(return_value="")) as get_setting_mock:
            with self.assertRaises(HTTPException) as context:
                await knowledge_router.ingest_file(file=upload, files=None, user=self.user)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn(".exe", context.exception.detail)
        get_setting_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
