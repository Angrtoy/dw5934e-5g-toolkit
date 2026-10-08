#!/usr/bin/env python3
"""Conservative AT-call controller for a SIMCom SIM8202G-M2 modem.

This program deliberately contains no modem configuration, NV, firmware, or
USB-composition commands.  It is usable on Windows with Python 3.8 and
pyserial 3.5 or newer.
"""
from __future__ import print_function

import argparse
import re
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # Lets the protocol/parser unit tests run without hardware.
    serial = None
    list_ports = None


EXPECTED_VID = 0x1E0E
EXPECTED_PID = 0x9001
NUMBER_RE = re.compile(r"^\+?[0-9]{3,20}$")
IMEI_RE = re.compile(r"(\bIMEI\s*:\s*)\d{14,16}\b", re.I)
TERMINALS_OK = ("OK",)
TERMINALS_ERROR = ("ERROR", "+CME ERROR")
CALL_FAILURE_URCS = ("NO CARRIER", "BUSY", "NO ANSWER", "NO DIALTONE")
CALL_PROGRESS_URCS = ("RING", "+MORING", "CONNECT")
# These voice-state notifications are distinct from an AT command's final OK.
# Keeping them in the URC queue lets a call/audio state machine give END
# precedence over a stale +CLCC response that happened to interleave a query.
VOICE_CALL_URC_PREFIXES = ("VOICE CALL: BEGIN", "VOICE CALL: END")

INITIALIZATION_COMMANDS = (
    "AT", "ATE0", "AT+CMEE=2", "AT+MORING=1", "AT+CVHU=0",
    "AT+CREG=2", "AT+CGREG=2", "AT+CEREG=2", "AT+C5GREG=2",
)
STATUS_COMMANDS = (
    ("identity", "ATI"), ("firmware", "AT+CGMR"), ("SIM", "AT+CPIN?"),
    ("signal", "AT+CSQ"), ("operator", "AT+COPS?"),
    ("CS registration", "AT+CREG?"), ("PS registration", "AT+CGREG?"),
    ("EPS registration", "AT+CEREG?"), ("5GS registration", "AT+C5GREG?"),
    ("network info", "AT+CNWINFO?"), ("calls", "AT+CLCC"),
)


class ATError(Exception):
    """An AT command reached an error final result."""


class ATTimeout(Exception):
    """An AT command did not produce a final result in time."""


class ATResponse(object):
    def __init__(self, command, lines=None, urcs=None, final=None):
        self.command = command
        self.lines = lines or []
        self.urcs = urcs or []
        self.final = final

    @property
    def ok(self):
        return self.final == "OK"


def validate_number(number):
    """Return a phone number safe to interpolate in ``ATD<number>;``."""
    if not isinstance(number, str) or not NUMBER_RE.fullmatch(number):
        raise ValueError("number must be an optional '+' followed by 3-20 digits")
    return number


def redact_sensitive(text):
    """Redact modem IMEI labels before anything is shown to the user/log."""
    return IMEI_RE.sub(r"\1<redacted>", text)


def is_urc(line):
    """Classify call-related unsolicited result codes without losing them."""
    clean = line.strip().upper()
    return (clean in CALL_FAILURE_URCS or clean in CALL_PROGRESS_URCS or
            clean.startswith("+MORING:") or clean.startswith("+CIEV:") or
            any(clean.startswith(prefix) for prefix in VOICE_CALL_URC_PREFIXES))


def registration_status(line):
    """Parse a +CREG/+CGREG/+CEREG/+C5GREG response into a safe summary.

    The return value intentionally says *cellular* registration.  It never
    presents a CEREG result as IMS registration, because the two are distinct.
    """
    match = re.match(r"^\+(?:C|CG|CE|C5G)REG:\s*(.+)$", line.strip(), re.I)
    if not match:
        return None
    fields = [part.strip() for part in match.group(1).split(",")]
    try:
        # Query responses may be <stat> or <n>,<stat>[,...].
        stat = int(fields[1] if len(fields) > 1 else fields[0])
    except (IndexError, ValueError):
        return None
    meaning = {
        0: "not registered; not searching",
        1: "registered (home network)",
        2: "not registered; searching",
        3: "registration denied",
        4: "unknown",
        5: "registered (roaming)",
        # 3GPP TS 27.007 reserves 6 for SMS-only registration.  Do not treat
        # it as ordinary voice service merely because the home PLMN is known.
        6: "SMS-only home; not normal voice registration",
    }.get(stat, "unrecognized registration status")
    return {"stat": stat, "meaning": meaning, "registered": stat in (1, 5)}


