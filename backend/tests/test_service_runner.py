import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import shutil
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_ROOT = PROJECT_ROOT / "deploy"
if str(DEPLOY_ROOT) not in sys.path:
    sys.path.insert(0, str(DEPLOY_ROOT))

import deploy as deploy_module  # noqa: E402
import service_runner  # noqa: E402


class ServiceRunnerBuildSpecsTests(unittest.TestCase):
    def test_windows_sqlite_workers_expand_to_multiple_single_worker_instances(self):
        env = {
            "MEETING_ASSISTANT_HOST": "127.0.0.1",
            "MEETING_ASSISTANT_PORT": "6200",
            "MEETING_ASSISTANT_WORKERS": "3",
            "MEETING_ASSISTANT_RUNTIME_COORDINATION": "sqlite",
            "MEETING_ASSISTANT_LOG_DIR": str(PROJECT_ROOT / "tmp" / "logs"),
            "MEETING_ASSISTANT_PYTHON_EXECUTABLE": sys.executable,
        }
        env_file = PROJECT_ROOT / "deploy" / "server.env"

        with patch("service_runner.platform.system", return_value="Windows"):
            specs = service_runner.build_child_specs(env, env_file)

        self.assertEqual(len(specs), 3)
        self.assertEqual([spec.port for spec in specs], [6200, 6201, 6202])
        self.assertTrue(all("--workers" in spec.command for spec in specs))
        self.assertTrue(all(spec.command[spec.command.index("--workers") + 1] == "1" for spec in specs))
        self.assertEqual(specs[0].env["MEETING_ASSISTANT_INSTANCE_MODE"], "windows-cluster")

    def test_linux_keeps_single_listener_with_uvicorn_workers(self):
        env = {
            "MEETING_ASSISTANT_HOST": "0.0.0.0",
            "MEETING_ASSISTANT_PORT": "6200",
            "MEETING_ASSISTANT_WORKERS": "3",
            "MEETING_ASSISTANT_RUNTIME_COORDINATION": "sqlite",
            "MEETING_ASSISTANT_LOG_DIR": str(PROJECT_ROOT / "tmp" / "logs"),
            "MEETING_ASSISTANT_PYTHON_EXECUTABLE": sys.executable,
        }
        env_file = PROJECT_ROOT / "deploy" / "server.env"

        with patch("service_runner.platform.system", return_value="Linux"):
            specs = service_runner.build_child_specs(env, env_file)

        self.assertEqual(len(specs), 1)
        self.assertIn("--workers", specs[0].command)
        self.assertEqual(specs[0].command[specs[0].command.index("--workers") + 1], "3")
        self.assertEqual(specs[0].env["MEETING_ASSISTANT_INSTANCE_MODE"], "single-process")


class RenderedNginxConfigTests(unittest.TestCase):
    def test_windows_rendered_config_contains_all_instance_ports(self):
        tmp_dir = PROJECT_ROOT / "backend" / ".tmp-test-data" / f"deploy-render-{uuid.uuid4().hex}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            env_file = tmp_dir / "server.env"
            env_file.write_text(
                "\n".join(
                    [
                        "MEETING_ASSISTANT_HOST=0.0.0.0",
                        "MEETING_ASSISTANT_PORT=6300",
                        "MEETING_ASSISTANT_WORKERS=3",
                        "MEETING_ASSISTANT_RUNTIME_COORDINATION=sqlite",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            rendered = deploy_module._render_nginx_config(env_file, target_platform="windows")  # noqa: SLF001
            content = rendered.read_text(encoding="utf-8")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        self.assertIn("server 127.0.0.1:6300;", content)
        self.assertIn("server 127.0.0.1:6301;", content)
        self.assertIn("server 127.0.0.1:6302;", content)


if __name__ == "__main__":
    unittest.main()
