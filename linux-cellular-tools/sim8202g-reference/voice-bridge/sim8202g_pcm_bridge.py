#!/usr/bin/env python3
"""Experimental bidirectional USB PCM bridge for SIM8202G-M2 voice calls.

The SIMTech ``Audio 9001`` COM interface is a binary PCM transport after the
modem has accepted ``AT+CPCMREG=1`` during an *already active* voice call.  It
is not a Windows USB Audio Class (UAC) device.  This module deliberately keeps
that binary interface separate from the AT control port: no AT text is ever
written to the audio port.

Python 3.8 compatible.  ``sounddevice`` is imported lazily so the offline
helpers and unit tests remain usable where PortAudio is not installed.
"""
from __future__ import print_function

import argparse
import audioop
import math
import os
import queue
import re
import sys
import threading
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

import sim8202g_voice as voice


PCM_RATE = 8000
PCM_WIDTH = 2
PCM_CHANNELS = 1
PCM_BLOCK_BYTES = 320                 # 20 ms of mono, signed, little-endian PCM
DEFAULT_QUEUE_BLOCKS = 50
DEFAULT_AUDIO_BAUD = 921600
# 8 kHz * 16 bits * 1 channel is 16,000 byte/s.  A conventional 8N1 UART
# needs ten line bits per byte, so 160,000 baud is only the zero-headroom
# mathematical floor.  Require the next conventional rate to leave margin for
# scheduling and USB-serial transport overhead.
MIN_AUDIO_BAUD = 230400
VOICE_BEGIN = "VOICE CALL: BEGIN"
VOICE_END_MARKERS = ("VOICE CALL: END", "NO CARRIER", "BUSY", "NO ANSWER", "NO DIALTONE")
CLCC_ACTIVE_RE = re.compile(r"^\+CLCC:\s*\d+\s*,\s*\d+\s*,\s*0(?:\s*,|$)", re.I)


class BridgeError(RuntimeError):
    """A bridge precondition or runtime operation failed."""


def _audioop_native(data):
    """Convert explicit little-endian transport data to audioop's native form."""
    if sys.byteorder == "big":
        return audioop.byteswap(data, PCM_WIDTH)
    return data


def _native_to_audioop_transport(data):
    if sys.byteorder == "big":
        return audioop.byteswap(data, PCM_WIDTH)
    return data


class PCMResampler(object):
    """Stateful mono int16 LE stream resampler which tolerates odd short reads."""
    def __init__(self, input_rate, output_rate):
        if input_rate <= 0 or output_rate <= 0:
            raise ValueError("PCM sample rates must be positive")
        self.input_rate = int(input_rate)
        self.output_rate = int(output_rate)
        self._state = None
        self._tail = b""

    def convert(self, data):
        if not isinstance(data, bytes):
            data = bytes(data)
        data = self._tail + data
        if len(data) & 1:
            self._tail, data = data[-1:], data[:-1]
        else:
            self._tail = b""
        if not data:
            return b""
        native = _audioop_native(data)
        if self.input_rate == self.output_rate:
            result = native
        else:
            result, self._state = audioop.ratecv(native, PCM_WIDTH, PCM_CHANNELS,
                                                 self.input_rate, self.output_rate,
                                                 self._state)
        return _native_to_audioop_transport(result)


class PCMAligner(object):
    """Return only complete int16 samples while retaining an odd trailing byte."""
    def __init__(self):
        self.tail = b""

    def feed(self, data):
        data = self.tail + bytes(data)
        if len(data) & 1:
            self.tail = data[-1:]
            return data[:-1]
        self.tail = b""
        return data


def short_write_all(port, data, stop_event=None):
    """Write every byte, accepting legal pyserial short writes.

    The caller supplies PCM-aligned data.  A zero/None-length write is treated
    as a transport failure rather than spinning forever.
    """
    view = memoryview(data)
    written = 0
    calls = 0
    while written < len(view):
        if stop_event is not None and stop_event.is_set():
            break
        count = port.write(view[written:])
        calls += 1
        if count is None or count <= 0:
            raise BridgeError("audio serial port made no write progress")
        written += count
    return written, calls


def has_active_clcc(lines):
    return any(CLCC_ACTIVE_RE.match(line.strip()) for line in lines)


def summarize_call_evidence(lines):
    """Return a non-sensitive diagnostic summary of recent call-state evidence.

    A ``+CLCC`` row can contain the remote number.  Keep the useful state
    category while deliberately never echoing a raw row to the console.
    """
    if any(is_voice_end(line) for line in lines):
        return "voice-call end indication"
    if any(is_voice_begin(line) for line in lines):
        return "voice-call begin indication"
    if has_active_clcc(lines):
        return "+CLCC active-call state"
    if any(re.match(r"^\s*\+CLCC:", line or "", re.I) for line in lines):
        return "+CLCC reported no active-call state"
    return "no VOICE CALL or +CLCC call-state evidence"


def parse_cpcmreg_state(lines):
    """Return state only from one unambiguous tagged ``+CPCMREG`` payload."""
    states = []
    for line in lines:
        match = re.match(r"^\s*\+CPCMREG:\s*([01])\s*$", line, re.I)
        if match:
            states.append(int(match.group(1)))
    return states[0] if len(states) == 1 else None


def is_voice_begin(line):
    return VOICE_BEGIN in (line or "").upper()