class ATSession(object):
    """A small, synchronous serial AT transaction layer.

    URCs observed while a transaction is awaiting a final result are appended
    to ``urcs`` and also returned in that response.  They are not discarded as
    noise merely because another command is in progress.
    """
    def __init__(self, port, baud=115200, timeout=3.0, serial_instance=None):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.ser = serial_instance
        self.urcs = []
        self.closed = False

    def open(self):
        if self.ser is not None:
            return self
        if serial is None:
            raise RuntimeError("pyserial is required: python -m pip install pyserial>=3.5")
        self.ser = serial.Serial(self.port, self.baud, timeout=0.15,
                                 write_timeout=2)
        return self

    def close(self):
        """Close safely even when cleanup paths invoke it more than once."""
        if self.closed:
            return
        self.closed = True
        ser, self.ser = self.ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    def __enter__(self):
        return self.open()

    def __exit__(self, exc_type, exc, tb):
        self.close()

    @staticmethod
    def _decode(raw):
        return raw.decode("utf-8", "replace").strip()

    def _remember_urc(self, line):
        if line and is_urc(line):
            self.urcs.append(line)
            return True
        return False

    def drain(self):
        """Move already pending input to the URC queue before a command."""
        if self.ser is None:
            return []
        drained = []
        # A finite bound prevents a noisy port from starving a user command.
        for _ in range(128):
            waiting = getattr(self.ser, "in_waiting", 0)
            if not waiting:
                break
            raw = self.ser.readline()
            if not raw:
                break
            line = self._decode(raw)
            if line:
                drained.append(line)
                # Before a command is sent there is no reliable request/reply
                # context for deciding whether an unfamiliar line is an URC.
                # Keep every residual line rather than silently losing a URC.
                if not self._remember_urc(line):
                    self.urcs.append(line)
        return drained

    def command(self, command, timeout=None):
        """Send one CR-terminated command and wait for its final result."""
        if not command or "\r" in command or "\n" in command:
            raise ValueError("AT command must be a single nonempty line")
        self.open()
        self.drain()
        self.ser.write((command + "\r").encode("ascii"))
        try:
            self.ser.flush()
        except AttributeError:
            pass
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        lines, urcs = [], []
        while time.monotonic() < deadline:
            raw = self.ser.readline()
            if not raw:
                continue
            line = self._decode(raw)
            if not line or line == command:  # echo is neither payload nor result
                continue
            upper = line.upper()
            if upper == "OK":
                return ATResponse(command, lines, urcs, "OK")
            if upper == "ERROR" or upper.startswith("+CME ERROR"):
                return ATResponse(command, lines, urcs, line)
            if self._remember_urc(line):
                urcs.append(line)
                # For a call-originating command, these URCs are also an
                # immediate final call outcome.  On unrelated transactions
                # retain them and continue awaiting that command's final OK.
                if command.startswith("ATD") or command == "ATA":
                    if upper in CALL_FAILURE_URCS:
                        return ATResponse(command, lines, urcs, line)
            else:
                lines.append(line)
        raise ATTimeout("%s timed out after %.1fs" % (command, self.timeout if timeout is None else timeout))

    def initialize(self):
        results = []
        for command in INITIALIZATION_COMMANDS:
            try:
                results.append((command, self.command(command)))
            except (ATError, ATTimeout) as exc:
                results.append((command, exc))
        return results

    def read_urc(self, timeout=1.0):
        self.open()
        old_timeout = getattr(self.ser, "timeout", None)
        try:
            self.ser.timeout = min(timeout, 0.25)
        except Exception:
            pass
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                raw = self.ser.readline()
                if not raw:
                    continue
                line = self._decode(raw)
                if line:
                    self._remember_urc(line)
                    return line
        finally:
            try:
                self.ser.timeout = old_timeout
            except Exception:
                pass
        return None

    def hangup(self):
        return self.command("AT+CHUP", timeout=5)


