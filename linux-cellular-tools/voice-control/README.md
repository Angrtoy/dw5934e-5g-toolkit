# DW5934e QMI Voice control — control plane only

`dw5934e-voice-control` sends QMI **call-control** requests through the
existing MBIM proxy.  It is not a telephone application: it provides neither
microphone capture, speaker playback, nor any other call-media/audio path.

Build against the target's installed libqmi headers (compile/link only; do not
run the produced binary as part of build validation):

```sh
gcc -Wall -Wextra -Werror -O2 dw5934e-voice-control.c -o dw5934e-voice-control \
  $(pkg-config --cflags --libs qmi-glib)
```

The normal operational commands, when separately authorised on a suitable
host, are `sudo ./dw5934e-voice-control capabilities`, `status`, and
`voice-domain`.  Stateful
commands require the exact final confirmation token:

```text
dial NUMBER --confirm
dial-ims NUMBER --confirm
dial-immediate-hangup 10010 --confirm
answer CALL_ID --confirm
hangup CALL_ID --confirm
```

Dial accepts only 3–32 ASCII digits and rejects common emergency numbers.  The
program never prints the dialled number.  Those checks and `--confirm` are
intentional safety gates; do not bypass them.  Obtain explicit confirmation
before any call-affecting command and never force-kill the process to stop it:
send SIGINT/SIGTERM/SIGHUP and allow its asynchronous cleanup to finish.

Every path, including normal success, releases the allocated VOICE client with
`RELEASE_CID` and then closes the QMI device.  If either cleanup operation
fails the program emits `CLEANUP_RELEASE_FAILED:` or
`CLEANUP_CLOSE_FAILED:` and exits non-zero.  This CID cleanup is control-plane
resource hygiene; it does not establish voice audio.

## Read-only Voice Domain Preference

`voice-domain` is a read-only raw QMI VOICE **Get Config** query. Like every
non-capabilities operation, it first allocates a VOICE CID and successfully
binds the primary subscription; it then sends QMI VOICE Get Config (`0x0041`)
with exactly one request TLV: `0x18`, length one, value `0x01` (request Voice
Domain Preference). It never sends VOICE Set Config (`0x0040`).

The response must contain a successful Result TLV (`0x02`) and Voice Domain
Preference TLV (`0x17`) of at least one byte. It prints one stable,
machine-readable line:

```text
VOICE_DOMAIN_PREFERENCE=0 CS-only
VOICE_DOMAIN_PREFERENCE=1 PS-only
VOICE_DOMAIN_PREFERENCE=2 CS-preferred
VOICE_DOMAIN_PREFERENCE=3 PS-preferred
VOICE_DOMAIN_PREFERENCE=N unknown(N)
```

The command makes no configuration change. It exists because the target's
VOICE service version is known to be `2.0`: qmicli only requests this Get
Config field for a later Voice version, while the public VOICE `0x0041` schema
defines the request field and the target supports the message. A transport,
protocol, missing-TLV, cancellation, release, or close error remains nonzero
and follows the same asynchronous cleanup path as every other command.

Before `status`, `voice-domain`, `dial`, `dial-ims`, `answer`, or `hangup`, the
tool binds that allocated VOICE CID to the primary subscription with the raw QMI VOICE **Bind
Subscription** request (`0x0044`, TLV `0x01` byte `0`).  The asynchronous bind
response must contain a successful Result TLV (`0x02`) before the operational
request is sent; a transport, malformed-response, or QMI protocol failure
instead follows the normal release-and-close cleanup path.  `capabilities` is
deliberately a discovery-only request and does not bind a subscription.

## Dial request contract

For the public libqmi QMI VOICE `Dial Call` request (`0x0020`), the sole input
TLV is the mandatory ASCII `Calling Number` (`0x01`); a successful response
then supplies its `Call ID` in TLV `0x10`.  The tool sets that required field
through `qmi_message_voice_dial_call_input_set_calling_number()`.  The target's
installed libqmi API and the upstream schema do **not** provide Dial Call
setters for call type, call mode, audio attributes, codecs, or a media route.
Do not hand-add or guess such TLVs to work around a modem `InvalidArgument`
response: that would no longer be the supported public request contract and
could itself be rejected.  A modem-side protocol error after the mandatory TLV
has been serialized is not evidence that no call-ID parser or output getter is
missing; no call ID is expected on an unsuccessful result.

