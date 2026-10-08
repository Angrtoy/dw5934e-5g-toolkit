# SIM8202G-M2 voice-call controller and experimental USB PCM bridge

`sim8202g_voice.py` is a deliberately narrow Windows/Python 3.8-compatible
controller for a **SIMCom SIM8202G-M2** modem's AT COM port.  It checks modem
state, makes an outgoing call, answers, hangs up, and prints unsolicited result
codes (URCs).  `sim8202g_pcm_bridge.py` is a separate, experimental program
which can bridge a real active call's modem PCM stream to the default Windows
microphone and speakers (or explicitly selected PortAudio endpoints).

It does **not** modify firmware, NV items, USB composition, or modem radio
configuration.  In particular it does not issue `AT+VOLTESETTING`, `AT+CNV`,
`AT+CUSBCFG`, or any write/configuration command outside the documented
call-control/status set.

## Install and start

1. Install the appropriate SIMCom/Windows USB serial driver and connect a
   powered SIM8202G-M2.  Windows Device Manager should show its serial COM
   interfaces.  This tool prefers an interface whose USB ID is `1E0E:9001`.
2. With Python 3.8 or newer, install the dependencies:

   ```bat
   py -3 -m pip install -r requirements.txt
   ```

3. Enumerate COM functions and perform identity probes (`AT`, `ATI`,
   `AT+CGMR`) only on interfaces Windows positively labels **AT Port** or
   **Modem**:

   ```bat
   py -3 sim8202g_voice.py probe
   ```

   The output says why a port was selected and which functions were skipped
   without opening.  Among responsive `1E0E:9001` functions, **AT Port** is
   preferred, then **Modem**.  **Audio**, **NMEA**, **Diagnostics**, and unknown
   descriptions are never speculatively probed; neither are AT/Modem functions
   with another VID/PID.  An explicit override must also resolve to a currently
   enumerated AT Port/Modem with target USB identity `1E0E:9001`; it cannot
   bypass either boundary:

   ```bat
   py -3 sim8202g_voice.py --port COM6 probe
   py -3 sim8202g_voice.py --port COM6 status
   ```

Default baud rate is 115200; pass `--baud 921600` only if the installed modem
profile uses it.

## Commands

```bat
py -3 sim8202g_voice.py status
py -3 sim8202g_voice.py dial NUMBER
py -3 sim8202g_voice.py answer
py -3 sim8202g_voice.py hangup
py -3 sim8202g_voice.py monitor
```

There is no default destination.  `dial` accepts only an optional leading `+`
and 3--20 digits, so a number cannot inject another AT command.  During dialing
or answering, a timeout/read failure or Ctrl+C is treated as a request that may
already have reached the modem: the tool makes a best-effort `AT+CHUP` and
then requires a tagged `+CPAS: 0` state query before it says the call is idle.
A naked `OK` is not accepted because it could be the prior command's late final
result.  Ctrl+C in `monitor` only stops monitoring and deliberately does not
alter an active call.  A call-control failure also requests `AT+CEER` for the
modem's last-call reason.

`monitor` initializes its own serial session first, including the documented
call and registration URC modes, so it does not depend on having run `status`
in an earlier process.

## Experimental USB PCM voice bridge

The SIM8202G-M2's **SimTech Audio 9001** COM interface is **not** a Windows
USB Audio Class (UAC) endpoint.  It is a binary serial PCM transport.  On the
tested firmware family, the safe, read-only capability queries
`AT+CPCMREG=?` and `AT+CPCMREG?` report that `CPCMREG` supports `0-1` and is
normally `0`.  During a real voice call, firmware documentation indicates that
`AT+CPCMREG=1` makes the separate Audio COM interface carry PCM raw data in
both directions, then `AT+CPCMREG=0` stops it.  This repository has **not yet
verified an actual call or audible two-way audio**; consider the bridge
experimental until the acceptance procedure below has passed.

The bridge assumes the documented/default transport candidate: 8 kHz,
mono, signed 16-bit little-endian linear PCM.  It deliberately treats COM
reads and writes as arbitrary binary streams, handles short reads/short writes
and 16-bit alignment, and does not assume that one serial read is one PCM
frame.  It resamples each default Windows endpoint's native sample rate (often
48 kHz) statefully to/from 8 kHz.  The exact channel/sample convention and
actual byte rate still require real-call verification.  The on-screen RX/TX
byte-rate counters should be roughly 16 kB/s per direction for that format;
they are a diagnostic, not proof of intelligible audio.

First list the Windows audio endpoints; this opens no modem port and does not
save audio:

```bat
py -3 sim8202g_pcm_bridge.py devices
```

The following query is safe while idle: it sends only `AT+CPCMREG=?` and
`AT+CPCMREG?`, never enables PCM.

```bat
py -3 sim8202g_pcm_bridge.py --at-port COM6 capability
```

With a permitted, voice-capable SIM and a real incoming/active call, examples
are:

