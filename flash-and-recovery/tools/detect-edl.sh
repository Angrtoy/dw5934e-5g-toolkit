#!/usr/bin/env bash
set -Eeuo pipefail
command -v lsusb >/dev/null||{ echo "install usbutils" >&2;exit 1;}
lsusb;command -v lspci >/dev/null&&lspci -nn||true
echo "05c6:9008 USB qdl EDL: $(lsusb -d 05c6:9008|wc -l)"
echo "0489:e131 Dell composite EDL, not USB9008: $(lsusb -d 0489:e131|wc -l)"
for i in e11d e11e e118;do echo "105b:$i PCI/MHI (not USB9008): $(for d in /sys/bus/pci/devices/*;do [ -r "$d/vendor" ]&&[ "$(cat "$d/vendor")" = 0x105b ]&&[ "$(cat "$d/device")" = "0x$i" ]&&echo x;done|wc -l)";done
echo "Read-only; all identities are non-interchangeable."
