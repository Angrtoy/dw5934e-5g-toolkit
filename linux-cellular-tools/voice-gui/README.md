# DW5934e GTK dialer — call control only

This independent GTK3 UI invokes the existing dw5934e-voice-control C backend
for one deliberate operation at a time. It does **not** implement USB/PCM
audio, microphone capture, speaker playback, modem audio routing, or any
call-media path. An accepted request means only that the modem accepted call
control; it does not prove that a PC audio call is established.

## Safety boundary

Normal use invokes exactly this argv asynchronously, never through a shell:

```text
/usr/bin/pkexec /usr/local/libexec/dw5934e-voice-control COMMAND ...
```

The installed path is deliberately fixed. The --backend and --no-pkexec options
create an explicitly unprivileged test/development mode and must be used
together. Thus an arbitrary backend path can never be handed to pkexec. The C
backend's own final --confirm, validation, and emergency-number rejection
remain authoritative. The UI also asks for explicit confirmation before dial,
answer, and hangup.

There is no automatic QMI polling: press **手动刷新状态**. Operations are
disabled while the backend runs. Cleanup failures are displayed as failures;
the UI never force-kills the backend, so its CID release/close lifecycle can
finish.

## Included installation templates

install-system.sh and uninstall-system.sh are templates and have not been run.
They require root, reject symlinks and existing destinations, use fixed
absolute destinations, install root:root non-group/world-writable files, and
do not authorize arbitrary commands. First build/review the C backend per
../dw5934e_voice_control/README.md; then deliberately run:

```sh
sudo ./install-system.sh /absolute/path/to/dw5934e-voice-control
```

Run install-user-desktop.sh separately as the desktop user for the supplied
user-level .desktop entry. It refuses an existing desktop entry and never
writes a system location.

## Offline checks

These do not load GTK, run pkexec, invoke a backend, or open a modem node:

```sh
python3 test_gui.py
python3 dw5934e_voice_gui.py --self-test
```

mock_backend.py is provided for local test launches only.