## Explicit PS-domain IMS Dial request contract

`dial-ims NUMBER --confirm` is a separate, explicitly named raw-QMI path.  It
does **not** change `dial`, whose public libqmi request contract remains the
number-only request described above.  Both commands retain the same 3–32 ASCII
digit validation, emergency-number refusal, confirmation requirement, primary
VOICE subscription bind, CID release, and device-close lifecycle.  Neither
prints the dialled number.

After the primary Bind Subscription succeeds, `dial-ims` constructs QMI VOICE
Dial Call (`0x0020`) on the allocated VOICE CID with the client's next
transaction ID.  Its request has exactly these TLVs, in this order:

| TLV | Width/value | Meaning |
|---:|---|---|
| `0x01` | ASCII number, no size prefix | Calling Number |
| `0x10` | one byte `0x02` | `CALL_TYPE_VOICE_IP` |
| `0x18` | 8-byte little-endian `0x0000000000000003` | audio attributes TX \| RX |
| `0x19` | 8-byte little-endian `0x0000000000000000` | zeroed auxiliary audio attributes |

This is an explicit ordinary PS-domain IMS voice request form reproduced from
the public SDM670/710 QCRIL Voice implementation, not a guessed extension of
the public number-only `dial` API.  Source evidence is Qualcomm vendor-source
mirror commit `9f4c0d4b9116d6e31ade3b7dac6c70996c14d0c1`:

```text
qcril-hal/qcril_qmi/qcril_qmi_voice.cc:12590-12665,23075-23120
qcril-qmi-services/voice_service_v02.c:1391-1449
voice_service_common_v02.h:83-100
```

It deliberately contains no service-type, CLIR, PI, presentation, or any other
TLV.  The raw response parser requires a complete Result TLV `0x02` (two
little-endian `guint16` values) and treats nonzero status as
`QMI_PROTOCOL_ERROR`.  Only a successful Result plus Call ID TLV `0x10` with
at least one byte emits `DIAL_ACCEPTED call_id=N`; every other outcome follows
the existing asynchronous CID-release and device-close cleanup path.

## Fixed 10010 immediate-owned-hangup action

`dial-immediate-hangup 10010 --confirm` is a narrowly fixed action for the
separately authorised CM capture wrapper; it accepts **only** `10010`, not a
general number.  It allocates and binds one ordinary VOICE client, sends exactly
one public QMI VOICE Dial Call request, and, only after that request's successful
response supplies this invocation's Call ID, sends QMI VOICE End Call for that
same ID in the same process and on the same client.  It never uses `status` or
any existing-call list to infer ownership, and it never sends a second Dial.

From immediately before submitting Dial until End Call succeeds or its bounded
retry path has explicitly failed, the process blocks SIGINT/SIGTERM/SIGHUP and
its GLib signal callback independently refuses to cancel the operation.  This
does not rely on an invoking shell's signal disposition.  End response/transport failure gets one bounded retry for
the already-proven ID only; no retry can originate another call.  A successful
run prints exactly one durable wrapper-capturable line:

```text
DIAL_IMMEDIATE_HANGUP_OK call_id=N
```

Only successful End Call permits a zero exit status.  Dial failure emits no End
Call.  An End failure after the bounded retry fails nonzero and then follows the
normal VOICE CID release/device-close cleanup; SIGKILL and power loss cannot be
recovered by userspace.

Offline lifecycle checks (no modem node and no tool binary are opened/run):

```sh
python3 test_static_paths.py
python3 test_state_machine.py
python3 test_dial_protocol_contract.py
python3 test_dial_ims_protocol_contract.py
python3 test_combined_dial_immediate_hangup_contract.py
python3 test_voice_domain_contract.py
python3 test_validation_contract.py
python3 ../../analysis/build_validate_dw5934e_voice_control.py --offline
```
