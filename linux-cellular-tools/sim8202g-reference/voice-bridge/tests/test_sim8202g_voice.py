import os
import sys
import unittest
from io import StringIO
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import sim8202g_voice as voice


class FakeSerial(object):
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.pending = []
        self.writes = []
        self.timeout = 0.001
        self.closed = False

    @property
    def in_waiting(self):
        return len(self.pending)

    def write(self, raw):
        command = raw.decode("ascii").rstrip("\r")
        self.writes.append(command)
        self.pending.extend((line + "\r\n").encode("ascii") for line in self.responses.get(command, []))
        return len(raw)

    def flush(self):
        pass

    def readline(self):
        return self.pending.pop(0) if self.pending else b""

    def close(self):
        self.closed = True


class LateNakedFinalSerial(FakeSerial):
    """Every cleanup transaction sees only a naked late OK, never tagged state."""
    def write(self, raw):
        command = raw.decode("ascii").rstrip("\r")
        self.writes.append(command)
        if command in ("AT+CHUP", "AT+CPAS"):
            self.pending.append(b"OK\r\n")
        return len(raw)


class Port(object):
    def __init__(self, device, vid=None, pid=None, description=""):
        self.device, self.vid, self.pid, self.description = device, vid, pid, description
        self.hwid = "USB"


