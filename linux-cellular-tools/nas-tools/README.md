# DW5934e NAS Usage Preference experiment

`dw5934e-nas-usage-preference` is a deliberately constrained QMI **NAS
control-plane** experiment for an authorised target.  It opens the target's
existing QMI-over-MBIM proxy at `/dev/wwan0mbim0`, allocates a temporary NAS
client, and uses only the public libqmi System Selection Preference operations:

* NAS Get System Selection Preference (`0x0034`), to read Usage Preference;
* NAS Set System Selection Preference (`0x0033`), with **only** its Usage
  Preference setter populated.

It accepts no numeric or raw-QMI value.  The only values it can request are the
public NAS enum values `voice-centric` (1) and `data-centric` (2).  A set first
requires a successful old-value read that is also one of those two values.  It
then reads the value back and fails if the readback differs from the requested
value.

This is not a call-control, audio, registration, attach, PDP/PDN, or dialling
tool.  It neither starts data nor starts a call.  It also performs no automatic
restoration after a set attempt.  That decision must remain outside this tool,
after observing the target.

## Build (offline; do not run during build validation)

Build on the target or an SDK with that target's `qmi-glib` development headers:

```sh
gcc -Wall -Wextra -Werror -O2 dw5934e-nas-usage-preference.c \
  -o dw5934e-nas-usage-preference $(pkg-config --cflags --libs qmi-glib)
```

The source depends on the public `QmiNasUsagePreference` and NAS System
Selection Preference APIs, whose Usage Preference support is present in libqmi
1.24 and later.  Compile against the installed target headers, rather than
assuming a host's libqmi ABI matches them.

## Authorised operation

```sh
sudo ./dw5934e-nas-usage-preference get
sudo ./dw5934e-nas-usage-preference set-voice-centric --confirm
sudo ./dw5934e-nas-usage-preference set-data-centric --confirm
```

The confirmation token is mandatory for either state change.  Structured output
uses only labels, never raw values:

```text
OLD=voice-centric
REQUESTED=data-centric
READBACK=data-centric
```

`get` prints `OLD=...` and makes no configuration change.  A set succeeds only
after the `READBACK` label equals `REQUESTED`; all QMI, timeout, unsupported
value, and cleanup errors exit non-zero.

The lifetime is intentional: open MBIM proxy, allocate NAS CID, Get, optional
Set, Get readback, explicit `RELEASE_CID`, then close.  SIGINT, SIGTERM, and
SIGHUP stop advancement and lead to the same release-and-close path after the
currently outstanding bounded async request completes.  Do not use `SIGKILL`
or an external forced short timeout, because neither gives the process an
opportunity to release its allocated CID and close the proxy cleanly.

## Operational risk

Usage Preference is a system-selection preference, not a proof that a voice
stack is present or that calls will work.  Applying it can cause service
selection or registration to be reconsidered.  That may temporarily interrupt
data service, change registration state, or have no visible effect if modem,
carrier, subscription, or firmware policy overrides it.  Run only in a
maintenance window with an independent way to observe registration and data
continuity.  The tool intentionally makes no interpretation of a successful
readback beyond showing that the modem returned the requested enum.

## Offline static contract test

The test opens no device and sends no QMI request:

```sh
python3 test_static_contract.py
```

It checks the limited command grammar, required MBIM-proxy lifecycle, explicit
CID release and close, the initial/readback Get calls, and that the sole NAS
System Selection Preference input setter in the source is Usage Preference.