def canonical_port_name(port):
    """Normalize Windows spellings such as ``COM6`` and ``\\\\.\\COM6``."""
    name = str(port).strip().replace("/", "\\").upper()
    if name.startswith("\\\\.\\"):
        name = name[4:]
    return name


def interface_kind_from_description(description):
    """Return only a role positively stated by the installed driver."""
    description = (description or "").upper()
    if "AT PORT" in description:
        return "at"
    if "MODEM" in description:
        return "modem"
    if any(label in description for label in ("AUDIO", "NMEA", "DIAGNOSTICS")):
        return "excluded"
    return "unknown"


def require_explicit_control_port(port, ports=None):
    """Resolve an override and require a positive AT Port/Modem driver role.

    A manual COM number is not authority to bypass the composite-device trust
    boundary.  Refuse absent, Audio, NMEA, Diagnostics, and unknown interfaces
    before any AT byte can be written.
    """
    if ports is None:
        if list_ports is None:
            raise RuntimeError("pyserial port enumeration is unavailable")
        ports = list(list_ports.comports())
    matches = [item for item in ports
               if canonical_port_name(getattr(item, "device", "")) == canonical_port_name(port)]
    if not matches:
        raise RuntimeError("%s is not present in the current Windows COM-port enumeration" % port)
    roles = set(interface_kind_from_description(getattr(item, "description", "")) for item in matches)
    if not roles.issubset(set(("at", "modem"))):
        raise RuntimeError("%s is not positively described as AT Port/Modem (role: %s)" %
                           (port, ", ".join(sorted(roles))))
    identities = set((getattr(item, "vid", None), getattr(item, "pid", None)) for item in matches)
    if identities != set(((EXPECTED_VID, EXPECTED_PID),)):
        raise RuntimeError("%s is not the target SIM8202G USB identity 1E0E:9001" % port)
    return matches[0]


class ProbeResult(object):
    def __init__(self, device, vid=None, pid=None, description="", hwid=""):
        self.device = device
        self.vid, self.pid = vid, pid
        self.description, self.hwid = description or "", hwid or ""
        self.responses = {}
        self.error = None
        self.skipped_reason = None

    @property
    def expected_usb_id(self):
        return self.vid == EXPECTED_VID and self.pid == EXPECTED_PID

    @property
    def responding(self):
        return self.responses.get("AT", False)

    @property
    def simcom_identity(self):
        text = self.identity_text.upper()
        return "SIMCOM" in text or "SIM8202" in text

    @property
    def target_identity(self):
        return "SIM8202" in self.identity_text.upper()

    @property
    def identity_text(self):
        return " | ".join(
            line for key in ("ATI", "AT+CGMR")
            for line in self.responses.get(key, [])
        )

    @property
    def interface_kind(self):
        """Return the usable role implied by a Windows driver description.

        SIM8202G's 9001 composite device exposes several functions.  Merely
        receiving an ``AT`` reply does not make a Diagnostics/NMEA/Audio
        function the intended call-control port, so description is a deliberate
        tie-breaker after the USB identity and a successful safe probe.
        """
        return interface_kind_from_description(self.description)

    @property
    def interface_priority(self):
        # AT Port is the documented control function.  Modem is the only
        # fallback preferred over an otherwise unidentified composite function.
        return {"at": 80, "modem": 40, "unknown": 0, "excluded": -100}.get(
            self.interface_kind, 0)

    @property
    def score(self):
        # An expected USB function wins; an identity response breaks ties among
        # such interfaces.  Generic AT responders are not auto-selected.
        return ((100 if self.expected_usb_id else 0) +
                (20 if self.simcom_identity else 0) +
                (5 if self.responding else 0) +
                self.interface_priority +
                sum(1 for key in ("ATI", "AT+CGMR") if self.responses.get(key)))

    def reason(self):
        parts = []
        parts.append("VID:PID 1E0E:9001" if self.expected_usb_id else "other/unknown VID:PID")
        parts.append("AT responds" if self.responding else "no AT response")
        role = {
            "at": "description says AT Port (preferred call-control port)",
            "modem": "description says Modem (fallback after AT Port)",
            "excluded": "description says Audio/NMEA/Diagnostics (excluded from auto-selection)",
            "unknown": "description has no known interface role",
        }[self.interface_kind]
        parts.append(role)
        if self.simcom_identity:
            parts.append("SIMCom identity text")
        return "; ".join(parts)