class VoiceToolTests(unittest.TestCase):
    def test_number_validation_rejects_injection_and_accepts_e164(self):
        self.assertEqual("+8613800138000", voice.validate_number("+8613800138000"))
        for bad in ("12", "123456789012345678901", "123;AT+CHUP", "123\rAT", "+12x"):
            with self.assertRaises(ValueError):
                voice.validate_number(bad)

    def test_transaction_ignores_echo_and_retains_urc(self):
        fake = FakeSerial({"AT+CSQ": ["AT+CSQ", "+MORING: 1", "+CSQ: 20,99", "OK"]})
        session = voice.ATSession("COM9", serial_instance=fake, timeout=.01)
        reply = session.command("AT+CSQ")
        self.assertTrue(reply.ok)
        self.assertEqual(["+CSQ: 20,99"], reply.lines)
        self.assertEqual(["+MORING: 1"], reply.urcs)
        self.assertEqual(["+MORING: 1"], session.urcs)

    def test_cme_error_is_terminal_not_a_timeout(self):
        fake = FakeSerial({"AT+CPIN?": ["+CME ERROR: SIM not inserted"]})
        reply = voice.ATSession("COM9", serial_instance=fake, timeout=.01).command("AT+CPIN?")
        self.assertEqual("+CME ERROR: SIM not inserted", reply.final)
        self.assertFalse(reply.ok)

    def test_pending_urc_is_not_thrown_away_when_drained(self):
        fake = FakeSerial({"AT": ["OK"]})
        fake.pending.append(b"RING\r\n")
        session = voice.ATSession("COM9", serial_instance=fake, timeout=.01)
        self.assertTrue(session.command("AT").ok)
        self.assertEqual(["RING"], session.urcs)

    def test_unknown_residual_line_is_preserved_instead_of_discarded(self):
        fake = FakeSerial({"AT": ["OK"]})
        fake.pending.append(b"+VENDOR-URC: state\r\n")
        session = voice.ATSession("COM9", serial_instance=fake, timeout=.01)
        session.command("AT")
        self.assertEqual(["+VENDOR-URC: state"], session.urcs)

    def test_registration_home_and_roaming(self):
        home = voice.registration_status("+CEREG: 2,1,ABCD,1234,7")
        roaming = voice.registration_status("+C5GREG: 2,5")
        self.assertTrue(home["registered"])
        self.assertIn("home", home["meaning"])
        self.assertTrue(roaming["registered"])
        self.assertIn("roaming", roaming["meaning"])

    def test_registration_sms_only_is_not_treated_as_normal_voice_registration(self):
        sms_only = voice.registration_status("+CREG: 2,6")
        self.assertEqual(6, sms_only["stat"])
        self.assertFalse(sms_only["registered"])
        self.assertIn("SMS-only", sms_only["meaning"])
        self.assertIn("not normal voice", sms_only["meaning"])

    def test_imei_is_redacted_from_all_rendered_response_text(self):
        reply = voice.ATResponse("ATI", ["SIMCOM", "IMEI: 861234567890123"], [], "OK")
        rendered = voice.response_text(reply)
        self.assertIn("IMEI: <redacted>", rendered)
        self.assertNotIn("861234567890123", rendered)
        self.assertEqual("prefix IMEI: <redacted> suffix",
                         voice.redact_sensitive("prefix IMEI: 861234567890123 suffix"))

    def test_probe_identity_output_redacts_imei(self):
        result = voice.ProbeResult("COM6", 0x1E0E, 0x9001, "SimTech HS-USB AT Port 9001")
        result.responses = {"AT": ["OK"], "ATI": ["SIMCOM", "IMEI: 861234567890123"]}
        output = StringIO()
        with mock.patch("sys.stdout", output):
            voice.print_probe_results([result], result)
        self.assertIn("IMEI: <redacted>", output.getvalue())
        self.assertNotIn("861234567890123", output.getvalue())

    def test_cereg_parser_and_documentation_do_not_claim_ims(self):
        result = voice.registration_status("+CEREG: 1")
        self.assertEqual(1, result["stat"])
        self.assertNotIn("IMS", result["meaning"])
        with open(os.path.join(os.path.dirname(HERE), "README.md"), encoding="utf-8") as handle:
            readme = handle.read()
        self.assertIn("not IMS registration", readme)

    def test_select_prefers_expected_usb_id_over_other_simcom_port(self):
        expected = voice.ProbeResult("COM8", 0x1E0E, 0x9001,
                                     "SimTech HS-USB AT Port 9001")
        expected.responses = {"AT": ["OK"], "ATI": ["SIMCOM SIM8202G-M2"]}
        other = voice.ProbeResult("COM3", 0x1234, 0x5678,
                                  "Other SIMCom AT Port")
        other.responses = {"AT": ["OK"], "ATI": ["SIMCOM SIM8202"]}
        self.assertIs(expected, voice.select_port([other, expected]))

    def test_select_prefers_at_port_description_over_lower_com_modem(self):
        modem = voice.ProbeResult("COM4", 0x1E0E, 0x9001, "SimTech HS-USB Modem 9001")
        modem.responses = {"AT": ["OK"], "ATI": ["SIMCOM SIM8202"]}
        at_port = voice.ProbeResult("COM6", 0x1E0E, 0x9001, "SimTech HS-USB AT Port 9001 (COM6)")
        at_port.responses = {"AT": ["OK"], "ATI": ["SIMCOM SIM8202"]}
        self.assertIs(at_port, voice.select_port([modem, at_port]))
        self.assertIn("AT Port", at_port.reason())

    def test_select_excludes_audio_nmea_and_diagnostics_auto_candidates(self):
        audio = voice.ProbeResult("COM3", 0x1E0E, 0x9001, "SimTech HS-USB Audio 9001")
        audio.responses = {"AT": ["OK"], "ATI": ["SIMCOM SIM8202"]}
        diagnostic = voice.ProbeResult("COM4", 0x1E0E, 0x9001, "SimTech HS-USB Diagnostics 9001")
        diagnostic.responses = {"AT": ["OK"], "ATI": ["SIMCOM SIM8202"]}
        nmea = voice.ProbeResult("COM5", 0x1E0E, 0x9001, "SimTech HS-USB NMEA 9001")
        nmea.responses = {"AT": ["OK"], "ATI": ["SIMCOM SIM8202"]}
        self.assertIsNone(voice.select_port([audio, diagnostic, nmea]))

    def test_select_refuses_generic_at_responder(self):
        generic = voice.ProbeResult("COM1", 0x1111, 0x2222)
        generic.responses = {"AT": ["OK"]}
        self.assertIsNone(voice.select_port([generic]))

    def test_opened_session_requires_positive_sim8202_identity(self):
        good = mock.Mock()
        good.command.return_value = voice.ATResponse(
            "ATI", ["Manufacturer: SIMCOM", "Model: SIMCOM_SIM8202G-M2"], [], "OK")
        self.assertTrue(voice.require_target_identity(good).ok)
        wrong = mock.Mock()
        wrong.command.return_value = voice.ATResponse(
            "ATI", ["Manufacturer: Other", "Model: Different Modem"], [], "OK")
        with self.assertRaises(RuntimeError):
            voice.require_target_identity(wrong)

    def test_list_candidates_probes_expected_id_first(self):
        ports = [
            Port("COM9", 2, 3, "Other AT Port"),
            Port("COM4", 0x1E0E, 0x9001, "SimTech HS-USB AT Port 9001"),
            Port("COM5", 0x1E0E, 0x9001, "SimTech HS-USB Audio 9001"),
            Port("COM7", 0x1E0E, 0x9001, "SimTech composite unknown"),
        ]
        seen = []
        def factory(device, baud, timeout):
            seen.append(device)
            return FakeSerial({"AT": ["OK"], "ATI": ["SIMCOM"], "AT+CGMR": ["FW", "OK"]})
        results = voice.list_candidates(ports=ports, serial_factory=factory, timeout=.01)
        self.assertEqual(["COM4"], seen)
        skipped = {item.device for item in results if item.skipped_reason}
        self.assertEqual({"COM5", "COM7", "COM9"}, skipped)

    def test_explicit_control_port_rejects_audio_diagnostics_nmea_unknown_and_absent(self):
        ports = [
            Port("COM5", 0x1E0E, 0x9001, "SimTech HS-USB Audio 9001"),
            Port("COM7", 0x1E0E, 0x9001, "SimTech HS-USB NMEA 9001"),
            Port("COM8", 0x1E0E, 0x9001, "SimTech HS-USB Diagnostics 9001"),
            Port("COM9", 0x1E0E, 0x9001, "SimTech composite unknown"),
        ]
        for name in ("COM5", "COM7", "COM8", "COM9", "COM99"):
            with self.assertRaises(RuntimeError):
                voice.require_explicit_control_port(name, ports=ports)

        wrong_device = Port("COM10", 0x1234, 0x5678, "Other USB Modem")
        with self.assertRaises(RuntimeError):
            voice.require_explicit_control_port("COM10", ports=[wrong_device])

    def test_explicit_control_port_accepts_at_and_modem_roles(self):
        ports = [
            Port("COM4", 0x1E0E, 0x9001, "SimTech HS-USB Modem 9001"),
            Port("COM6", 0x1E0E, 0x9001, "SimTech HS-USB AT Port 9001"),
        ]
        self.assertEqual("COM6", voice.require_explicit_control_port(r"\\.\COM6", ports=ports).device)
        self.assertEqual("COM4", voice.require_explicit_control_port("COM4", ports=ports).device)

    def test_dial_failure_queries_ceer(self):
        fake = FakeSerial({"ATD12345;": ["NO CARRIER"], "AT+CEER": ["+CEER: 42", "OK"]})
        session = voice.ATSession("COM9", serial_instance=fake, timeout=.01)
        # NO CARRIER is preserved as an URC and is an immediate dial outcome.
        with mock.patch.object(voice, "ceer_after_failure", wraps=voice.ceer_after_failure) as ceer:
            code = voice.command_dial(session, "12345", call_timeout=.01)
        self.assertEqual(2, code)
        self.assertTrue(ceer.called)
        self.assertIn("AT+CEER", fake.writes)

    def test_no_carrier_is_preserved_and_finishes_a_dial(self):
        fake = FakeSerial({"ATD12345;": ["NO CARRIER"]})
        reply = voice.ATSession("COM9", serial_instance=fake, timeout=.01).command("ATD12345;")
        self.assertEqual("NO CARRIER", reply.final)
        self.assertEqual(["NO CARRIER"], reply.urcs)

    def test_keyboard_interrupt_dial_attempts_hangup(self):
        session = mock.Mock()
        session.command.side_effect = KeyboardInterrupt
        session.hangup.return_value = voice.ATResponse("AT+CHUP", [], [], "OK")
        self.assertEqual(130, voice.command_dial(session, "12345", call_timeout=.01))
        session.hangup.assert_called_once_with()

    def test_dial_timeout_attempts_hangup_and_requires_tagged_state(self):
        session = mock.Mock()
        session.command.side_effect = voice.ATTimeout("lost final response")
        session.hangup.return_value = voice.ATResponse("AT+CHUP", [], [], "OK")
        with mock.patch.object(voice, "ceer_after_failure"):
            self.assertEqual(2, voice.command_dial(session, "12345", call_timeout=.01))
        session.hangup.assert_called_once_with()

    def test_tagged_cpas_zero_confirms_call_idle(self):
        session = mock.Mock()
        session.hangup.return_value = voice.ATResponse("AT+CHUP", [], [], "OK")
        session.command.return_value = voice.ATResponse(
            "AT+CPAS", ["+CPAS: 0"], [], "OK")
        messages = []
        self.assertTrue(voice.best_effort_hangup(session, reporter=messages.append))
        self.assertIn("call idle confirmed", messages[-1])

    def test_answer_non_ok_requests_ceer(self):
        session = mock.Mock()
        session.command.return_value = voice.ATResponse("ATA", [], [], "ERROR")
        with mock.patch.object(voice, "ceer_after_failure") as ceer:
            self.assertEqual(2, voice.command_answer(session))
        ceer.assert_called_once_with(session)

    def test_answer_timeout_and_interrupt_attempt_hangup(self):
        for failure, expected in ((voice.ATTimeout("lost final response"), 2),
                                  (KeyboardInterrupt(), 130)):
            session = mock.Mock()
            session.command.side_effect = failure
            session.hangup.return_value = voice.ATResponse("AT+CHUP", [], [], "OK")
            with mock.patch.object(voice, "ceer_after_failure"):
                self.assertEqual(expected, voice.command_answer(session))
            session.hangup.assert_called_once_with()

    def test_late_naked_ok_cannot_confirm_hangup(self):
        fake = LateNakedFinalSerial()
        session = voice.ATSession("COM9", serial_instance=fake, timeout=.001)
        with self.assertRaises(voice.ATTimeout):
            session.command("ATD12345;", timeout=.001)
        messages = []
        self.assertFalse(voice.best_effort_hangup(session, reporter=messages.append))
        self.assertEqual(["ATD12345;", "AT+CHUP", "AT+CPAS", "AT+CPAS"], fake.writes)
        self.assertIn("NOT confirmed", messages[-1])

    def test_monitor_initializes_fresh_session_before_waiting_for_urcs(self):
        session = mock.Mock()
        session.initialize.return_value = [("AT+MORING=1", mock.Mock(ok=True))]
        session.read_urc.side_effect = KeyboardInterrupt
        self.assertEqual(0, voice.command_monitor(session))
        session.initialize.assert_called_once_with()

    def test_close_is_idempotent(self):
        fake = FakeSerial()
        session = voice.ATSession("COM9", serial_instance=fake)
        session.close()
        session.close()
        self.assertTrue(fake.closed)


if __name__ == "__main__":
    unittest.main()
