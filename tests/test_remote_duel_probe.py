import unittest
from pathlib import Path
import subprocess
import sys

from server.app import BattleServer
from server.config import ServerConfig
from tools.remote_duel_probe import health_url, probe


ROOT = Path(__file__).resolve().parents[1]


class RemoteDuelProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_quick_probe_exercises_two_real_clients(self):
        server = BattleServer(
            ServerConfig(host="127.0.0.1", port=0, tick_rate=30, snapshot_rate=15)
        )
        await server.start()
        try:
            report = await probe(
                f"ws://127.0.0.1:{server.port}", full_round=False, timeout=3.0
            )
        finally:
            await server.stop()

        self.assertTrue(report["ok"])
        self.assertEqual(report["protocol_version"], 2)
        self.assertFalse(report["full_round"])

    def test_health_url_tracks_websocket_tls_scheme(self):
        self.assertEqual(health_url("wss://duel.example.com"), "https://duel.example.com/health")
        self.assertEqual(health_url("ws://localhost:8765"), "http://localhost:8765/health")

    def test_documented_direct_script_entrypoint_loads_project_packages(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "remote_duel_probe.py"), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Probe a deployed Spells Remote Duel server", result.stdout)


if __name__ == "__main__":
    unittest.main()
