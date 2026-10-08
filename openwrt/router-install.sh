#!/bin/sh
# Deliberately no feed/network direct-install path.  This entry point only
# delegates to a complete bundle made by onekey-build.sh in the exact source.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ -r "$HERE/manifest" ] && [ -r "$HERE/install.sh" ] && [ -d "$HERE/packages" ] || { echo 'STOP: expected generated manifest, install.sh and packages/ beside this wrapper' >&2; exit 1; }
exec sh "$HERE/install.sh" "$@"
