#!/usr/bin/env bash
# Installs only the two phase scripts and the manual Phase-B unit.  It does not
# touch a PCI device, change a driver, start ModemManager, or enable/run Phase B.
set -Eeuo pipefail
umask 077
export LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test "$(id -u)" -eq 0
for f in phase-a-stage-rc-local.remote.sh phase-b-install-ap047.remote.sh dw5934e-ap047-phase-b.service; do test -f "$root/$f" && test ! -L "$root/$f"; done
install -o root -g root -m 0700 "$root/phase-a-stage-rc-local.remote.sh" /usr/local/sbin/dw5934e-ap047-phase-a
install -o root -g root -m 0700 "$root/phase-b-install-ap047.remote.sh" /usr/local/sbin/dw5934e-ap047-phase-b
install -o root -g root -m 0644 "$root/dw5934e-ap047-phase-b.service" /etc/systemd/system/dw5934e-ap047-phase-b.service
systemctl daemon-reload
systemctl disable --now dw5934e-ap047-phase-b.service 2>/dev/null || true
printf '%s\n' 'INSTALL_HOST_ARTIFACTS_COMPLETE=1' 'PHASE_A_MANUAL=/usr/local/sbin/dw5934e-ap047-phase-a' 'PHASE_B_MANUAL=systemctl start dw5934e-ap047-phase-b.service'