```bat
:: Wait for an already active call.  It does not hang up that call by default.
py -3 sim8202g_pcm_bridge.py bridge --existing-call

:: Make/answer a user-requested call and bridge it after real active-call evidence.
:: Replace NUMBER with a permitted test destination; no destination is supplied by this tool.
py -3 sim8202g_pcm_bridge.py bridge --dial NUMBER
py -3 sim8202g_pcm_bridge.py bridge --answer

:: Optional cost guard for a dialed or answered call: 60 seconds of active PCM bridge time.
py -3 sim8202g_pcm_bridge.py bridge --dial NUMBER --max-active-seconds 60

:: Explicit endpoint and COM overrides for unusual drivers/defaults.
py -3 sim8202g_pcm_bridge.py --at-port COM6 bridge --existing-call --audio-port COM5 --input-device 2 --output-device 4
```

There is no default number.  `--dial` uses the same strict optional-`+`,
3--20 digit validation as the AT tool.  Automatic bridge selection probes only
Windows descriptions explicitly labelled **AT Port** (with **Modem** only as a
fallback); it deliberately does not speculate on an expected-but-unknown,
NMEA, Diagnostics, or Audio interface.  An explicit `--at-port` that Windows
does not describe as an AT Port/Modem with target VID/PID is rejected.  It selects
a single expected `Audio` description without sending **any** text to that
binary port.  Use explicit `--audio-port` if Windows shows more than one
candidate.  The override must still resolve to a currently enumerated
**Audio** interface with target VID/PID; AT Port, Modem, NMEA, Diagnostics,
unknown, absent, and other-vendor ports are rejected before any call or
`CPCMREG=1`.  The AT and Audio functions must also have the same USB serial
number and composite-location root, preventing cross-wiring between two
modules.  `COM5` and `\\.\COM5` are treated as the same port and cannot be used
as both AT and Audio.

Audio COM opens at **921600** by default.  The candidate 8 kHz/16-bit mono
stream needs at least 16,000 byte/s in each direction; conventional 8N1 needs
160,000 baud with zero headroom.  The bridge uses the next conventional rate,
**230400**, as its safety minimum and rejects anything lower rather than
silently accepting the old 115200 setting.  The Audio port is opened with
XON/XOFF, RTS/CTS, and DSR/DTR flow control disabled.

For `--dial` and `--answer`, ATD/ATA `OK` means only that the request was
accepted.  It is not treated as a voice/IMS success.  The bridge waits for
`VOICE CALL: BEGIN` or a `+CLCC` active-call state before it can send
`AT+CPCMREG=1`.  It first requires a readback state of `CPCMREG=0`; if another
process already has it at `1`, this bridge refuses to take over or disable that
other process's stream.  It stops local writes on `VOICE CALL: END`, ordinary
call-end URCs, loss of active `CLCC`, Ctrl+C, or a worker failure.  A dial or
answer request is conservatively treated as possibly sent even if its final
`OK`/URC is lost, times out, or Ctrl+C arrives: this tool then first makes a
best-effort `AT+CHUP`, followed by best-effort `AT+CPCMREG=0`.  Existing-call
mode does not hang up unless `--hangup-on-exit` was explicit.  A failed/timeout
`CPCMREG=1` is also rolled back with `=0`.  Cleanup never treats a naked `OK` as
proof: call-idle confirmation requires tagged `+CPAS: 0`, and PCM-disable
confirmation requires tagged `+CPCMREG: 0`.  Missing or conflicting tagged
state is reported as **call/PCM state not confirmed**, not silently treated as
clean.  No VoLTE/NV/USB-composition command is sent.

If a `--dial` or `--answer` request fails, ends, or times out before the bridge
reaches its active PCM phase, the bridge first makes a best-effort `AT+CEER`
query **before** its conservative `AT+CHUP` cleanup can replace the modem's
last-call reason.  It also prints a safe summary of the last `+CLCC` or voice
call-state evidence, not a raw `+CLCC` row (which can contain a remote number).
An unavailable `AT+CEER` is reported but never prevents the normal
`CHUP`/`+CPAS: 0`/`CPCMREG=0` cleanup and verification sequence.
If the ATD transaction itself times out before returning a response, its
user-visible bridge error is likewise generic rather than echoing the complete
ATD command and destination number.

`bridge --max-active-seconds SECONDS` is an optional finite positive duration
for limiting real-call cost.  It does **not** start when `ATD`/`ATA` is sent or
when the call is merely being awaited.  It starts only after `VOICE CALL: BEGIN`
or active `+CLCC` evidence has allowed `AT+CPCMREG=1` and the local PCM bridge
has successfully started.  On expiry the controller returns through its normal
cleanup path rather than killing the process: a call initiated by `--dial` or
`--answer` receives best-effort `AT+CHUP` followed by tagged `+CPAS: 0`
verification, and the tool also requires tagged `+CPCMREG: 0` verification.
Existing-call mode still does not hang up without the separate explicit
`--hangup-on-exit` option.

By default no voice data is retained.  `--capture-rx FILE` and
`--capture-tx FILE` are the only opt-in raw s16le capture mechanisms; each
refuses to overwrite an existing file.  Treat these recordings as sensitive
user audio and protect/delete them appropriately.

## Phone Bluetooth audio is a separate host-profile problem

