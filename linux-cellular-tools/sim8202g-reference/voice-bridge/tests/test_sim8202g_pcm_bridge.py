import argparse
import io
import os
import sys
import threading
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import sim8202g_pcm_bridge as pcm  # noqa: E402
import sim8202g_voice as voice  # noqa: E402


class FakePort(object):
    def __init__(self, device, vid=None, pid=None, description="",
                 serial_number=None, location=None):
        self.device = device
        self.vid = vid
        self.pid = pid
        self.description = description
        self.serial_number = serial_number
        self.location = location


class FakeWriteSerial(object):
    def __init__(self, writes):
        self.writes = list(writes)
        self.write_calls = []
        self.index = 0

    def write(self, data):
        self.write_calls.append(data)
        if not self.writes:
            return len(data)
        count = self.writes[self.index % len(self.writes)]
        self.index += 1
        # emulate pyserial short-write semantics
        return max(0, min(len(data), int(count)))


class FakeSession(object):
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.command_calls = []
        self.closed = False

    def command(self, command, timeout=None):
        self.command_calls.append((command, timeout))
        return self.responses.get(
            command, voice.ATResponse(command, lines=["OK"], urcs=[], final="OK")
        )

    def read_urc(self, timeout=1.0):
        return None

    def hangup(self):
        self.command_calls.append(("AT+CHUP", 5))
        return voice.ATResponse("AT+CHUP", [], [], "OK")

    def open(self):
        return self

    def close(self):
        self.closed = True


class FakeClock(object):
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


class TimeoutAdvancingSession(FakeSession):
    """Fake AT session whose URC wait advances a deterministic monotonic clock."""
    def __init__(self, clock, responses=None):
        super(TimeoutAdvancingSession, self).__init__(responses=responses)
        self.clock = clock
        self.urc_timeouts = []

    def read_urc(self, timeout=1.0):
        self.urc_timeouts.append(timeout)
        self.clock.now += timeout
        return None


class CLCCAdvancingSession(TimeoutAdvancingSession):
    """Also make a CLCC transaction consume exactly its requested timeout."""
    def __init__(self, clock, responses=None, raise_clcc_timeout=False):
        super(CLCCAdvancingSession, self).__init__(clock, responses=responses)
        self.clcc_timeouts = []
        self.raise_clcc_timeout = raise_clcc_timeout

    def command(self, command, timeout=None):
        response = super(CLCCAdvancingSession, self).command(command, timeout=timeout)
        if command == "AT+CLCC":
            self.clcc_timeouts.append(timeout)
            self.clock.now += timeout
            if self.raise_clcc_timeout:
                raise voice.ATTimeout("CLCC final result timed out")
        return response


def _ok_response(command, lines=None, final="OK"):
    return voice.ATResponse(command, lines=lines or [], urcs=[], final=final)


