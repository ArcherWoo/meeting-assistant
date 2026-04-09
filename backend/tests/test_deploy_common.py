import sys
import unittest
from pathlib import Path
import shutil
import uuid
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_ROOT = PROJECT_ROOT / "deploy"
if str(DEPLOY_ROOT) not in sys.path:
    sys.path.insert(0, str(DEPLOY_ROOT))

import common  # noqa: E402


class DeployCommonHelpersTests(unittest.TestCase):
    def test_relax_requirement_keeps_package_and_extras(self):
        self.assertEqual(common._relax_requirement("fastapi==0.115.6"), "fastapi")  # noqa: SLF001
        self.assertEqual(
            common._relax_requirement("pydantic-ai-slim[openai]==1.73.0"),  # noqa: SLF001
            "pydantic-ai-slim[openai]",
        )

    def test_build_pip_env_maps_company_mirror_settings(self):
        tmp_dir = PROJECT_ROOT / "backend" / ".tmp-test-data" / f"deploy-common-{uuid.uuid4().hex}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            env_file = tmp_dir / "server.env"
            env_file.write_text(
                "\n".join(
                    [
                        "MEETING_ASSISTANT_PIP_INDEX_URL=https://mirror.example/simple",
                        "MEETING_ASSISTANT_PIP_EXTRA_INDEX_URL=https://mirror.example/extra",
                        "MEETING_ASSISTANT_PIP_TRUSTED_HOST=mirror.example",
                        "MEETING_ASSISTANT_PIP_FIND_LINKS=\\\\fileserver\\wheels",
                        "MEETING_ASSISTANT_PIP_NO_INDEX=1",
                        "MEETING_ASSISTANT_PIP_ARGS=--prefer-binary --timeout 30",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            pip_env = common.build_pip_env(env_file)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        self.assertEqual(pip_env["PIP_INDEX_URL"], "https://mirror.example/simple")
        self.assertEqual(pip_env["PIP_EXTRA_INDEX_URL"], "https://mirror.example/extra")
        self.assertEqual(pip_env["PIP_TRUSTED_HOST"], "mirror.example")
        self.assertEqual(pip_env["PIP_FIND_LINKS"], "\\\\fileserver\\wheels")
        self.assertEqual(pip_env["PIP_NO_INDEX"], "1")
        self.assertEqual(pip_env["MEETING_ASSISTANT_PIP_ARGS"], "--prefer-binary --timeout 30")

    def test_detect_pip_settings_reads_pip_config_output(self):
        pip_output = "\n".join(
            [
                "global.index-url='https://mirror.example/simple'",
                "install.trusted-host='mirror.example'",
            ]
        )
        with patch("common.run", return_value=pip_output):
            detected = common.detect_pip_settings("python")

        self.assertEqual(detected["MEETING_ASSISTANT_PIP_INDEX_URL"], "https://mirror.example/simple")
        self.assertEqual(detected["MEETING_ASSISTANT_PIP_TRUSTED_HOST"], "mirror.example")

    def test_detect_missing_requirements_uses_import_name_overrides(self):
        tmp_dir = PROJECT_ROOT / "backend" / ".tmp-test-data" / f"deploy-common-{uuid.uuid4().hex}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            requirements_file = tmp_dir / "requirements.txt"
            requirements_file.write_text(
                "\n".join(
                    [
                        "python-pptx==1.0.2",
                        "python-multipart==0.0.19",
                        "httpx==0.27.2",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            original = common.python_can_import

            def fake_python_can_import(_python_executable, import_name: str) -> bool:
                return import_name in {"pptx", "httpx"}

            common.python_can_import = fake_python_can_import
            try:
                missing = common.detect_missing_requirements("python", requirements_file)
            finally:
                common.python_can_import = original
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        self.assertEqual(missing, ["python-multipart==0.0.19"])

    def test_venv_system_site_packages_detection_reads_pyvenv_cfg(self):
        tmp_dir = PROJECT_ROOT / "backend" / ".tmp-test-data" / f"deploy-common-{uuid.uuid4().hex}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            (tmp_dir / "pyvenv.cfg").write_text(
                "home = C:\\Python313\ninclude-system-site-packages = true\nversion = 3.13.0\n",
                encoding="utf-8",
            )
            self.assertTrue(common._venv_uses_system_site_packages(tmp_dir))  # noqa: SLF001
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_backfill_env_file_populates_blank_auto_detected_fields(self):
        tmp_dir = PROJECT_ROOT / "backend" / ".tmp-test-data" / f"deploy-common-{uuid.uuid4().hex}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            env_file = tmp_dir / "server.env"
            env_file.write_text(
                "\n".join(
                    [
                        "MEETING_ASSISTANT_HOST=0.0.0.0",
                        "MEETING_ASSISTANT_PIP_INDEX_URL=",
                        "MEETING_ASSISTANT_PIP_TRUSTED_HOST=",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with patch(
                "common.detect_pip_settings",
                return_value={
                    "MEETING_ASSISTANT_PIP_INDEX_URL": "https://mirror.example/simple",
                    "MEETING_ASSISTANT_PIP_TRUSTED_HOST": "mirror.example",
                },
            ):
                common.backfill_env_file(env_file)

            loaded = common.load_env_file(env_file)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        self.assertEqual(loaded["MEETING_ASSISTANT_PIP_INDEX_URL"], "https://mirror.example/simple")
        self.assertEqual(loaded["MEETING_ASSISTANT_PIP_TRUSTED_HOST"], "mirror.example")


if __name__ == "__main__":
    unittest.main()
