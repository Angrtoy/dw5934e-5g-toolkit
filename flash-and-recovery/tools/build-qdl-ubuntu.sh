#!/usr/bin/env bash
# Default: offline dependency check plus build from the vendored, pinned source.
# Network access is used only with --install-deps-online.
set -Eeuo pipefail
R=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd);S="$R/tools/qdl-v2.7.1";install=0
[ "$#" -le 1 ] || { echo "Usage: $0 [--install-deps-online]" >&2;exit 64;}
[ "$#" = 0 ] || { [ "$1" = --install-deps-online ] || exit 64;install=1;}
[ "$(git -C "$S" describe --exact-match --tags HEAD)" = v2.7.1 ]||{ echo "qdl pin failed" >&2;exit 2;}
if ((install));then sudo apt-get update;sudo apt-get install -y libxml2-dev libusb-1.0-0-dev libzip-dev meson ninja-build help2man;fi
for x in meson ninja pkg-config;do command -v "$x" >/dev/null||{ echo "Missing $x. Stop: preinstall dependencies, use approved internal APT cache/mirror, or explicitly rerun --install-deps-online." >&2;exit 1;};done
pkg-config --exists libxml-2.0 libusb-1.0 libzip||{ echo "Missing development libraries. Stop; use preinstalled packages/internal mirror or explicit online mode." >&2;exit 1;}
meson setup "$S/build" "$S" --wipe;meson compile -C "$S/build"
