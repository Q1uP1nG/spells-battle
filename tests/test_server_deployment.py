import unittest
from pathlib import Path
import subprocess
import sys

import yaml

from server.config import ServerConfig


ROOT = Path(__file__).resolve().parents[1]


class ServerDeploymentTests(unittest.TestCase):
    def test_server_config_rejects_unsafe_rates_and_invalid_log_level(self):
        with self.assertRaises(ValueError):
            ServerConfig(tick_rate=10, snapshot_rate=15)
        with self.assertRaises(ValueError):
            ServerConfig(log_level="VERBOSE")

    def test_server_image_is_headless_and_runs_as_non_root(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements-server.txt").read_text(encoding="utf-8")

        self.assertIn("USER spells", dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn('CMD ["python", "-m", "server.app"]', dockerfile)
        for dependency in ("opencv", "mediapipe", "pygame", "Pillow"):
            self.assertNotIn(dependency, requirements)

    def test_compose_exposes_only_caddy_and_rotates_logs(self):
        compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
        services = compose["services"]

        self.assertNotIn("ports", services["spells-server"])
        self.assertEqual(services["spells-server"]["restart"], "unless-stopped")
        self.assertIn("443:443", services["caddy"]["ports"])
        self.assertNotIn("80:80", services["caddy"]["ports"])
        self.assertEqual(
            services["spells-server"]["logging"]["options"]["max-file"], "5"
        )

    def test_caddy_terminates_tls_and_proxies_websocket_capable_http(self):
        caddyfile = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")

        self.assertIn("{$SPELLS_DOMAIN}", caddyfile)
        self.assertIn("reverse_proxy spells-server:8765", caddyfile)
        self.assertIn("Strict-Transport-Security", caddyfile)

    def test_headless_server_import_does_not_load_client_device_dependencies(self):
        command = (
            "import sys; import server.app; "
            "assert 'cv2' not in sys.modules; "
            "assert 'pygame' not in sys.modules; "
            "assert 'mediapipe' not in sys.modules"
        )

        result = subprocess.run(
            [sys.executable, "-c", command], capture_output=True, text=True, check=False
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
