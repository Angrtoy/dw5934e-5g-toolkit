"""Offline unit tests: no GTK import, pkexec, modem node, or actual backend."""
from __future__ import annotations
import pathlib
import sys
import threading
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dw5934e_voice_gui as gui

class FakeProcess:
    def __init__(self, argv, **kwargs):
        self.argv, self.kwargs, self.returncode = argv, kwargs, 0
    def communicate(self):
        return "CALL_COUNT=0\n", ""

class GuiTests(unittest.TestCase):
    def test_parse_status(self):
        calls = gui.parse_status("CALL_COUNT=2\nCALL id=7 state=3 type=0 direction=1 mode=9\nCALL id=8 state=4 type=1 direction=0 mode=9\n")
        self.assertEqual([call.id for call in calls], [7, 8])
        with self.assertRaises(ValueError): gui.parse_status("CALL_COUNT=1\n")
        with self.assertRaises(ValueError): gui.parse_status("CALL_COUNT=2\nCALL id=7 state=3 type=0 direction=1 mode=9\n")

    def test_acceptance_and_input(self):
        self.assertEqual(gui.parse_accepted("dial", "DIAL_ACCEPTED call_id=7\n"), 7)
        with self.assertRaises(ValueError): gui.parse_accepted("dial", "ANSWER_ACCEPTED call_id=7\n")
        self.assertEqual(gui.validate_number("13800138000"), "13800138000")
        for number in ("12", "12a", "+8613800138000", "1" * 33):
            with self.assertRaises(ValueError): gui.validate_number(number)
        self.assertEqual(gui.validate_id("255"), 255)
        for call_id in ("0", "256", "7;id"):
            with self.assertRaises(ValueError): gui.validate_id(call_id)

    def test_argv_never_elevates_configurable_path(self):
        self.assertEqual(gui.command_argv(gui.DEFAULT_BACKEND, True, ["status"]), ["/usr/bin/pkexec", gui.DEFAULT_BACKEND, "status"])
        self.assertEqual(gui.command_argv("/tmp/mock", False, ["status"]), ["/tmp/mock", "status"])
        with self.assertRaises(ValueError): gui.command_argv("/tmp/mock", True, ["status"])
        with self.assertRaises(ValueError): gui.command_argv("relative", False, ["status"])

    def test_busy_gate_and_shell_false(self):
        ready, release, results, processes = threading.Event(), threading.Event(), [], []
        class Blocking(FakeProcess):
            def __init__(self, argv, **kwargs):
                super().__init__(argv, **kwargs)
                processes.append(self)
            def communicate(self):
                ready.set(); release.wait(2); return super().communicate()
        runner = gui.Runner("/tmp/mock", False, Blocking)
        self.assertTrue(runner.start(["status"], lambda r, e: results.append((r, e))))
        self.assertTrue(ready.wait(1))
        self.assertFalse(runner.start(["status"], lambda r, e: None))
        release.set()
        for _ in range(100):
            if results: break
            threading.Event().wait(.01)
        result, error = results[0]
        self.assertIsNone(error)
        self.assertEqual(result.argv, ("/tmp/mock", "status"))
        self.assertIs(result.argv[0] == "sh", False)
        self.assertIs(processes[0].kwargs["shell"], False)

    def test_cli_guard_and_selftest(self):
        self.assertEqual(gui.main(["--self-test"]), 0)
        with self.assertRaises(SystemExit): gui.parse_args(["--backend", "/tmp/mock"])
        with self.assertRaises(SystemExit): gui.parse_args(["--no-pkexec"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
