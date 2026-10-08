#!/usr/bin/env bash
# Valid only before fwupdmgr install has started.  It intentionally restores no
# module content and sends no DMS/QMI request.
set -Eeuo pipefail
export LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin
test "$(id -u)" -eq 0
systemctl stop ModemManager.service 2>/dev/null || true
systemctl disable --now dw5934e-ap047-phase-b.service 2>/dev/null || true
rm -f -- /etc/systemd/system/dw5934e-ap047-phase-b.service /usr/local/sbin/dw5934e-ap047-phase-a /usr/local/sbin/dw5934e-ap047-phase-b
systemctl daemon-reload
printf '%s\n' 'ROLLBACK_BEFORE_INSTALL_COMPLETE=1' 'NOTE=Existing_native_maintenance_configuration_is_intentionally_unchanged'