def probe_port(port_info, baud=115200, timeout=2.0, serial_factory=None):
    result = ProbeResult(port_info.device, getattr(port_info, "vid", None),
                         getattr(port_info, "pid", None),
                         getattr(port_info, "description", ""), getattr(port_info, "hwid", ""))
    if result.interface_kind not in ("at", "modem"):
        result.skipped_reason = "interface is not positively described as AT Port/Modem"
        return result
    if not result.expected_usb_id:
        result.skipped_reason = "interface is not target USB identity 1E0E:9001"
        return result
    session = None
    try:
        instance = serial_factory(port_info.device, baud, timeout) if serial_factory else None
        session = ATSession(port_info.device, baud, timeout, instance)
        for command in ("AT", "ATI", "AT+CGMR"):
            response = session.command(command, timeout=timeout)
            if response.ok:
                result.responses[command] = response.lines or ["OK"]
    except Exception as exc:
        result.error = str(exc)
    finally:
        if session is not None:
            session.close()
    return result


def list_candidates(baud=115200, timeout=2.0, ports=None, serial_factory=None):
    if ports is None:
        if list_ports is None:
            raise RuntimeError("pyserial is required: python -m pip install pyserial>=3.5")
        ports = list(list_ports.comports())
    # Probe matching functions first, then other interfaces.  It gives a likely
    # AT function the first chance without assuming its Windows COM number.
    ports = sorted(ports, key=lambda p: (not (getattr(p, "vid", None) == EXPECTED_VID and
                                          getattr(p, "pid", None) == EXPECTED_PID), p.device))
    results = []
    for port in ports:
        role = interface_kind_from_description(getattr(port, "description", ""))
        expected_id = (getattr(port, "vid", None) == EXPECTED_VID and
                       getattr(port, "pid", None) == EXPECTED_PID)
        if role in ("at", "modem") and expected_id:
            results.append(probe_port(port, baud, timeout, serial_factory))
        else:
            skipped = ProbeResult(port.device, getattr(port, "vid", None),
                                  getattr(port, "pid", None),
                                  getattr(port, "description", ""), getattr(port, "hwid", ""))
            if not expected_id:
                skipped.skipped_reason = "not probed: non-target USB identity"
            else:
                skipped.skipped_reason = "not probed: driver role is %s" % role
            results.append(skipped)
    return results


def select_port(results):
    """Select a safe control interface, preferring AT Port then Modem.

    Audio, NMEA, Diagnostics, and unknown interfaces are intentionally never
    chosen, even if they happen to echo an AT command.  ``--port`` must pass the
    same positive Windows role validation.
    """
    eligible = [item for item in results
                if item.responding and item.target_identity and
                item.interface_kind in ("at", "modem")]
    expected = [item for item in eligible if item.expected_usb_id]
    candidates = expected
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-item.score, item.device.upper()))[0]


def print_probe_results(results, selected=None):
    for item in results:
        suffix = " [SELECTED]" if selected is item else ""
        skipped = ("; " + item.skipped_reason) if item.skipped_reason else ""
        error = ("; probe error: " + item.error) if item.error else ""
        print("%s: %s%s%s%s" % (redact_sensitive(item.device), redact_sensitive(item.reason()),
                                 redact_sensitive(skipped), redact_sensitive(error), suffix))
        if item.identity_text:
            print("  identity: %s" % redact_sensitive(item.identity_text))
    if selected is not None:
        print("Selection basis: %s." % redact_sensitive(selected.reason()))


def open_selected(args):
    if args.port:
        require_explicit_control_port(args.port)
        print("Using explicit port %s (verified AT Port/Modem role)." % args.port)
        session = ATSession(args.port, args.baud, args.timeout).open()
        try:
            require_target_identity(session)
        except Exception:
            session.close()
            raise
        return session
    results = list_candidates(args.baud, args.timeout)
    selected = select_port(results)
    print_probe_results(results, selected)
    if selected is None:
        raise RuntimeError("No responsive SIM8202G AT port found; specify --port COMx after checking the driver.")
    session = ATSession(selected.device, args.baud, args.timeout).open()
    try:
        require_target_identity(session)
    except Exception:
        session.close()
        raise
    return session