def is_voice_end(line):
    upper = (line or "").upper()
    return any(marker in upper for marker in VOICE_END_MARKERS)


def parse_device_identifier(value):
    """Let --input-device 3 mean PortAudio index 3, otherwise retain its name."""
    if value is None:
        return None
    return int(value) if re.fullmatch(r"\d+", value) else value


def positive_seconds(value):
    """``argparse`` converter for an explicitly bounded active-call duration."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("must be a finite positive number of seconds")
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number of seconds")
    return seconds


def canonical_port_name(port):
    """Normalize Windows spellings such as ``COM5`` and ``\\\\.\\COM5``."""
    name = str(port).strip().replace("/", "\\").upper()
    if name.startswith("\\\\.\\"):
        name = name[4:]
    return name


def described_port_role(port_info):
    """Return only the role directly stated by a Windows driver description."""
    description = (getattr(port_info, "description", "") or "").upper()
    if "AT PORT" in description:
        return "at"
    if "MODEM" in description:
        return "modem"
    if "AUDIO" in description:
        return "audio"
    if "NMEA" in description:
        return "nmea"
    if "DIAGNOSTICS" in description:
        return "diagnostics"
    return "unknown"


def enumerate_audio_devices(sounddevice_module=None, output=None):
    """Print PortAudio endpoints without opening a modem or an audio stream."""
    sd = sounddevice_module or load_sounddevice()
    output = output or sys.stdout
    devices = sd.query_devices()
    default = getattr(sd, "default", None)
    default_pair = getattr(default, "device", None)
    print("PortAudio audio devices (default input/output: %r):" % (default_pair,), file=output)
    for index, item in enumerate(devices):
        # Device dictionaries are used by sounddevice and easy to fake in tests.
        name = item.get("name", "")
        inputs = item.get("max_input_channels", 0)
        outputs = item.get("max_output_channels", 0)
        rate = item.get("default_samplerate", 0)
        print("  %d: %s (input=%s, output=%s, default-rate=%s)" %
              (index, name, inputs, outputs, rate), file=output)
    return devices


def load_sounddevice():
    try:
        import sounddevice
        return sounddevice
    except ImportError:
        raise BridgeError("sounddevice is required for host audio: python -m pip install sounddevice>=0.4.4")


def find_audio_port_info(ports=None):
    """Select one expected SIMTech Audio COM function without probing it."""
    if ports is None:
        if list_ports is None:
            raise BridgeError("pyserial is required: python -m pip install pyserial>=3.5")
        ports = list(list_ports.comports())
    matches = [p for p in ports if "AUDIO" in (getattr(p, "description", "") or "").upper()]
    expected = [p for p in matches if (getattr(p, "vid", None) == voice.EXPECTED_VID and
                                       getattr(p, "pid", None) == voice.EXPECTED_PID)]
    # Never auto-select an unrelated serial device merely because its friendly
    # name happens to contain "Audio".  The target function has a known USB ID.
    candidates = expected
    if len(candidates) != 1:
        if not candidates:
            if matches:
                names = ", ".join(p.device for p in matches)
                raise BridgeError("Only non-SIM8202 Audio COM interface(s) found (%s); refusing auto-selection" % names)
            raise BridgeError("No SIM8202 Audio COM interface found")
        names = ", ".join(p.device for p in candidates)
        raise BridgeError("Multiple Audio COM interfaces found (%s); provide --audio-port COMx" % names)
    return candidates[0]


def find_audio_port(ports=None):
    """Return the selected target Audio COM name for compatibility/callers."""
    return find_audio_port_info(ports=ports).device


def select_at_port(baud=115200, timeout=2.0):
    """Probe only explicitly-labelled AT Port/Modem functions.

    An expected VID:PID alone is not a positive identity proof: unknown or
    localized descriptions can be a diagnostic/vendor function.  Bridge mode
    therefore favours refusing an ambiguous setup over putting AT bytes on the
    wrong binary interface.
    """
    if list_ports is None:
        raise BridgeError("pyserial is required: python -m pip install pyserial>=3.5")
    ports = list(list_ports.comports())
    # Filter here as well as inside ``voice.list_candidates`` so the bridge's
    # trust boundary is explicit at the call site.  Audio, NMEA, Diagnostics,
    # and unknown interfaces must never receive a speculative AT probe.
    ports = [p for p in ports if described_port_role(p) in ("at", "modem")]
    if not ports:
        raise BridgeError("No explicitly described AT Port/Modem interface found; provide a correctly installed AT port")
    results = voice.list_candidates(baud, timeout, ports=ports)
    selected = voice.select_port(results)
    voice.print_probe_results(results, selected)
    if selected is None:
        raise BridgeError("No responsive SIM8202G AT port found; provide --at-port COMx")
    return selected.device


def require_explicit_at_port_role(port, ports=None):
    """Validate a known explicit override before any AT byte is transmitted."""
    if ports is None:
        if list_ports is None:
            raise BridgeError("pyserial port enumeration is unavailable")
        ports = list(list_ports.comports())
    matches = [item for item in ports
               if canonical_port_name(getattr(item, "device", "")) == canonical_port_name(port)]
    if not matches:
        raise BridgeError("%s is not present in the current COM-port enumeration" % port)
    roles = set(described_port_role(item) for item in matches)
    if not roles.issubset(set(("at", "modem"))):
        raise BridgeError("%s has non-AT/Modem role(s) %s; refuse to write AT text" %
                          (port, ", ".join(sorted(roles))))
    identities = set((getattr(item, "vid", None), getattr(item, "pid", None)) for item in matches)
    if identities != set(((voice.EXPECTED_VID, voice.EXPECTED_PID),)):
        raise BridgeError("%s is not the target SIM8202G USB identity 1E0E:9001" % port)
    return matches[0]


def require_explicit_audio_port_role(port, ports=None):
    """Require an enumerated, positively-labelled Audio function."""
    if ports is None:
        if list_ports is None:
            raise BridgeError("pyserial port enumeration is unavailable")
        ports = list(list_ports.comports())
    matches = [item for item in ports
               if canonical_port_name(getattr(item, "device", "")) == canonical_port_name(port)]
    if not matches:
        raise BridgeError("%s is not present in the current COM-port enumeration" % port)
    roles = set(described_port_role(item) for item in matches)
    if roles != set(("audio",)):
        raise BridgeError("%s has non-Audio role(s) %s; refuse raw PCM I/O" %
                          (port, ", ".join(sorted(roles))))
    identities = set((getattr(item, "vid", None), getattr(item, "pid", None)) for item in matches)
    if identities != set(((voice.EXPECTED_VID, voice.EXPECTED_PID),)):
        raise BridgeError("%s is not the target SIM8202G USB identity 1E0E:9001" % port)
    return matches[0]


def composite_location_root(port_info):
    """Strip the Windows composite interface suffix from a USB location."""
    location = (getattr(port_info, "location", None) or "").strip().upper()
    return re.sub(r":X\.\d+$", "", location)


def same_target_composite(at_info, audio_info):
    """Prove two functions belong to the same target physical USB composite."""
    expected = (voice.EXPECTED_VID, voice.EXPECTED_PID)
    if ((getattr(at_info, "vid", None), getattr(at_info, "pid", None)) != expected or
            (getattr(audio_info, "vid", None), getattr(audio_info, "pid", None)) != expected):
        return False
    at_serial = (getattr(at_info, "serial_number", None) or "").strip().upper()
    audio_serial = (getattr(audio_info, "serial_number", None) or "").strip().upper()
    at_root, audio_root = composite_location_root(at_info), composite_location_root(audio_info)
    # Requiring both protects against modules that share a placeholder USB
    # serial number and against location-only aliasing.
    return bool(at_serial and audio_serial and at_serial == audio_serial and
                at_root and audio_root and at_root == audio_root)


def reject_known_audio_as_at_port(port, ports=None):
    """Backward-compatible narrow helper retained for callers/tests."""
    return require_explicit_at_port_role(port, ports)


def open_audio_serial(port, baud=DEFAULT_AUDIO_BAUD, serial_factory=None):
    """Open the binary interface with all software/hardware flow control off."""
    if baud < MIN_AUDIO_BAUD:
        raise BridgeError("audio baud %d is below %d and cannot carry 8 kHz/16-bit PCM" %
                          (baud, MIN_AUDIO_BAUD))
    if serial_factory is not None:
        return serial_factory(port, baud)
    if serial is None:
        raise BridgeError("pyserial is required: python -m pip install pyserial>=3.5")
    return serial.Serial(port=port, baudrate=baud, timeout=0.10, write_timeout=0.5,
                         xonxoff=False, rtscts=False, dsrdtr=False)


class PCMBridge(object):
    """Own the real-time PCM workers and their bounded queues.

    AT state is intentionally owned by the foreground controller; workers touch
    only COM Audio binary bytes and PortAudio streams.  This prevents a delayed
    worker from ever writing AT strings to the audio interface.
    """
    def __init__(self, audio_port, input_device=None, output_device=None, host_rate=None,
                 audio_baud=DEFAULT_AUDIO_BAUD, sounddevice_module=None, serial_factory=None,
                 queue_blocks=DEFAULT_QUEUE_BLOCKS, capture_rx=None, capture_tx=None,
                 reporter=None):
        self.audio_port_name = audio_port
        self.input_device = input_device
        self.output_device = output_device
        self.requested_host_rate = host_rate
        self.audio_baud = audio_baud
        self.sd = sounddevice_module
        self.serial_factory = serial_factory
        self.capture_rx = capture_rx
        self.capture_tx = capture_tx
        self.reporter = reporter or (lambda text: print(text, file=sys.stderr))
        self.rx_queue = queue.Queue(maxsize=queue_blocks)
        self.tx_queue = queue.Queue(maxsize=queue_blocks)
        self.stop_event = threading.Event()
        self.error = None
        self.audio_serial = None
        self.input_stream = None
        self.output_stream = None
        self.threads = []
        self._capture_handles = []
        self._lock = threading.Lock()
        self.stats = {"rx_bytes": 0, "tx_bytes": 0, "rx_dropped": 0,
                      "tx_dropped": 0, "short_writes": 0,
                      "input_status": 0, "output_underflows": 0}

    def _add(self, key, amount=1):
        with self._lock:
            self.stats[key] += amount

    def _set_error(self, exc):
        with self._lock:
            if self.error is None:
                self.error = exc
                self.reporter("PCM bridge worker failed: %s" % exc)
        self.stop_event.set()

    @staticmethod
    def _put_bounded(target, data, counter, owner):
        if not data:
            return
        try:
            target.put_nowait(data)
        except queue.Full:
            owner._add(counter, len(data))

    def _input_callback(self, indata, frames, time_info, status):
        if status:
            self._add("input_status")
        self._put_bounded(self.tx_queue, bytes(indata), "tx_dropped", self)

    def _input_rate(self):
        if self.requested_host_rate:
            return int(self.requested_host_rate)
        item = self.sd.query_devices(self.input_device, "input")
        return int(round(item["default_samplerate"]))

    def _output_rate(self):
        if self.requested_host_rate:
            return int(self.requested_host_rate)
        item = self.sd.query_devices(self.output_device, "output")
        return int(round(item["default_samplerate"]))

    def _open_capture(self, path):
        if not path:
            return None
        # Explicit raw capture is opt-in and refuses to overwrite existing audio.
        handle = open(path, "xb")
        self._capture_handles.append(handle)
        return handle

    def start(self):
        if self.audio_serial is not None:
            raise BridgeError("PCM bridge is already started")
        self.sd = self.sd or load_sounddevice()
        input_rate, output_rate = self._input_rate(), self._output_rate()
        if input_rate <= 0 or output_rate <= 0:
            raise BridgeError("selected host audio device did not report a usable sample rate")
        try:
            self.audio_serial = open_audio_serial(self.audio_port_name, self.audio_baud, self.serial_factory)
            self.input_stream = self.sd.RawInputStream(samplerate=input_rate, blocksize=0,
                                                        device=self.input_device, channels=1,
                                                        dtype="int16", callback=self._input_callback)
            self.output_stream = self.sd.RawOutputStream(samplerate=output_rate, blocksize=0,
                                                          device=self.output_device, channels=1,
                                                          dtype="int16")
            self._rx_capture = self._open_capture(self.capture_rx)
            self._tx_capture = self._open_capture(self.capture_tx)
            self.input_stream.start()
            self.output_stream.start()
            self.threads = [
                threading.Thread(target=self._reader, name="sim8202g-pcm-rx", daemon=True),
                threading.Thread(target=self._writer, args=(input_rate,), name="sim8202g-pcm-tx", daemon=True),
                threading.Thread(target=self._speaker, args=(output_rate,), name="sim8202g-pcm-speaker", daemon=True),
            ]
            for worker in self.threads:
                worker.start()
            self.reporter("PCM bridge started: modem 8000 Hz mono s16le; host input %d Hz, output %d Hz" %
                          (input_rate, output_rate))
        except Exception:
            self.stop()
            raise

    def _reader(self):
        aligner = PCMAligner()
        try:
            while not self.stop_event.is_set():
                data = self.audio_serial.read(1024)
                if not data:
                    continue
                self._add("rx_bytes", len(data))
                if self._rx_capture:
                    self._rx_capture.write(data)
                aligned = aligner.feed(data)
                self._put_bounded(self.rx_queue, aligned, "rx_dropped", self)
        except Exception as exc:
            if not self.stop_event.is_set():
                self._set_error(exc)

    def _writer(self, input_rate):
        resampler = PCMResampler(input_rate, PCM_RATE)
        pending = b""
        try:
            while not self.stop_event.is_set():
                try:
                    host_data = self.tx_queue.get(timeout=0.20)
                except queue.Empty:
                    continue
                pending += resampler.convert(host_data)
                while len(pending) >= PCM_BLOCK_BYTES and not self.stop_event.is_set():
                    block, pending = pending[:PCM_BLOCK_BYTES], pending[PCM_BLOCK_BYTES:]
                    wrote, calls = short_write_all(self.audio_serial, block, self.stop_event)
                    self._add("tx_bytes", wrote)
                    if calls > 1:
                        self._add("short_writes", calls - 1)
                    if self._tx_capture and wrote:
                        self._tx_capture.write(block[:wrote])
        except Exception as exc:
            if not self.stop_event.is_set():
                self._set_error(exc)

    def _speaker(self, output_rate):
        resampler = PCMResampler(PCM_RATE, output_rate)
        try:
            while not self.stop_event.is_set():
                try:
                    modem_data = self.rx_queue.get(timeout=0.20)
                except queue.Empty:
                    continue
                host_data = resampler.convert(modem_data)
                if host_data:
                    underflowed = self.output_stream.write(host_data)
                    if underflowed:
                        self._add("output_underflows")
        except Exception as exc:
            if not self.stop_event.is_set():
                self._set_error(exc)

    def stats_snapshot(self):
        with self._lock:
            return dict(self.stats)

    def stop(self):
        """Stop audio writes first, then close all local handles, idempotently."""
        self.stop_event.set()
        for stream_name in ("input_stream", "output_stream"):
            stream = getattr(self, stream_name, None)
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
                setattr(self, stream_name, None)
        port, self.audio_serial = self.audio_serial, None
        if port is not None:
            try:
                port.close()
            except Exception:
                pass
        for worker in self.threads:
            if worker is not threading.current_thread():
                worker.join(1.0)
        self.threads = []
        for handle in self._capture_handles:
            try:
                handle.close()
            except Exception:
                pass
        self._capture_handles = []


class CallPCMController(object):
    """AT state gate and cleanup owner around :class:`PCMBridge`."""
    def __init__(self, session, bridge_factory=PCMBridge, reporter=None, clock=None):
        self.session = session
        self.bridge_factory = bridge_factory
        self.reporter = reporter or print
        self.clock = clock or time.monotonic
        # Keep request, call, and PCM ownership separate.  In particular a
        # missing final result after ATD/ATA is not evidence that nothing was
        # sent, and a missing final result after CPCMREG=1 is not evidence that
        # PCM remained disabled.
        self.call_request_attempted = False
        self.call_request_sent = False
        self.call_active = False
        self.owned_call = False
        self.hangup_attempted = False
        self.hangup_confirmed = False
        self.pcm_enabled = False              # CPCMREG=1 positively confirmed
        self.pcm_enable_attempted = False     # result may be unknown
        self.pcm_disable_confirmed = False
        self.pcm_was_preexisting = False
        self.bridge = None
        # Set only after both modem PCM registration and local bridge startup
        # succeeded.  A call request or its later BEGIN/CLCC evidence alone
        # must never consume a user's requested active-call budget.
        self.bridge_active_started_at = None
        self.last_call_evidence = "no VOICE CALL or +CLCC call-state evidence"
        self.pre_pcm_failure_diagnostics_reported = False

    def _command_ok(self, command, timeout=None, record_call_evidence=False):
        try:
            reply = self.session.command(command, timeout=timeout)
        except KeyboardInterrupt:
            # Preserve the established Ctrl+C return path; it has no modem
            # command text to render and still performs conservative cleanup.
            raise
        except Exception:
            if record_call_evidence:
                # ATSession timeout/transport errors include the full command
                # text, which for ATD includes a sensitive destination.  CEER
                # and the sanitized state summary below are the useful
                # diagnostics, so do not let that command leak through the
                # outer "Bridge failed" message.
                raise BridgeError("call request did not return a final result")
            raise
        if record_call_evidence:
            # ATD/ATA transactions can themselves carry the final call URC.
            # Persist only a categorized summary before raising, never a raw
            # response row that might contain the dialed/remote number.
            self.last_call_evidence = summarize_call_evidence(reply.lines + reply.urcs)
        if not reply.ok:
            if record_call_evidence:
                raise BridgeError("call request was not accepted: %s" % reply.final)
            raise BridgeError("%s was not accepted: %s" % (command, reply.final))
        return reply

    def verify_capability(self):
        # Both are read-only.  Query current state even if a firmware rejects
        # the test form, so a field diagnosis says exactly which safe probe
        # failed rather than silently hiding the current state.
        supported = self.session.command("AT+CPCMREG=?", timeout=5)
        current = self.session.command("AT+CPCMREG?", timeout=5)
        self.reporter("CPCMREG capability: %s; current: %s" %
                      (voice.response_text(supported), voice.response_text(current)))
        if not supported.ok:
            raise BridgeError("AT+CPCMREG=? was not accepted: %s" % supported.final)
        text = " ".join(supported.lines)
        if "0-1" not in text.replace(" ", ""):
            raise BridgeError("AT+CPCMREG=? did not report the required (0-1) capability")
        if not current.ok:
            raise BridgeError("AT+CPCMREG? was not accepted: %s" % current.final)
        current_state = parse_cpcmreg_state(current.lines)
        if current_state is None:
            raise BridgeError("AT+CPCMREG? did not provide an unambiguous 0/1 state")
        self.pcm_was_preexisting = current_state == 1
        return current_state

    def report_pre_pcm_failure_diagnostics(self):
        """Best-effort CEER plus safe call-evidence summary before owned-call CHUP.

        This is deliberately idempotent because the active-setup controller and
        its foreground caller can both observe the same failure.  A CEER reply
        is useful only before CHUP changes the modem's last-call reason, but a
        failed diagnostic must never prevent the existing safety cleanup.
        """
        if self.pre_pcm_failure_diagnostics_reported:
            return
        self.pre_pcm_failure_diagnostics_reported = True
        self.reporter("Call did not reach active PCM bridge phase; last call evidence: %s." %
                      self.last_call_evidence)
        try:
            response = self.session.command("AT+CEER", timeout=5)
            self.reporter("AT+CEER: %s" % voice.response_text(response))
        except (Exception, KeyboardInterrupt) as exc:
            self.reporter("AT+CEER unavailable: %s" % exc)

    def wait_for_active_call(self, timeout=30.0, poll_seconds=2.0):
        """Require a voice-begin URC or CLCC active state; command OK is insufficient."""
        end = self.clock() + timeout
        next_poll = self.clock()
        while self.clock() < end:
            line = self.session.read_urc(timeout=min(0.25, max(0.01, end - self.clock())))
            if is_voice_begin(line):
                self.last_call_evidence = "voice-call begin indication"
                self.call_active = True
                self.reporter("Voice call begin URC received; enabling PCM is now permitted.")
                return True
            if is_voice_end(line):
                self.last_call_evidence = "voice-call end indication"
                raise BridgeError("voice call ended before PCM start: %s" % line)
            now = self.clock()
            if now >= next_poll:
                reply = self._command_ok("AT+CLCC", timeout=5)
                evidence = reply.lines + reply.urcs
                self.last_call_evidence = summarize_call_evidence(evidence)
                # ATSession preserves unfamiliar voice URCs as response lines;
                # do not lose a BEGIN/END simply because it interleaved CLCC.
                if any(is_voice_end(item) for item in evidence):
                    raise BridgeError("voice call ended before PCM start")
                if any(is_voice_begin(item) for item in evidence) or has_active_clcc(evidence):
                    self.call_active = True
                    self.reporter("AT+CLCC reports an active call; enabling PCM is now permitted.")
                    return True
                next_poll = now + poll_seconds
        raise BridgeError("timed out waiting for VOICE CALL: BEGIN or +CLCC active; PCM was not enabled")

    def start_for_active_call(self, bridge_kwargs):
        try:
            current_state = self.verify_capability()
            if current_state == 1:
                raise BridgeError("CPCMREG is already 1; refuse to take over or later disable another process's PCM session")
            self.wait_for_active_call(bridge_kwargs.pop("wait_timeout", 30.0))
            # This is intentionally the first CPCMREG=1 command in the
            # lifecycle.  Mark before sending because a lost response leaves
            # the modem's state unknown and requires best-effort rollback.
            self.pcm_enable_attempted = True
            enabled = self._command_ok("AT+CPCMREG=1", timeout=5)
            self.pcm_enabled = True
            if any(is_voice_end(item) for item in enabled.lines + enabled.urcs):
                raise BridgeError("voice call ended while PCM was being enabled")
            self.bridge = self.bridge_factory(**bridge_kwargs)
            self.bridge.start()
            self.bridge_active_started_at = self.clock()
            return self.bridge
        except Exception:
            # Preserve the modem's last-call cause before cleanup CHUP can
            # replace it.  Existing-call mode has no owned outbound/inbound
            # request and therefore never performs this call-specific query.
            if self.owned_call and self.bridge_active_started_at is None:
                self.report_pre_pcm_failure_diagnostics()
            self.cleanup(hangup=self.owned_call)
            raise

    def run_until_call_end(self, poll_seconds=2.0, max_active_seconds=None):
        """Run the started bridge until call end or an optional active-call limit.

        ``max_active_seconds`` deliberately measures only the phase beginning
        after ``bridge.start()`` has completed.  The foreground caller owns the
        normal cleanup in its ``finally`` block, so a limit expiry returns here
        rather than forcibly terminating the process or bypassing AT cleanup.
        """
        deadline = None
        if max_active_seconds is not None:
            try:
                max_active_seconds = float(max_active_seconds)
            except (TypeError, ValueError):
                raise BridgeError("max active seconds must be a finite positive number")
            if not math.isfinite(max_active_seconds) or max_active_seconds <= 0:
                raise BridgeError("max active seconds must be a finite positive number")
            if self.bridge_active_started_at is None:
                raise BridgeError("PCM bridge has not entered its active audio phase")
            deadline = self.bridge_active_started_at + max_active_seconds
        next_poll = self.clock() + poll_seconds
        last = self.clock()
        prior = self.bridge.stats_snapshot()
        try:
            while not self.bridge.stop_event.is_set():
                now = self.clock()
                if deadline is not None and now >= deadline:
                    self.reporter("Maximum active-call duration reached; stopping PCM and running normal cleanup.")
                    return
                urc_timeout = 0.25
                if deadline is not None:
                    # Do not sleep beyond the deadline just because no URC is
                    # arriving.  This keeps a short budget useful while still
                    # using ordinary controller/AT teardown below.
                    urc_timeout = min(urc_timeout, max(0.0, deadline - now))
                line = self.session.read_urc(timeout=urc_timeout)
                if is_voice_end(line):
                    self.reporter("Voice call ended: %s" % line)
                    return
                now = self.clock()
                if deadline is not None and now >= deadline:
                    self.reporter("Maximum active-call duration reached; stopping PCM and running normal cleanup.")
                    return
                if now >= next_poll:
                    clcc_timeout = 5
                    if deadline is not None:
                        remaining = deadline - now
                        if remaining <= 0:
                            self.reporter("Maximum active-call duration reached; stopping PCM and running normal cleanup.")
                            return
                        # CLCC is a helpful liveness check, not a reason to
                        # overrun the explicit cost limit.  Its transaction
                        # may block while waiting for a modem final result, so
                        # bound that wait by the active-call time remaining.
                        clcc_timeout = min(clcc_timeout, remaining)
                    try:
                        reply = self._command_ok("AT+CLCC", timeout=clcc_timeout)
                    except voice.ATTimeout:
                        # A timeout bounded by the last remaining slice is an
                        # ordinary limit expiry; return to command_bridge's
                        # normal finally cleanup rather than reporting an AT
                        # failure or bypassing teardown.
                        if deadline is not None and self.clock() >= deadline:
                            self.reporter("Maximum active-call duration reached; stopping PCM and running normal cleanup.")
                            return
                        raise
                    evidence = reply.lines + reply.urcs
                    # An END embedded in the CLCC transaction wins over any
                    # stale active row in that same response.
                    if any(is_voice_end(item) for item in evidence):
                        self.reporter("Voice call ended while checking +CLCC; stopping PCM.")
                        return
                    if not has_active_clcc(evidence):
                        self.reporter("AT+CLCC no longer reports an active call; stopping PCM.")
                        return
                    next_poll = now + poll_seconds
                if now - last >= 1.0:
                    current = self.bridge.stats_snapshot()
                    elapsed = now - last
                    self.reporter("PCM rate: RX %.0f B/s, TX %.0f B/s; drops RX/TX %d/%d; short writes %d" %
                                  ((current["rx_bytes"] - prior["rx_bytes"]) / elapsed,
                                   (current["tx_bytes"] - prior["tx_bytes"]) / elapsed,
                                   current["rx_dropped"], current["tx_dropped"], current["short_writes"]))
                    prior, last = current, now
            if self.bridge.error:
                raise BridgeError("PCM bridge stopped after worker error: %s" % self.bridge.error)
        finally:
            pass

    def cleanup(self, hangup=False):
        """Local audio cleanup plus best-effort modem cleanup, safe on every path."""
        if self.bridge is not None:
            self.bridge.stop()
            self.bridge = None
        self.bridge_active_started_at = None
        # For a call owned by this invocation, end the network call before
        # disabling its PCM path, matching the documented END -> CPCMREG=0
        # ordering.  Existing calls are never hung up unless explicitly asked.
        if hangup and not self.hangup_confirmed:
            self.hangup_attempted = True
            self.hangup_confirmed = voice.best_effort_hangup(
                self.session, "Bridge cleanup", reporter=self.reporter)
        if self.pcm_enable_attempted and not self.pcm_was_preexisting:
            details = []
            try:
                reply = self.session.command("AT+CPCMREG=0", timeout=5)
                if not reply.ok:
                    details.append("AT+CPCMREG=0 returned %s" % reply.final)
            except Exception as exc:
                details.append("AT+CPCMREG=0 failed: %s" % exc)
            # A naked OK may be a late final result from CPCMREG=1.  Only a
            # tagged state query can clear the uncertainty marker.
            confirmed = False
            for _ in range(2):
                try:
                    state_reply = self.session.command("AT+CPCMREG?", timeout=5)
                    state = parse_cpcmreg_state(state_reply.lines + state_reply.urcs)
                    if state_reply.ok and state == 0:
                        confirmed = True
                        break
                    if state is not None:
                        details.append("AT+CPCMREG? reports %d" % state)
                    elif not state_reply.ok:
                        details.append("AT+CPCMREG? returned %s" % state_reply.final)
                    else:
                        details.append("AT+CPCMREG? returned no tagged state")
                except Exception as exc:
                    details.append("AT+CPCMREG? failed: %s" % exc)
            if confirmed:
                self.pcm_enabled = False
                self.pcm_enable_attempted = False
                self.pcm_disable_confirmed = True
                self.reporter("PCM disabled; +CPCMREG: 0 state confirmed.")
            else:
                # Do not erase the local uncertainty marker: user must know
                # that a later process may encounter an enabled PCM state.
                self.reporter("Best-effort AT+CPCMREG=0 attempted; PCM state not confirmed: %s" %
                              ("; ".join(details) if details else "no tagged state"))


def _bridge_kwargs_from_args(args, ports=None):
    if args.audio_baud < MIN_AUDIO_BAUD:
        raise BridgeError("--audio-baud %d is below %d; it cannot carry 8 kHz/16-bit PCM" %
                          (args.audio_baud, MIN_AUDIO_BAUD))
    if args.audio_port:
        audio_info = require_explicit_audio_port_role(args.audio_port, ports=ports)
        audio_port = args.audio_port
    else:
        audio_info = find_audio_port_info(ports=ports)
        audio_port = audio_info.device
    return ({"audio_port": audio_port,
             "input_device": parse_device_identifier(args.input_device),
             "output_device": parse_device_identifier(args.output_device),
             "host_rate": args.host_rate, "audio_baud": args.audio_baud,
             "capture_rx": args.capture_rx, "capture_tx": args.capture_tx,
             "wait_timeout": args.wait_timeout}, audio_info)


def command_capability(args, ports=None):
    at_port = args.at_port or select_at_port(args.baud, args.timeout)
    require_explicit_at_port_role(at_port, ports=ports)
    session = voice.ATSession(at_port, args.baud, args.timeout).open()
    try:
        voice.require_target_identity(session)
        controller = CallPCMController(session)
        controller.verify_capability()
        return 0
    finally:
        session.close()


def command_bridge(args, ports=None):
    at_port = args.at_port or select_at_port(args.baud, args.timeout)
    at_info = require_explicit_at_port_role(at_port, ports=ports)
    # Fail configuration/identity checks before the user could request a call.
    kwargs, audio_info = _bridge_kwargs_from_args(args, ports=ports)
    if not same_target_composite(at_info, audio_info):
        raise BridgeError("AT and Audio ports are not proven to belong to the same physical SIM8202G composite device")
    if canonical_port_name(kwargs["audio_port"]) == canonical_port_name(at_port):
        raise BridgeError("AT port and Audio port must be different COM interfaces")
    session = voice.ATSession(at_port, args.baud, args.timeout).open()
    try:
        voice.require_target_identity(session)
    except Exception:
        session.close()
        raise
    controller = CallPCMController(session)
    request_attempted = False
    try:
        if args.mode == "dial":
            number = voice.validate_number(args.number)
            # Set this before invoking the transaction: serial write may have
            # reached the modem even if final OK/URC is lost or Ctrl+C occurs.
            request_attempted = True
            controller.call_request_attempted = True
            controller._command_ok("ATD%s;" % number, timeout=args.call_timeout,
                                   record_call_evidence=True)
            controller.call_request_sent = True
            controller.owned_call = True
            controller.reporter("Dial request accepted; waiting for real call activity before PCM.")
        elif args.mode == "answer":
            request_attempted = True
            controller.call_request_attempted = True
            controller._command_ok("ATA", timeout=args.call_timeout,
                                   record_call_evidence=True)
            controller.call_request_sent = True
            controller.owned_call = True
            controller.reporter("Answer request accepted; waiting for real call activity before PCM.")
        else:
            controller.reporter("Waiting for an already-active call; this mode will not hang it up by default.")
        controller.start_for_active_call(kwargs)
        # The controller records its start timestamp only after active-call
        # evidence, CPCMREG=1, and local audio-bridge startup all succeeded.
        # Returning on limit expiry deliberately falls through to this
        # function's normal ``finally`` cleanup path.
        controller.run_until_call_end(args.clcc_poll,
                                      max_active_seconds=getattr(args, "max_active_seconds", None))
        return 0
    except KeyboardInterrupt:
        if request_attempted and controller.bridge_active_started_at is None:
            controller.report_pre_pcm_failure_diagnostics()
        controller.reporter("Interrupted; stopping PCM bridge.")
        return 130
    except (BridgeError, voice.ATTimeout, voice.ATError, OSError) as exc:
        if request_attempted and controller.bridge_active_started_at is None:
            controller.report_pre_pcm_failure_diagnostics()
        controller.reporter("Bridge failed: %s" % exc)
        return 2
    finally:
        # A request may have reached the modem even when no final result was
        # received.  Conservative cleanup applies only to dial/answer, never
        # to --existing-call unless the user explicitly asked for it.
        controller.cleanup(hangup=request_attempted or args.hangup_on_exit)
        session.close()


def make_parser():
    parser = argparse.ArgumentParser(description="SIM8202G-M2 experimental USB PCM voice bridge (not UAC)")
    parser.add_argument("--at-port", help="AT COM port override, e.g. COM6")
    parser.add_argument("--baud", type=int, default=115200, help="AT COM baud rate (default: 115200)")
    parser.add_argument("--timeout", type=float, default=3.0, help="normal AT timeout seconds")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("devices", help="list host PortAudio input/output endpoints; opens no modem port")
    sub.add_parser("capability", help="safely query AT+CPCMREG capability/current value; does not enable PCM")
    bridge = sub.add_parser("bridge", help="bridge an active/new/answered call to default host microphone/speakers")
    modes = bridge.add_mutually_exclusive_group(required=True)
    modes.add_argument("--existing-call", dest="mode", action="store_const", const="existing",
                       help="wait for an already active call (does not hang up by default)")
    modes.add_argument("--dial", dest="number", metavar="NUMBER", help="dial validated NUMBER, then bridge")
    modes.add_argument("--answer", dest="mode", action="store_const", const="answer", help="answer, then bridge")
    bridge.add_argument("--audio-port", help="Audio COM port override, e.g. COM5 (binary PCM only)")
    bridge.add_argument("--audio-baud", type=int, default=DEFAULT_AUDIO_BAUD,
                        help="Audio COM baud rate (default: 921600; safety minimum 230400 for candidate PCM)")
    bridge.add_argument("--input-device", help="PortAudio input device index or name (default system input)")
    bridge.add_argument("--output-device", help="PortAudio output device index or name (default system output)")
    bridge.add_argument("--host-rate", type=int, help="force host input/output rate; defaults to each device native rate")
    bridge.add_argument("--wait-timeout", type=float, default=30.0, help="seconds to wait for real active-call evidence")
    bridge.add_argument("--call-timeout", type=float, default=30.0, help="ATD/ATA command timeout seconds")
    bridge.add_argument("--clcc-poll", type=float, default=2.0, help="active-call polling interval seconds")
    bridge.add_argument("--max-active-seconds", type=positive_seconds,
                        help="optional finite positive limit measured after PCM bridge startup")
    bridge.add_argument("--hangup-on-exit", action="store_true", help="also AT+CHUP an existing call on exit")
    bridge.add_argument("--capture-rx", metavar="FILE", help="explicitly save modem-to-speaker raw s16le PCM; refuses overwrite")
    bridge.add_argument("--capture-tx", metavar="FILE", help="explicitly save microphone-to-modem raw s16le PCM; refuses overwrite")
    return parser


def main(argv=None):
    args = make_parser().parse_args(argv)
    if args.action == "devices":
        try:
            enumerate_audio_devices()
            return 0
        except BridgeError as exc:
            print("Cannot enumerate audio devices: %s" % exc, file=sys.stderr)
            return 2
    if args.action == "capability":
        try:
            return command_capability(args)
        except (BridgeError, voice.ATTimeout, voice.ATError, OSError) as exc:
            print("Capability query failed: %s" % exc, file=sys.stderr)
            return 2
    if args.action == "bridge":
        if args.number is not None:
            try:
                args.number = voice.validate_number(args.number)
            except ValueError as exc:
                print("Invalid dial number: %s" % exc, file=sys.stderr)
                return 2
            args.mode = "dial"
        try:
            return command_bridge(args)
        except (BridgeError, voice.ATTimeout, voice.ATError, OSError) as exc:
            print("Cannot start bridge: %s" % exc, file=sys.stderr)
            return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