The PCM bridge can use any real PortAudio capture/playback endpoints, but a
phone paired to ordinary Windows Bluetooth does not automatically become such
a two-way phone endpoint.  Microsoft's documented HFP topology makes the
Windows PC the **Audio Gateway (AG)** and a Bluetooth headset the
**Hands-Free (HF)** accessory; the requested direction is the reverse (phone
AG, PC HF).  Windows' public `AudioPlaybackConnection` enables an **A2DP sink**
for phone-to-PC media playback, not an HFP HF service with SCO microphone
uplink.  Relevant Microsoft documentation:

- <https://learn.microsoft.com/en-us/windows-hardware/design/accessory-guidelines/bluetooth-accessory-guidelines/bluetooth-accessory-guidelines-classic-audio>
- <https://learn.microsoft.com/en-us/windows-hardware/drivers/bluetooth/bluetooth-classic-audio>
- <https://learn.microsoft.com/en-us/windows/apps/develop/media-playback/enable-remote-audio-playback>

Consequently, the immediately usable Windows path is the selected local
microphone/speaker (for this machine, the XIBERIA T10 endpoints).  Making an
Android/iPhone see this PC as a call headset would require a custom Windows HFP
HF profile/driver or a different host stack.  Current BlueZ and
PipeWire/WirePlumber document an `hfp_hf` role on Linux, so Linux is a viable
separate experiment, but BlueZ's newer native HF implementation remains
experimental and must be tested against the specific phone/controller before
it is treated as a deliverable:

- <https://bluez.readthedocs.io/en/latest/supported-features/>
- <https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/bluetooth.html>

## What `status` means

For the current serial session it sends conservative setup commands (`ATE0`,
extended errors, call URCs, hangup behavior and registration URC modes), then
reports identity/firmware, SIM readiness, signal, operator, all cellular
registration views, network information, and `AT+CLCC` call state.  It does
not query IMSI, ICCID, stored phone numbers, or other sensitive subscriber
identifiers.

`+CREG`, `+CGREG`, `+CEREG`, and `+C5GREG` status **1** means registered on the
home network; **5** means registered while roaming.  Other values explain a
not-registered/searching/denied condition.  Status **6** is SMS-only home
registration, not normal voice registration.  Crucially, LTE/EPS (`CEREG`) or 5G
registration is **not IMS registration** and cannot establish that VoLTE is
provisioned or that a voice call will work.  The operator, SIM, carrier profile
and network must support voice/VoLTE for the specific subscription.

For privacy, user-visible modem output redacts a labelled 14--16-digit
`IMEI:` value as `<redacted>`.  The tool does not query IMSI, ICCID, stored
phone numbers, or other subscriber identifiers.

## Hardware and carrier prerequisites

Before real calls, use an activated voice-capable SIM, correctly installed
antennas, stable power sized for cellular transmit peaks, and a carrier/network
where the subscription and local radio coverage permit voice service.  A
registered data network alone is insufficient.  Driver installation only makes
the AT port available; it does not enable carrier voice service.

The AT controller itself does not carry audio and the USB path is **not UAC**.
Unlike the earlier assumption that only an external PCM/I2S codec could carry
audio, this modem/driver combination exposes a separate candidate USB binary
PCM transport through `CPCMREG`.  An external codec/board audio path may still
be appropriate, but it is not the only path worth testing.  The USB bridge is
not a claim that the carrier, firmware, or host driver has delivered usable
voice audio.

## Suggested real-hardware acceptance procedure

1. Confirm Device Manager identifies the expected USB functions, run `probe`,
   and record its chosen AT COM port.
2. Run `status`; check SIM readiness, usable RF signal and cellular
   registration.  Treat these as prerequisites, not proof of IMS.
3. With a known voice-capable test subscription and a permitted test number,
   run `dial NUMBER`, watch its result/URCs, then use `hangup`.  Test an incoming
   call with `monitor` followed by `answer` and `hangup`.
4. Run `sim8202g_pcm_bridge.py bridge --existing-call` (or its explicit
   dial/answer form), confirm it does not enable PCM until `VOICE CALL: BEGIN`
   or active `+CLCC`, observe approximately 16 kB/s RX/TX for the candidate
   format, and verify intelligible sound in both directions using the selected
   Windows microphone and speakers.  If it fails, retain only explicit capture
   files needed for diagnosis and report the firmware/URCs/byte rates.

This workspace has run only safe identity/capability queries and host-audio
open/read/silent-write checks on the physical modem/PC.  It has not sent
`ATD`, `ATA`, or `AT+CPCMREG=1`, and has not verified an actual call or audible
two-way modem audio.  Those results still depend on the SIM, carrier, firmware
and hardware.

## Tests

```bat
py -3 -m unittest discover -s tests -v
```

The tests use fake serial/PortAudio-style objects; they cover injection rejection, port
preference/selection, terminal responses and URC retention, registration
interpretation, `CEREG` versus IMS wording, dial-failure `CEER`, and the
best-effort Ctrl+C hangup path, plus PCM port selection, state gating,
resampling/alignment, short writes, and exceptional cleanup.  They are
protocol/stream logic tests, not hardware, PortAudio-host, real-call, or carrier
validation.