def response_text(response):
    payload = response.lines + response.urcs
    return redact_sensitive(" | ".join(payload) if payload else response.final)


def require_target_identity(session):
    """Verify SIM8202 identity on the opened control session before call writes."""
    response = session.command("ATI", timeout=5)
    text = " ".join(response.lines + response.urcs).upper()
    if not response.ok or "SIM8202" not in text:
        raise RuntimeError("opened control port did not positively identify a SIM8202 modem")
    return response


def ceer_after_failure(session):
    try:
        response = session.command("AT+CEER", timeout=5)
        print("AT+CEER: %s" % response_text(response))
    except (ATError, ATTimeout, OSError) as exc:
        print("AT+CEER unavailable: %s" % exc)


def parse_cpas_state(lines):
    """Extract an unambiguous tagged ``+CPAS: <state>`` response."""
    states = []
    for line in lines:
        match = re.match(r"^\s*\+CPAS:\s*(\d+)\s*$", line, re.I)
        if match:
            states.append(int(match.group(1)))
    return states[0] if len(states) == 1 else None


def confirm_call_idle(session, attempts=2):
    """Require tagged +CPAS: 0 evidence; a naked/late OK is never sufficient."""
    last_detail = "no tagged +CPAS state"
    for _ in range(max(1, int(attempts))):
        try:
            response = session.command("AT+CPAS", timeout=5)
        except (Exception, KeyboardInterrupt) as exc:
            last_detail = str(exc) or exc.__class__.__name__
            continue
        state = parse_cpas_state(response.lines + response.urcs)
        if response.ok and state == 0:
            return True, "+CPAS: 0"
        if state is not None:
            last_detail = "+CPAS: %d" % state
        elif not response.ok:
            last_detail = response.final
    return False, last_detail


def best_effort_hangup(session, context="Call request result unknown", reporter=print):
    """Attempt CHUP, then confirm idle with tagged state rather than naked OK."""
    command_detail = "AT+CHUP result unavailable"
    try:
        response = session.hangup()
    except (Exception, KeyboardInterrupt) as exc:
        command_detail = "AT+CHUP failed: %s" % exc
    else:
        command_detail = "AT+CHUP returned %s" % response.final
    confirmed, state_detail = confirm_call_idle(session)
    if confirmed:
        reporter("%s; %s; call idle confirmed by %s." %
                 (context, command_detail, state_detail))
        return True
    reporter("%s; %s; call state is NOT confirmed (%s)." %
             (context, command_detail, state_detail))
    return False


def command_status(session):
    print("Initialization (current session):")
    for command, result in session.initialize():
        if isinstance(result, Exception):
            print("  %-12s %s" % (command, result))
        else:
            print("  %-12s %s" % (command, "OK" if result.ok else result.final))
    print("\nStatus:")
    for label, command in STATUS_COMMANDS:
        try:
            response = session.command(command)
            print("  %s: %s" % (label, response_text(response)))
            for line in response.lines:
                status = registration_status(line)
                if status:
                    print("    cellular registration: %s" % status["meaning"])
        except (ATError, ATTimeout) as exc:
            print("  %s: %s" % (label, exc))
    print("\nNote: CEREG/C5GREG report cellular registration only; they do NOT prove IMS/VoLTE registration.")


def command_dial(session, number, call_timeout=30.0):
    number = validate_number(number)
    try:
        response = session.command("ATD%s;" % number, timeout=call_timeout)
        print("Dial command: %s" % response_text(response))
        if not response.ok:
            ceer_after_failure(session)
            return 2
        # A final OK only says the modem accepted the request.  Collect any
        # immediately available call URCs but never label this as IMS/voice success.
        end = time.monotonic() + min(call_timeout, 5.0)
        while time.monotonic() < end:
            line = session.read_urc(timeout=0.25)
            if line:
                print("URC: %s" % redact_sensitive(line))
                if line.upper() in CALL_FAILURE_URCS:
                    ceer_after_failure(session)
                    return 2
        print("Dial request accepted; continue `monitor` to observe later call URCs.")
        return 0
    except (ATError, ATTimeout, OSError) as exc:
        print("Dial failed: %s" % exc)
        # command() writes ATD before it waits.  A timeout/read failure therefore
        # leaves delivery uncertain and must be treated as a possibly live call.
        best_effort_hangup(session, "Dial request result unknown")
        ceer_after_failure(session)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted while dialing.")
        best_effort_hangup(session, "Dial request may already have reached the modem")
        return 130


