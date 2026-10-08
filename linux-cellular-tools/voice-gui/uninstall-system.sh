#!/bin/sh
# Template only. Refuses removal when owner/mode differs from install-system.sh.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "REFUSED: run as root" >&2; exit 77; }
check() {
  [ -f "$1" ] && [ ! -L "$1" ] || { echo "REFUSED: missing/nonregular: $1" >&2; exit 65; }
  [ "$(stat -c '%U:%G %a' -- "$1")" = "root:root $2" ] || { echo "REFUSED: unexpected owner/mode: $1" >&2; exit 65; }
}
check /usr/local/libexec/dw5934e-voice-control 755
check /usr/local/lib/dw5934e-voice-gui/dw5934e_voice_gui.py 755
check /usr/share/polkit-1/actions/org.example.dw5934e.voice-control.policy 644
rm -- /usr/local/libexec/dw5934e-voice-control /usr/local/lib/dw5934e-voice-gui/dw5934e_voice_gui.py /usr/share/polkit-1/actions/org.example.dw5934e.voice-control.policy
rmdir -- /usr/local/lib/dw5934e-voice-gui 2>/dev/null || echo "NOTE: GUI directory retained because nonempty."
echo "REMOVED system files only; user desktop entries were not touched."
