#!/bin/sh
# Template only; it is intentionally not run by this repository.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "REFUSED: run as root" >&2; exit 77; }
[ "$#" -eq 1 ] || { echo "Usage: $0 /absolute/path/to/dw5934e-voice-control" >&2; exit 64; }
src=$1
case "$src" in /*) ;; *) echo "REFUSED: backend source must be absolute" >&2; exit 64;; esac
[ -f "$src" ] && [ -x "$src" ] && [ ! -L "$src" ] || { echo "REFUSED: source is not an executable regular file" >&2; exit 64; }
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
for file in "$base/dw5934e_voice_gui.py" "$base/org.example.dw5934e.voice-control.policy"; do
  [ -f "$file" ] && [ ! -L "$file" ] || { echo "REFUSED: required template missing/symlink: $file" >&2; exit 64; }
done
for directory in /usr/local/libexec /usr/local/lib /usr/share/polkit-1/actions; do
  [ -d "$directory" ] || { echo "REFUSED: directory missing: $directory" >&2; exit 64; }
done
for target in /usr/local/libexec/dw5934e-voice-control /usr/local/lib/dw5934e-voice-gui /usr/share/polkit-1/actions/org.example.dw5934e.voice-control.policy; do
  [ ! -e "$target" ] || { echo "REFUSED: target already exists; no overwrite: $target" >&2; exit 65; }
done
install -d -o root -g root -m 0755 /usr/local/lib/dw5934e-voice-gui
install -o root -g root -m 0755 -- "$src" /usr/local/libexec/dw5934e-voice-control
install -o root -g root -m 0755 -- "$base/dw5934e_voice_gui.py" /usr/local/lib/dw5934e-voice-gui/dw5934e_voice_gui.py
install -o root -g root -m 0644 -- "$base/org.example.dw5934e.voice-control.policy" /usr/share/polkit-1/actions/org.example.dw5934e.voice-control.policy
echo "INSTALLED: root-owned system files. Use install-user-desktop.sh separately as the desktop user."