def command_answer(session):
    try:
        response = session.command("ATA", timeout=15)
        print("Answer: %s" % response_text(response))
        if not response.ok:
            ceer_after_failure(session)
            return 2
        return 0
    except (ATError, ATTimeout, OSError) as exc:
        print("Answer failed: %s" % exc)
        best_effort_hangup(session, "Answer request result unknown")
        ceer_after_failure(session)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted while answering.")
        best_effort_hangup(session, "Answer request may already have reached the modem")
        return 130


def command_hangup(session):
    return 0 if best_effort_hangup(session, "Hangup requested") else 2


def command_monitor(session):
    try:
        # A fresh invocation should ask the modem for its documented call and
        # registration notifications instead of relying on a prior `status`.
        initialization = session.initialize()
        failed = [command for command, result in initialization if isinstance(result, Exception) or not result.ok]
        if failed:
            print("URC setup did not confirm: %s" % ", ".join(failed))
        print("Monitoring URCs. Press Ctrl+C to stop monitoring (this does not hang up).")
        while True:
            line = session.read_urc(timeout=1.0)
            if line:
                print("URC: %s" % redact_sensitive(line))
    except KeyboardInterrupt:
        print("\nMonitor stopped; call state was not changed.")
        return 0


def make_parser():
    parser = argparse.ArgumentParser(description="SIM8202G-M2 AT voice call controller (no audio transport)")
    parser.add_argument("--port", help="verified Windows AT Port/Modem override, e.g. COM6")
    parser.add_argument("--baud", type=int, default=115200, help="baud rate (default: 115200)")
    parser.add_argument("--timeout", type=float, default=3.0, help="normal command timeout seconds")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("probe", help="list and safely probe candidate serial ports")
    sub.add_parser("status", help="initialize this session and show SIM/network/call state")
    dial = sub.add_parser("dial", help="dial a validated phone number")
    dial.add_argument("number", help="optional + followed by 3-20 digits")
    dial.add_argument("--call-timeout", type=float, default=30.0, help="dial command timeout seconds")
    sub.add_parser("answer", help="answer an incoming call")
    sub.add_parser("hangup", help="hang up a call")
    sub.add_parser("monitor", help="print unsolicited result codes until Ctrl+C")
    return parser


def main(argv=None):
    args = make_parser().parse_args(argv)
    if args.action == "probe":
        if args.port:
            try:
                explicit = require_explicit_control_port(args.port)
            except RuntimeError as exc:
                print("Cannot probe explicit AT port: %s" % exc, file=sys.stderr)
                return 2
            results = [probe_port(explicit, args.baud, args.timeout)]
            print_probe_results(results)
            return 0 if results[0].responding else 2
        results = list_candidates(args.baud, args.timeout)
        selected = select_port(results)
        print_probe_results(results, selected)
        return 0 if selected else 2
    try:
        session = open_selected(args)
    except (RuntimeError, OSError, Exception) as exc:
        print("Cannot open AT port: %s" % exc, file=sys.stderr)
        return 2
    try:
        if args.action == "status":
            command_status(session)
            return 0
        if args.action == "dial":
            return command_dial(session, args.number, args.call_timeout)
        if args.action == "answer":
            return command_answer(session)
        if args.action == "hangup":
            return command_hangup(session)
        if args.action == "monitor":
            return command_monitor(session)
    except (ATError, ATTimeout, OSError) as exc:
        print("Command failed: %s" % exc)
        if args.action in ("answer", "hangup"):
            ceer_after_failure(session)
        return 2
    finally:
        session.close()
    return 2


if __name__ == "__main__":
    sys.exit(main())
