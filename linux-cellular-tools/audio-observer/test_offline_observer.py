#!/usr/bin/env python3
"""Offline validation for dw5934e-voice-audio-endpoint-observer.sh."""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "dw5934e-voice-audio-endpoint-observer.sh"


def to_bash_path(path: str) -> str:
    """Convert a local Windows path to a bash-friendly path when needed."""
    normalized = path.replace("\\", "/")
    if len(normalized) >= 3 and normalized[1:3] == ":/":
        return f"/{normalized[0].lower()}{normalized[2:]}"
    return normalized


def run_cmd(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        args=["bash", "-lc", cmd],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


class TestObserverOffline(unittest.TestCase):
    def test_script_has_required_safety_words(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", text)
        self.assertIn("No calls to qmicli/mbimcli/mmcli", text)
        self.assertIn("No automatic dialing", text)
        self.assertIn("No remote execution", text)

    def test_bash_syntax(self) -> None:
        quoted = shlex.quote(to_bash_path(str(SCRIPT)))
        result = run_cmd(f"bash -n {quoted}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_help_output_contains_contract(self) -> None:
        quoted = shlex.quote(to_bash_path(str(SCRIPT)))
        result = run_cmd(f"{quoted} --help")
        self.assertEqual(result.returncode, 0)
        output = result.stdout
        self.assertIn("start [options]", output)
        self.assertIn("mark --session-dir", output)
        self.assertIn("stop --session-dir", output)
        self.assertIn("status --session-dir", output)
        self.assertIn("manifest.sha256", output)

    def test_mark_phase_validation(self) -> None:
        quoted_script = shlex.quote(to_bash_path(str(SCRIPT)))
        with tempfile.TemporaryDirectory(prefix="dw5934e-observer-test-") as temp_dir:
            bash_temp = shlex.quote(to_bash_path(temp_dir))
            start = run_cmd(
                f"{quoted_script} start --once --interval 1 --root-dir {bash_temp}"
            )
            self.assertEqual(start.returncode, 0, start.stdout + start.stderr)

            session_path = None
            for line in start.stdout.splitlines():
                if line.startswith("SESSION_DIR="):
                    session_path = line.split("=", 1)[1]
                    break
            self.assertIsNotNone(session_path, start.stdout)

            manifest_output = run_cmd(f"cat {shlex.quote(session_path + '/manifest.json')}")
            self.assertEqual(manifest_output.returncode, 0, manifest_output.stdout + manifest_output.stderr)
            data = json.loads(manifest_output.stdout)
            self.assertIn("snapshots", data)
            self.assertGreaterEqual(len(data["snapshots"]), 1)
            self.assertIn("markers", data)

            mark_bad = run_cmd(
                f"{quoted_script} mark --session-dir {shlex.quote(session_path)} --phase invalid"
            )
            self.assertNotEqual(mark_bad.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
