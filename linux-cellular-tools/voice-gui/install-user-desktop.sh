#!/bin/sh
# Per-user, no-root desktop-entry template. It never writes system directories.
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
src="$base/dw5934e-voice-gui.desktop"
[ -f "$src" ] && [ ! -L "$src" ] || { echo "REFUSED: desktop file missing/symlink" >&2; exit 64; }
dest="$HOME/.local/share/applications/dw5934e-voice-gui.desktop"
[ ! -e "$dest" ] || { echo "REFUSED: desktop destination exists; no overwrite" >&2; exit 65; }
umask 022
mkdir -p -- "$(dirname -- "$dest")"
install -m 0644 -- "$src" "$dest"
echo "INSTALLED: $dest"
