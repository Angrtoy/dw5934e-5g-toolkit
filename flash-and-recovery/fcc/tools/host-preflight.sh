#!/usr/bin/env bash
set -Eeuo pipefail
uname -srmo;command -v adb >/dev/null&&adb version||true;echo "Read-only: no module action."