class PCMBridgeTests(unittest.TestCase):
    def test_find_audio_port_prefers_expected_audio_and_does_not_probe_candidates(self):
        ports = [
            FakePort("COM3", vid=0x1234, pid=0x4321, description="Other audio function"),
            FakePort("COM7", vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID,
                     description="SIMTech HS-USB Audio 9001"),
            FakePort("COM8", vid=0x9999, pid=0x8888, description="USB Printer"),
        ]
        with mock.patch.object(pcm, "list_ports", None):
            selected = pcm.find_audio_port(ports=ports)
        self.assertEqual("COM7", selected)

    def test_select_at_port_filters_audio_interfaces_from_candidate_list(self):
        audio_port = FakePort("COM5", vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID,
                              description="SIMTech HS-USB Audio 9001")
        at_port = FakePort("COM6", vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID,
                           description="SIMTech HS-USB AT Port 9001")
        mock_ports = mock.Mock()
        mock_ports.comports.return_value = [audio_port, at_port]

        with mock.patch.object(pcm, "list_ports", mock_ports):
            with mock.patch.object(voice, "list_candidates") as list_candidates:
                list_candidates.return_value = [mock.Mock(device="COM6")]
                with mock.patch.object(voice, "select_port") as select_port:
                    with mock.patch.object(voice, "print_probe_results"):
                        select_port.return_value = mock.Mock(device="COM6")
                        selected = pcm.select_at_port(baud=115200, timeout=1.0)

        self.assertEqual("COM6", selected)
        self.assertEqual(["COM6"], [item.device for item in list_candidates.call_args.kwargs["ports"]])
        self.assertEqual(1, len(list_candidates.call_args.kwargs["ports"]))

    def test_select_at_port_only_probes_explicit_at_or_modem_ports(self):
        audio_port = FakePort("COM5", vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID,
                              description="SIMTech HS-USB Audio 9001")
        modem_port = FakePort("COM7", vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID,
                              description="SIMTech HS-USB Modem 9001")
        at_port = FakePort("COM6", vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID,
                           description="SIMTech HS-USB AT Port 9001")
        unknown_port = FakePort("COM8", vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID,
                                description="SIMTech HS-USB Composite 9001")
        mock_ports = mock.Mock()
        mock_ports.comports.return_value = [audio_port, at_port, modem_port, unknown_port]

        with mock.patch.object(pcm, "list_ports", mock_ports):
            with mock.patch.object(voice, "list_candidates") as list_candidates:
                list_candidates.return_value = [mock.Mock(device="COM6")]
                with mock.patch.object(voice, "select_port") as select_port:
                    with mock.patch.object(voice, "print_probe_results"):
                        select_port.return_value = mock.Mock(device="COM6")
                        selected = pcm.select_at_port(baud=115200, timeout=1.0)

        self.assertEqual("COM6", selected)
        candidate_devices = [item.device for item in list_candidates.call_args.kwargs["ports"]]
        self.assertEqual(["COM6", "COM7"], candidate_devices)

    def test_select_at_port_rejects_unknown_port_candidates(self):
        unknown_port = FakePort("COM5", vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID,
                                description="SIMTech HS-USB Composite 9001")
        mock_ports = mock.Mock()
        mock_ports.comports.return_value = [unknown_port]

        with mock.patch.object(pcm, "list_ports", mock_ports):
            with mock.patch.object(voice, "list_candidates") as list_candidates:
                with self.assertRaises(pcm.BridgeError):
                    pcm.select_at_port(baud=115200, timeout=1.0)
        list_candidates.assert_not_called()

    def test_find_audio_port_reports_ambiguity(self):
        ports = [
            FakePort("COM4", vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID,
                     description="SimTech HS-USB Audio 9001"),
            FakePort("COM5", vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID,
                     description="SimTech HS-USB Audio 9001 (secondary)"),
        ]
        with self.assertRaises(pcm.BridgeError):
            pcm.find_audio_port(ports=ports)

    def test_find_audio_port_does_not_auto_select_non_target_audio(self):
        ports = [FakePort("COM3", vid=0x1234, pid=0x4321,
                          description="Other vendor Audio COM")]
        with self.assertRaises(pcm.BridgeError):
            pcm.find_audio_port(ports=ports)

    def test_pcm_resampler_handles_odd_short_chunks_across_calls(self):
        resampler = pcm.PCMResampler(input_rate=16000, output_rate=8000)
        self.assertEqual(b"", resampler.convert(b"\x01"))
        self.assertEqual(1, len(resampler._tail))
        out = resampler.convert(b"\x02\x00\x03")
        self.assertIsInstance(out, (bytes, bytearray))
        self.assertEqual(0, len(resampler._tail))
        self.assertEqual(len(out) % 2, 0)
        self.assertGreater(len(out), 0)
        self.assertEqual(b"", resampler.convert(b"\x04"))
        self.assertEqual(1, len(resampler._tail))

    def test_pcm_aligner_keeps_byte_tail_for_next_feed(self):
        aligner = pcm.PCMAligner()
        self.assertEqual(b"", aligner.feed(b"\x01"))
        self.assertEqual(b"\x01\x02", aligner.feed(b"\x02\x03"))  # odd -> keep last byte
        self.assertEqual(b"\x03\x04", aligner.feed(b"\x04"))  # now aligned again

    def test_short_write_all_retries_on_partial_writes(self):
        serial = FakeWriteSerial(writes=(2, 2, 1))
        written, calls = pcm.short_write_all(serial, b"12345", stop_event=None)
        self.assertEqual(5, written)
        self.assertGreater(calls, 1)
        self.assertEqual(3, len(serial.write_calls))

    def test_short_write_all_fails_when_write_progress_stops(self):
        serial = FakeWriteSerial(writes=(0,))
        with self.assertRaises(pcm.BridgeError):
            pcm.short_write_all(serial, b"12345", stop_event=None)

    def _make_bridge_args(self, mode="dial"):
        return argparse.Namespace(
            at_port="COM9",
            baud=115200,
            timeout=0.5,
            mode=mode,
            number="12345" if mode == "dial" else None,
            call_timeout=1.0,
            audio_port="COM8",
            audio_baud=230400,
            input_device=None,
            output_device=None,
            host_rate=None,
            capture_rx=None,
            capture_tx=None,
            wait_timeout=0.1,
            clcc_poll=1.0,
            max_active_seconds=None,
            hangup_on_exit=False,
        )

    def _role_ports(self):
        return [
            FakePort("COM9", vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID,
                     description="SIMTech HS-USB AT Port 9001",
                     serial_number="TARGETSERIAL", location="1-2.3:x.2"),
            FakePort("COM8", vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID,
                     description="SIMTech HS-USB Audio 9001",
                     serial_number="TARGETSERIAL", location="1-2.3:x.4"),
        ]

    def _make_opened_mock_session(self):
        session = mock.Mock()
        session.open.return_value = session
        session.close = mock.Mock()
        session.command.return_value = voice.ATResponse(
            "ATI", ["Model: SIMCOM_SIM8202G-M2"], [], "OK")
        return session

    def test_command_bridge_dial_timeout_sends_best_effort_chup(self):
        fake_controller = mock.Mock()
        fake_controller._command_ok.side_effect = voice.ATTimeout("timed out")

        with mock.patch.object(pcm, "CallPCMController", return_value=fake_controller):
            with mock.patch.object(pcm.voice, "ATSession") as at_session:
                session = self._make_opened_mock_session()
                at_session.return_value = session
                result = pcm.command_bridge(self._make_bridge_args("dial"), ports=self._role_ports())

        self.assertEqual(2, result)
        fake_controller.cleanup.assert_called_once_with(hangup=True)
        self.assertEqual(1, session.close.call_count)

    def test_command_bridge_dial_keyboard_interrupt_sends_best_effort_chup(self):
        fake_controller = mock.Mock()
        fake_controller._command_ok.side_effect = KeyboardInterrupt

        with mock.patch.object(pcm, "CallPCMController", return_value=fake_controller):
            with mock.patch.object(pcm.voice, "ATSession") as at_session:
                session = self._make_opened_mock_session()
                at_session.return_value = session
                result = pcm.command_bridge(self._make_bridge_args("dial"), ports=self._role_ports())

        self.assertEqual(130, result)
        fake_controller.cleanup.assert_called_once_with(hangup=True)
        self.assertEqual(1, session.close.call_count)

    def test_command_bridge_answer_timeout_sends_best_effort_chup(self):
        fake_controller = mock.Mock()
        fake_controller._command_ok.side_effect = voice.ATTimeout("timed out")

        with mock.patch.object(pcm, "CallPCMController", return_value=fake_controller):
            with mock.patch.object(pcm.voice, "ATSession") as at_session:
                session = self._make_opened_mock_session()
                at_session.return_value = session
                result = pcm.command_bridge(self._make_bridge_args("answer"), ports=self._role_ports())

        self.assertEqual(2, result)
        fake_controller.cleanup.assert_called_once_with(hangup=True)
        self.assertEqual(1, session.close.call_count)

    def test_command_bridge_answer_keyboard_interrupt_sends_best_effort_chup(self):
        fake_controller = mock.Mock()
        fake_controller._command_ok.side_effect = KeyboardInterrupt

        with mock.patch.object(pcm, "CallPCMController", return_value=fake_controller):
            with mock.patch.object(pcm.voice, "ATSession") as at_session:
                session = self._make_opened_mock_session()
                at_session.return_value = session
                result = pcm.command_bridge(self._make_bridge_args("answer"), ports=self._role_ports())

        self.assertEqual(130, result)
        fake_controller.cleanup.assert_called_once_with(hangup=True)

    def test_command_bridge_existing_call_does_not_send_hangup_in_cleanup(self):
        fake_controller = mock.Mock()
        fake_controller.start_for_active_call.side_effect = pcm.BridgeError("no active call")
        fake_controller.call_request_attempted = False
        args = self._make_bridge_args("existing")
        args.call_timeout = 1.0

        with mock.patch.object(pcm, "CallPCMController", return_value=fake_controller):
            with mock.patch.object(pcm.voice, "ATSession") as at_session:
                session = self._make_opened_mock_session()
                at_session.return_value = session
                result = pcm.command_bridge(args, ports=self._role_ports())

        self.assertEqual(2, result)
        fake_controller.cleanup.assert_called_once_with(hangup=False)
        self.assertEqual(1, session.close.call_count)
        self.assertEqual(0, fake_controller._command_ok.call_count)

    def test_main_rejects_invalid_dial_number_before_session_and_audio_open(self):
        with mock.patch.object(pcm.voice, "ATSession") as at_session:
            with mock.patch.object(pcm, "CallPCMController") as controller_cls:
                result = pcm.main([
                    "--at-port", "COM9", "bridge", "--audio-port", "COM8", "--dial", "12"
                ])
                self.assertEqual(2, result)
                self.assertEqual(0, at_session.call_count)
                self.assertEqual(0, controller_cls.call_count)

    def test_max_active_seconds_parser_requires_finite_positive_value(self):
        parser = pcm.make_parser()
        default_args = parser.parse_args(["bridge", "--existing-call"])
        self.assertIsNone(default_args.max_active_seconds)
        args = parser.parse_args([
            "bridge", "--existing-call", "--max-active-seconds", "0.25"
        ])
        self.assertEqual(0.25, args.max_active_seconds)
        for invalid in ("0", "-0.1", "nan", "inf", "not-a-number"):
            with mock.patch("sys.stderr", new=io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args([
                        "bridge", "--existing-call", "--max-active-seconds", invalid
                    ])

    def test_command_bridge_passes_active_limit_to_controller_and_uses_normal_cleanup(self):
        fake_controller = mock.Mock()
        fake_controller._command_ok.return_value = _ok_response("ATD12345;")
        args = self._make_bridge_args("dial")
        args.max_active_seconds = 0.5

        with mock.patch.object(pcm, "CallPCMController", return_value=fake_controller):
            with mock.patch.object(pcm.voice, "ATSession") as at_session:
                session = self._make_opened_mock_session()
                at_session.return_value = session
                result = pcm.command_bridge(args, ports=self._role_ports())

        self.assertEqual(0, result)
        fake_controller.run_until_call_end.assert_called_once_with(
            1.0, max_active_seconds=0.5
        )
        # Dial/answer calls own the request, so this is the same cleanup path
        # that performs CHUP/call-idle confirmation and CPCMREG verification.
        fake_controller.cleanup.assert_called_once_with(hangup=True)

    def test_failed_dial_requests_pre_pcm_diagnostics_before_final_cleanup(self):
        fake_controller = mock.Mock()
        fake_controller.bridge_active_started_at = None
        fake_controller._command_ok.side_effect = pcm.BridgeError("dial rejected")
        args = self._make_bridge_args("dial")

        with mock.patch.object(pcm, "CallPCMController", return_value=fake_controller):
            with mock.patch.object(pcm.voice, "ATSession") as at_session:
                session = self._make_opened_mock_session()
                at_session.return_value = session
                result = pcm.command_bridge(args, ports=self._role_ports())

        self.assertEqual(2, result)
        diagnostics = mock.call.report_pre_pcm_failure_diagnostics()
        cleanup = mock.call.cleanup(hangup=True)
        self.assertIn(diagnostics, fake_controller.mock_calls)
        self.assertIn(cleanup, fake_controller.mock_calls)
        self.assertLess(fake_controller.mock_calls.index(diagnostics),
                        fake_controller.mock_calls.index(cleanup))

    def test_dial_failure_response_is_saved_as_safe_evidence_before_ceer_and_chup(self):
        number = "+15551234567"
        session = FakeSession({
            "ATD%s;" % number: voice.ATResponse(
                "ATD%s;" % number,
                lines=['+CLCC: 1,0,3,0,0,"%s",129' % number],
                urcs=["NO CARRIER"], final="NO CARRIER"
            ),
            "AT+CEER": _ok_response("AT+CEER", lines=["+CEER: network rejected call"]),
            "AT+CPAS": _ok_response("AT+CPAS", lines=["+CPAS: 0"]),
        })
        reporter = mock.Mock()
        controller = pcm.CallPCMController(session, reporter=reporter)

        with self.assertRaises(pcm.BridgeError):
            controller._command_ok("ATD%s;" % number, timeout=1.0,
                                   record_call_evidence=True)
        self.assertEqual("voice-call end indication", controller.last_call_evidence)
        controller.report_pre_pcm_failure_diagnostics()
        controller.cleanup(hangup=True)

        commands = [command for command, _ in session.command_calls]
        self.assertLess(commands.index("AT+CEER"), commands.index("AT+CHUP"))
        messages = " ".join(str(call.args[0]) for call in reporter.call_args_list)
        self.assertIn("voice-call end indication", messages)
        self.assertIn("AT+CEER: +CEER: network rejected call", messages)
        self.assertNotIn(number, messages)

    def test_dial_timeout_command_text_is_redacted_before_ceer_and_cleanup(self):
        number = "+15551234567"
        session = FakeSession({
            "ATI": _ok_response("ATI", lines=["Model: SIMCOM_SIM8202G-M2"]),
            "AT+CEER": _ok_response("AT+CEER", lines=["+CEER: request timed out"]),
            "AT+CPAS": _ok_response("AT+CPAS", lines=["+CPAS: 0"]),
        })
        original_command = session.command

        def command(command_name, timeout=None):
            if command_name == "ATD%s;" % number:
                session.command_calls.append((command_name, timeout))
                raise voice.ATTimeout("ATD%s; timed out after %.1f seconds" % (number, timeout))
            return original_command(command_name, timeout=timeout)

        session.command = command
        args = self._make_bridge_args("dial")
        args.number = number
        output = io.StringIO()
        with mock.patch.object(pcm.voice, "ATSession", return_value=session):
            with mock.patch("sys.stdout", new=output):
                result = pcm.command_bridge(args, ports=self._role_ports())

        self.assertEqual(2, result)
        commands = [command_name for command_name, _ in session.command_calls]
        self.assertLess(commands.index("AT+CEER"), commands.index("AT+CHUP"))
        rendered = output.getvalue()
        self.assertIn("AT+CEER: +CEER: request timed out", rendered)
        self.assertIn("call request did not return a final result", rendered)
        self.assertNotIn(number, rendered)
        self.assertNotIn("ATD%s;" % number, rendered)

    def test_wait_timeout_collects_ceer_and_safe_clcc_summary_before_owned_call_chup(self):
        responses = {
            "AT+CPCMREG=?": _ok_response("AT+CPCMREG=?", lines=["(0-1)"]),
            "AT+CPCMREG?": _ok_response("AT+CPCMREG?", lines=["+CPCMREG: 0"]),
            "AT+CEER": _ok_response("AT+CEER", lines=["+CEER: 42"]),
            "AT+CPAS": _ok_response("AT+CPAS", lines=["+CPAS: 0"]),
        }
        session = FakeSession(responses)
        reporter = mock.Mock()
        controller = pcm.CallPCMController(session, reporter=reporter)
        controller.owned_call = True
        # A raw CLCC row can carry a remote number.  The diagnostic must retain
        # only its state category, never that raw payload.
        controller.last_call_evidence = pcm.summarize_call_evidence([
            '+CLCC: 1,0,3,0,0,"+15551234567",129'
        ])

        with mock.patch.object(controller, "wait_for_active_call",
                               side_effect=pcm.BridgeError("timed out waiting for active call")):
            with self.assertRaises(pcm.BridgeError):
                controller.start_for_active_call({"audio_port": "COM8", "wait_timeout": 1.0})

        commands = [command for command, _ in session.command_calls]
        self.assertLess(commands.index("AT+CEER"), commands.index("AT+CHUP"))
        self.assertIn("AT+CPAS", commands)
        messages = " ".join(str(call.args[0]) for call in reporter.call_args_list)
        self.assertIn("AT+CEER: +CEER: 42", messages)
        self.assertIn("+CLCC reported no active-call state", messages)
        self.assertNotIn("15551234567", messages)

    def test_pre_pcm_ceer_failure_does_not_block_owned_call_cleanup(self):
        session = FakeSession({"AT+CPAS": _ok_response("AT+CPAS", lines=["+CPAS: 0"])})
        original_command = session.command

        def command(command_name, timeout=None):
            if command_name == "AT+CEER":
                session.command_calls.append((command_name, timeout))
                raise voice.ATTimeout("CEER timed out")
            return original_command(command_name, timeout=timeout)

        session.command = command
        reporter = mock.Mock()
        controller = pcm.CallPCMController(session, reporter=reporter)
        controller.report_pre_pcm_failure_diagnostics()
        controller.cleanup(hangup=True)

        self.assertIn(("AT+CEER", 5), session.command_calls)
        self.assertIn(("AT+CHUP", 5), session.command_calls)
        messages = " ".join(str(call.args[0]) for call in reporter.call_args_list)
        self.assertIn("AT+CEER unavailable", messages)
        self.assertTrue(controller.hangup_confirmed)

    def test_active_limit_expires_after_bridge_start_then_cleanup_hangs_up_and_confirms_states(self):
        clock = FakeClock(now=100.0)
        responses = {
            "AT+CPCMREG=?": _ok_response("AT+CPCMREG=?", lines=["(0-1)"]),
            "AT+CPCMREG?": _ok_response("AT+CPCMREG?", lines=["+CPCMREG: 0"]),
            "AT+CPCMREG=1": _ok_response("AT+CPCMREG=1"),
            "AT+CPCMREG=0": _ok_response("AT+CPCMREG=0"),
            "AT+CPAS": _ok_response("AT+CPAS", lines=["+CPAS: 0"]),
        }
        session = TimeoutAdvancingSession(clock, responses=responses)
        bridge = mock.Mock()
        bridge.stop_event = threading.Event()
        bridge.stats_snapshot.return_value = {
            "rx_bytes": 0, "tx_bytes": 0, "rx_dropped": 0,
            "tx_dropped": 0, "short_writes": 0,
        }
        reporter = mock.Mock()
        controller = pcm.CallPCMController(
            session, bridge_factory=mock.Mock(return_value=bridge), reporter=reporter,
            clock=clock
        )

        # The active-call evidence may arrive long after a dial/answer request.
        # The limit starts only once start_for_active_call has fully started the
        # local bridge, at the clock's then-current value.
        with mock.patch.object(controller, "wait_for_active_call", return_value=True):
            controller.start_for_active_call({"audio_port": "COM8", "wait_timeout": 1.0})
        self.assertEqual(100.0, controller.bridge_active_started_at)
        controller.run_until_call_end(poll_seconds=10.0, max_active_seconds=0.5)

        self.assertEqual([0.25, 0.25], session.urc_timeouts)
        messages = " ".join(str(call.args[0]) for call in reporter.call_args_list)
        self.assertIn("Maximum active-call duration reached", messages)
        self.assertNotIn("AT+CLCC", [command for command, _ in session.command_calls])

        # Expiry only returns from the controller loop.  The caller's normal
        # cleanup stops local audio, CHUPs owned calls, verifies +CPAS: 0, then
        # verifies +CPCMREG: 0; no process-kill shortcut is involved.
        controller.cleanup(hangup=True)
        commands = [command for command, _ in session.command_calls]
        self.assertIn("AT+CHUP", commands)
        self.assertIn("AT+CPAS", commands)
        self.assertIn("AT+CPCMREG=0", commands)
        self.assertTrue(controller.hangup_confirmed)
        self.assertTrue(controller.pcm_disable_confirmed)
        bridge.stop.assert_called_once_with()

    def test_active_limit_bounds_in_flight_clcc_to_remaining_duration(self):
        clock = FakeClock()
        session = CLCCAdvancingSession(clock, responses={
            "AT+CLCC": _ok_response(
                "AT+CLCC", lines=["+CLCC: 1,0,0,0,0,0,0"]
            ),
        })
        bridge = mock.Mock()
        bridge.stop_event = threading.Event()
        bridge.stats_snapshot.return_value = {
            "rx_bytes": 0, "tx_bytes": 0, "rx_dropped": 0,
            "tx_dropped": 0, "short_writes": 0,
        }
        reporter = mock.Mock()
        controller = pcm.CallPCMController(session, reporter=reporter, clock=clock)
        controller.bridge = bridge
        controller.bridge_active_started_at = clock()

        # The first URC read consumes 0.25 s, leaving only 0.25 s when the
        # CLCC liveness poll begins.  It must not use its usual five-second
        # timeout and therefore cannot delay the normal cleanup path by five
        # seconds beyond the caller's explicit maximum.
        controller.run_until_call_end(poll_seconds=0.0, max_active_seconds=0.5)

        self.assertEqual([0.25], session.clcc_timeouts)
        self.assertEqual(0.5, clock())
        messages = " ".join(str(call.args[0]) for call in reporter.call_args_list)
        self.assertIn("Maximum active-call duration reached", messages)

    def test_active_limit_treats_bounded_clcc_timeout_at_deadline_as_normal_expiry(self):
        clock = FakeClock()
        session = CLCCAdvancingSession(clock, raise_clcc_timeout=True)
        bridge = mock.Mock()
        bridge.stop_event = threading.Event()
        bridge.stats_snapshot.return_value = {
            "rx_bytes": 0, "tx_bytes": 0, "rx_dropped": 0,
            "tx_dropped": 0, "short_writes": 0,
        }
        reporter = mock.Mock()
        controller = pcm.CallPCMController(session, reporter=reporter, clock=clock)
        controller.bridge = bridge
        controller.bridge_active_started_at = clock()

        # A modem that never supplies the CLCC final result must time out on
        # the remaining budget, then return to the caller's normal cleanup
        # path as an expiry instead of turning into a five-second overrun.
        controller.run_until_call_end(poll_seconds=0.0, max_active_seconds=0.5)

        self.assertEqual([0.25], session.clcc_timeouts)
        messages = " ".join(str(call.args[0]) for call in reporter.call_args_list)
        self.assertIn("Maximum active-call duration reached", messages)

    def test_command_bridge_does_not_send_cpcmreg_1_before_active_call_evidence(self):
        calls = []
        fake_controller = mock.Mock()

        def command_ok(cmd, timeout=None, **kwargs):
            calls.append((cmd, timeout))
            return _ok_response(cmd)

        fake_controller._command_ok.side_effect = command_ok
        fake_controller.start_for_active_call.side_effect = pcm.BridgeError("no voice evidence yet")
        fake_controller.cleanup.return_value = None

        with mock.patch.object(pcm, "CallPCMController", return_value=fake_controller):
            with mock.patch.object(pcm.voice, "ATSession") as at_session:
                session = self._make_opened_mock_session()
                at_session.return_value = session
                args = argparse.Namespace(
                    at_port="COM9",
                    baud=115200,
                    timeout=0.5,
                    mode="dial",
                    number="12345",
                    call_timeout=1.0,
                    audio_port="COM8",
                    audio_baud=230400,
                    input_device=None,
                    output_device=None,
                    host_rate=None,
                    capture_rx=None,
                    capture_tx=None,
                    wait_timeout=0.1,
                    clcc_poll=1.0,
                    hangup_on_exit=False,
                )
                result = pcm.command_bridge(args, ports=self._role_ports())

        self.assertEqual(2, result)
        self.assertEqual([("ATD12345;", 1.0)], calls[:1])
        self.assertNotIn("AT+CPCMREG=1", [cmd for cmd, _ in calls])
        fake_controller.cleanup.assert_called_once()

    def test_command_bridge_answer_mode_also_waits_for_active_before_pcm_enable(self):
        calls = []
        fake_controller = mock.Mock()

        def command_ok(cmd, timeout=None, **kwargs):
            calls.append((cmd, timeout))
            return _ok_response(cmd)

        fake_controller._command_ok.side_effect = command_ok
        fake_controller.start_for_active_call.side_effect = pcm.BridgeError("still no active call")
        fake_controller.cleanup.return_value = None

        with mock.patch.object(pcm, "CallPCMController", return_value=fake_controller):
            with mock.patch.object(pcm.voice, "ATSession") as at_session:
                session = self._make_opened_mock_session()
                at_session.return_value = session
                args = argparse.Namespace(
                    at_port="COM9",
                    baud=115200,
                    timeout=0.5,
                    mode="answer",
                    number=None,
                    call_timeout=1.0,
                    audio_port="COM8",
                    audio_baud=230400,
                    input_device=None,
                    output_device=None,
                    host_rate=None,
                    capture_rx=None,
                    capture_tx=None,
                    wait_timeout=0.1,
                    clcc_poll=1.0,
                    hangup_on_exit=False,
                )
                result = pcm.command_bridge(args, ports=self._role_ports())

        self.assertEqual(2, result)
        self.assertEqual([("ATA", 1.0)], calls[:1])
        self.assertNotIn("AT+CPCMREG=1", [cmd for cmd, _ in calls])
        fake_controller.cleanup.assert_called_once()

    def test_start_for_active_call_cpcmreg_one_failure_still_attempts_cpcmreg_zero(self):
        def run_with_mode(mode):
            command_calls = []

            def command(cmd, timeout=None):
                command_calls.append((cmd, timeout))
                if cmd == "AT+CPCMREG=1":
                    if mode == "timeout":
                        raise voice.ATTimeout("timed out")
                    return _ok_response(cmd, final="ERROR")
                if cmd == "AT+CPCMREG=?":
                    return _ok_response(cmd, lines=["(0-1)"], final="OK")
                if cmd == "AT+CPCMREG?":
                    return _ok_response(cmd, lines=["+CPCMREG: 0"], final="OK")
                return _ok_response(cmd)

            session = mock.Mock()
            session.command.side_effect = command
            session.read_urc.return_value = None
            controller = pcm.CallPCMController(session, reporter=mock.Mock())

            with mock.patch.object(controller, "wait_for_active_call", return_value=True):
                if mode == "timeout":
                    with self.assertRaises(voice.ATTimeout):
                        controller.start_for_active_call({"audio_port": "COM8", "wait_timeout": 1.0})
                else:
                    with self.assertRaises(pcm.BridgeError):
                        controller.start_for_active_call({"audio_port": "COM8", "wait_timeout": 1.0})

            self.assertIn("AT+CPCMREG=1", [cmd for cmd, _ in command_calls])
            self.assertIn("AT+CPCMREG=0", [cmd for cmd, _ in command_calls])
            self.assertEqual("AT+CPCMREG=?", command_calls[0][0])
            self.assertEqual("AT+CPCMREG?", command_calls[1][0])
            self.assertEqual("AT+CPCMREG?", command_calls[-1][0])
            self.assertTrue(controller.pcm_disable_confirmed)

        run_with_mode("timeout")
        run_with_mode("error")

    def test_cleanup_warns_when_cpcmreg_zero_not_confirmed(self):
        for mode in ("error", "timeout"):
            command_calls = []
            reporter = mock.Mock()

            def command(cmd, timeout=None):
                command_calls.append((cmd, timeout))
                if cmd == "AT+CPCMREG=0":
                    if mode == "error":
                        return _ok_response(cmd, lines=["1"], final="ERROR")
                    raise voice.ATTimeout("timed out")
                return _ok_response(cmd)

            session = mock.Mock()
            session.command.side_effect = command
            session.read_urc.return_value = None
            controller = pcm.CallPCMController(session, reporter=reporter)
            controller.pcm_enabled = True
            controller.pcm_enable_attempted = True
            controller.cleanup(hangup=False)

            self.assertIn(("AT+CPCMREG=0", 5), command_calls)
            messages = "".join(str(item[0]) for item in reporter.call_args_list)
            self.assertIn("CPCMREG=0", messages)
            self.assertTrue("failed" in messages.lower() or "not confirmed" in messages.lower())

    def test_start_for_active_call_rejects_preexisting_cpcmreg_enabled_state(self):
        command_calls = []

        def command(cmd, timeout=None):
            command_calls.append((cmd, timeout))
            if cmd == "AT+CPCMREG=?":
                return _ok_response(cmd, lines=["(0-1)"], final="OK")
            if cmd == "AT+CPCMREG?":
                return _ok_response(cmd, lines=["+CPCMREG: 1"], final="OK")
            raise AssertionError("unexpected command: %s" % cmd)

        session = mock.Mock()
        session.command.side_effect = command
        session.read_urc.return_value = None
        controller = pcm.CallPCMController(session, reporter=mock.Mock())
        with self.assertRaises(pcm.BridgeError):
            with mock.patch.object(controller, "wait_for_active_call", return_value=True):
                controller.start_for_active_call({"audio_port": "COM8", "wait_timeout": 1.0})

        self.assertEqual(["AT+CPCMREG=?", "AT+CPCMREG?"], [cmd for cmd, _ in command_calls])

    def test_wait_for_active_call_prioritizes_voice_end_over_stale_clcc_active(self):
        def command(cmd, timeout=None):
            if cmd == "AT+CLCC":
                return voice.ATResponse(
                    "AT+CLCC", lines=["+CLCC: 1,0,0,0,0,0,0"],
                    urcs=["VOICE CALL: END"], final="OK"
                )
            return _ok_response(cmd)

        session = mock.Mock()
        session.command.side_effect = command
        session.read_urc.return_value = None
        controller = pcm.CallPCMController(session, reporter=mock.Mock())

        with self.assertRaises(pcm.BridgeError):
            controller.wait_for_active_call(timeout=0.2, poll_seconds=0.0)

    def test_callpcmcontroller_enables_cpcmreg_after_active_and_cleans_up_on_close(self):
        responses = {
            "AT+CPCMREG=?": _ok_response("AT+CPCMREG=?", lines=["(0-1)"], final="OK"),
            "AT+CPCMREG?": _ok_response("AT+CPCMREG?", lines=["+CPCMREG: 0"], final="OK"),
            "AT+CPCMREG=0": _ok_response("AT+CPCMREG=0", final="OK"),
            "AT+CPCMREG=1": _ok_response("AT+CPCMREG=1", final="OK"),
        }
        session = FakeSession(responses)
        fake_bridge = mock.Mock()
        fake_bridge.start.return_value = None
        fake_bridge.stop.return_value = None

        controller = pcm.CallPCMController(session, bridge_factory=mock.Mock(return_value=fake_bridge))
        with mock.patch.object(controller, "wait_for_active_call", return_value=True):
            active_bridge = controller.start_for_active_call({
                "audio_port": "COM8",
                "wait_timeout": 1.0,
            })

        self.assertIs(active_bridge, fake_bridge)
        self.assertTrue(controller.pcm_enabled)
        fake_bridge.start.assert_called_once_with()
        self.assertIn(("AT+CPCMREG=1", 5), session.command_calls)

        fake_bridge_exception = mock.Mock()
        fake_bridge_exception.start.side_effect = RuntimeError("audio worker failed")
        fail_session = FakeSession(responses)
        fail_controller = pcm.CallPCMController(
            fail_session, bridge_factory=mock.Mock(return_value=fake_bridge_exception)
        )
        with mock.patch.object(fail_controller, "wait_for_active_call", return_value=True):
            with self.assertRaises(RuntimeError):
                fail_controller.start_for_active_call({
                    "audio_port": "COM8",
                    "wait_timeout": 1.0,
                })
        fail_commands = [command for command, _ in fail_session.command_calls]
        self.assertIn("AT+CPCMREG=1", fail_commands)
        self.assertEqual("AT+CPCMREG?", fail_commands[-1])
        self.assertFalse(fail_controller.pcm_enabled)
        self.assertTrue(fail_controller.pcm_disable_confirmed)

        controller.cleanup(hangup=False)
        self.assertEqual("AT+CPCMREG?", [command for command, _ in session.command_calls][-1])
        self.assertTrue(controller.pcm_disable_confirmed)

    def test_reject_known_audio_as_at_port(self):
        audio_port = FakePort("COM6", description="SIMTech HS-USB Audio 9001",
                              vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID)
        with self.assertRaises(pcm.BridgeError):
            pcm.reject_known_audio_as_at_port("COM6", ports=[audio_port])

    def test_reject_known_audio_as_at_port_treats_windows_alias_equivalent(self):
        audio_port = FakePort("COM6", description="SIMTech HS-USB Audio 9001",
                              vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID)
        for port_name in ("COM6", r"\\.\COM6"):
            with self.assertRaises(pcm.BridgeError):
                pcm.reject_known_audio_as_at_port(port_name, ports=[audio_port])

    def test_explicit_audio_port_requires_positive_audio_role_and_presence(self):
        ports = [
            FakePort("COM5", description="SIMTech HS-USB Audio 9001",
                     vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID),
            FakePort("COM8", description="SIMTech HS-USB Diagnostics 9001",
                     vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID),
            FakePort("COM9", description="SIMTech composite unknown",
                     vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID),
        ]
        pcm.require_explicit_audio_port_role(r"\\.\COM5", ports=ports)
        for name in ("COM8", "COM9", "COM99"):
            with self.assertRaises(pcm.BridgeError):
                pcm.require_explicit_audio_port_role(name, ports=ports)

    def test_wrong_audio_role_fails_before_at_session_or_call_request(self):
        args = self._make_bridge_args("dial")
        ports = [
            FakePort("COM9", description="SIMTech HS-USB AT Port 9001",
                     vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID),
            FakePort("COM8", description="SIMTech HS-USB Diagnostics 9001",
                     vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID),
        ]
        with mock.patch.object(pcm.voice, "ATSession") as at_session:
            with mock.patch.object(pcm, "CallPCMController") as controller:
                with self.assertRaises(pcm.BridgeError):
                    pcm.command_bridge(args, ports=ports)
        at_session.assert_not_called()
        controller.assert_not_called()

    def test_correct_role_with_wrong_usb_identity_is_rejected(self):
        other_at = FakePort("COM9", description="Other USB AT Port",
                            vid=0x1234, pid=0x5678)
        other_audio = FakePort("COM8", description="Other USB Audio",
                               vid=0x1234, pid=0x5678)
        with self.assertRaises(pcm.BridgeError):
            pcm.require_explicit_at_port_role("COM9", ports=[other_at])
        with self.assertRaises(pcm.BridgeError):
            pcm.require_explicit_audio_port_role("COM8", ports=[other_audio])

    def test_cross_device_at_and_audio_pair_is_rejected_before_session(self):
        args = self._make_bridge_args("dial")
        ports = [
            FakePort("COM9", description="SIMTech HS-USB AT Port 9001",
                     vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID,
                     serial_number="SAME-PLACEHOLDER", location="1-2.3:x.2"),
            FakePort("COM8", description="SIMTech HS-USB Audio 9001",
                     vid=voice.EXPECTED_VID, pid=voice.EXPECTED_PID,
                     serial_number="SAME-PLACEHOLDER", location="1-9.4:x.4"),
        ]
        with mock.patch.object(pcm.voice, "ATSession") as at_session:
            with self.assertRaises(pcm.BridgeError):
                pcm.command_bridge(args, ports=ports)
        at_session.assert_not_called()

    def test_audio_baud_rejects_old_115200_default_before_open(self):
        factory = mock.Mock()
        with self.assertRaises(pcm.BridgeError):
            pcm.open_audio_serial("COM5", baud=115200, serial_factory=factory)
        factory.assert_not_called()
        self.assertEqual(921600, pcm.DEFAULT_AUDIO_BAUD)
        self.assertEqual(230400, pcm.MIN_AUDIO_BAUD)

    def test_cleanup_reports_non_ok_chup_as_unconfirmed_call_state(self):
        session = mock.Mock()
        session.hangup.return_value = voice.ATResponse("AT+CHUP", [], [], "ERROR")
        session.command.return_value = voice.ATResponse(
            "AT+CPAS", ["+CPAS: 4"], [], "OK")
        reporter = mock.Mock()
        controller = pcm.CallPCMController(session, reporter=reporter)
        controller.cleanup(hangup=True)
        session.hangup.assert_called_once_with()
        messages = " ".join(str(call.args[0]) for call in reporter.call_args_list)
        self.assertIn("call state is not confirmed", messages.lower())

    def test_naked_ok_does_not_confirm_cpcmreg_disabled(self):
        session = mock.Mock()
        session.command.return_value = voice.ATResponse("unknown", [], [], "OK")
        reporter = mock.Mock()
        controller = pcm.CallPCMController(session, reporter=reporter)
        controller.pcm_enabled = True
        controller.pcm_enable_attempted = True
        controller.cleanup(hangup=False)
        commands = [call.args[0] for call in session.command.call_args_list]
        self.assertEqual(["AT+CPCMREG=0", "AT+CPCMREG?", "AT+CPCMREG?"], commands)
        self.assertFalse(controller.pcm_disable_confirmed)
        self.assertTrue(controller.pcm_enable_attempted)

    def test_naked_zero_does_not_confirm_cpcmreg_disabled(self):
        session = mock.Mock()

        def command(cmd, timeout=None):
            if cmd == "AT+CPCMREG=0":
                return voice.ATResponse(cmd, [], [], "OK")
            return voice.ATResponse(cmd, ["0"], [], "OK")

        session.command.side_effect = command
        reporter = mock.Mock()
        controller = pcm.CallPCMController(session, reporter=reporter)
        controller.pcm_enabled = True
        controller.pcm_enable_attempted = True
        controller.cleanup(hangup=False)
        self.assertFalse(controller.pcm_disable_confirmed)
        self.assertTrue(controller.pcm_enable_attempted)
        messages = " ".join(str(call.args[0]) for call in reporter.call_args_list)
        self.assertIn("state not confirmed", messages)


if __name__ == "__main__":
    unittest.main()
