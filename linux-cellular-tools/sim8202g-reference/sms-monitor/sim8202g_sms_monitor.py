#!/usr/bin/env python3
"""Listen for newly stored SMS messages on a SIMCom AT port.

The monitor never deletes messages.  It selects PDU mode, asks the modem to
report the storage index of each new SMS, reads that index, and emits one JSON
record containing the PDU for a supervising process to decode.
"""

from __future__ import print_function

import argparse
import datetime
import json
import re
import sys
import time

import serial


TERMINALS = ("OK", "ERROR", "+CME ERROR", "+CMS ERROR")
CMTI_RE = re.compile(r'^\+CMTI:\s*"([^"]+)",\s*(\d+)\s*$', re.I)
PDU_RE = re.compile(r"^[0-9A-Fa-f]+$")


def emit(kind, **fields):
    fields["event"] = kind
    fields.setdefault("host_time", datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
    print(json.dumps(fields, ensure_ascii=False, sort_keys=True), flush=True)


class Modem(object):
    def __init__(self, port, baud):
        self.ser = serial.Serial(port, baud, timeout=0.25, write_timeout=2)
        self.deferred = []

    def close(self):
        self.ser.close()

    def line(self):
        raw = self.ser.readline()
        if not raw:
            return ""
        return raw.decode("ascii", "replace").strip()

    def command(self, command, timeout=6.0):
        self.ser.write((command + "\r").encode("ascii"))
        self.ser.flush()
        deadline = time.monotonic() + timeout
        lines = []
        while time.monotonic() < deadline:
            line = self.line()
            if not line or line == command:
                continue
            upper = line.upper()
            if upper == "OK":
                return "OK", lines
            if upper == "ERROR" or upper.startswith("+CME ERROR") or upper.startswith("+CMS ERROR"):
                return line, lines
            if CMTI_RE.match(line):
                self.deferred.append(line)
            else:
                lines.append(line)
        raise RuntimeError("AT command timed out: %s" % command)


def require_ok(modem, command):
    final, lines = modem.command(command)
    if final != "OK":
        raise RuntimeError("%s failed: %s" % (command, final))
    return lines


def read_new_message(modem, storage, index):
    # Mode 1 asks standards-compliant modems not to change REC UNREAD to
    # REC READ.  Fall back to the universally supported form if unsupported.
    final, lines = modem.command("AT+CMGR=%d,1" % index, timeout=10.0)
    preserved_unread = final == "OK"
    if final != "OK":
        final, lines = modem.command("AT+CMGR=%d" % index, timeout=10.0)
    if final != "OK":
        emit("sms_read_error", storage=storage, index=index, final=final)
        return

    pdu = ""
    for line in lines:
        candidate = line.strip()
        if len(candidate) >= 20 and len(candidate) % 2 == 0 and PDU_RE.fullmatch(candidate):
            pdu = candidate.upper()
            break
    if not pdu:
        emit("sms_read_error", storage=storage, index=index,
             final="No PDU payload in AT+CMGR response")
        return
    emit("sms_pdu", storage=storage, index=index, pdu=pdu,
         unread_status_preserved=preserved_unread)


def process_cmti(modem, line):
    match = CMTI_RE.match(line)
    if not match:
        return
    storage, index_text = match.groups()
    read_new_message(modem, storage, int(index_text))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Monitor SIMCom new-SMS notifications")
    parser.add_argument("--port", default="COM6")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args(argv)

    modem = Modem(args.port, args.baud)
    try:
        # Discard stale registration chatter before defining the beginning of
        # this monitoring interval.  Existing stored SMS messages are untouched.
        modem.ser.reset_input_buffer()
        require_ok(modem, "AT")
        require_ok(modem, "ATE0")
        require_ok(modem, "AT+CMEE=2")
        require_ok(modem, "AT+C5GREG=0")
        require_ok(modem, "AT+CEREG=0")
        require_ok(modem, "AT+CGREG=0")
        require_ok(modem, "AT+CREG=0")
        sim_state = require_ok(modem, "AT+CPIN?")
        if not any("READY" in line.upper() for line in sim_state):
            raise RuntimeError("SIM is not ready: %r" % sim_state)
        require_ok(modem, "AT+CMGF=0")
        # Store new messages and report their index.  This is safer than direct
        # delivery because the SMS remains in SIM storage if the host exits.
        require_ok(modem, "AT+CNMI=2,1,0,0,0")
        cnmi = require_ok(modem, "AT+CNMI?")
        cmgf = require_ok(modem, "AT+CMGF?")
        cpms = require_ok(modem, "AT+CPMS?")
        emit("ready", port=args.port, cnmi=cnmi, cmgf=cmgf, storage=cpms,
             policy="new messages only; existing messages retained; no deletion")

        while True:
            if modem.deferred:
                process_cmti(modem, modem.deferred.pop(0))
                continue
            line = modem.line()
            if not line:
                continue
            if CMTI_RE.match(line):
                process_cmti(modem, line)
            elif line.upper().startswith(("+CMS ERROR", "+CME ERROR")):
                emit("modem_error", line=line)
    except KeyboardInterrupt:
        emit("stopped", reason="keyboard interrupt")
        return 0
    except Exception as exc:
        emit("fatal", error="%s: %s" % (type(exc).__name__, exc))
        return 1
    finally:
        modem.close()


if __name__ == "__main__":
    sys.exit(main())
