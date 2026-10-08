#!/usr/bin/env bash
# Run manually on the host only after a cold boot in native low-power state.
# This script intentionally ends on mhi_q.  It MUST NOT bind native MHI again.
set -Eeuo pipefail
umask 077
export LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin

readonly BDF=0000:07:00.0
readonly DEV=/sys/bus/pci/devices/$BDF
readonly ADB_HELPER=$HOME/e11d_restore_transaction_20260728/mhi_adb_exec_resync.py
readonly RC_BACKUP=/data/rc.local.pre-low-power-20260904
readonly RC_SHA256=c21bedf9042f038bdb5017f490df3f666f4811473c85b93b17d562d2b73e0f29
readonly DMS_SHA256=60a8592b6310b03230c45f205ee901add65b16591d16a20001763d120174cc61
readonly DMS_CTL_SHA256=b059e447fe8013e8a4da31cbdba02ceb9172bd821e3aa3766f7d9798d599f6bc
readonly DMS_INIT_SHA256=ba2c14950dbe001a601b9041ba2de01abf03d411f7af628843dd2a0ff11b2ac2
readonly LOGDIR=/var/log/dw5934e-ap047
readonly LOG="$LOGDIR/phase-a-$(date -u +%Y%m%dT%H%M%SZ).log"

mkdir -p -m 0700 "$LOGDIR"
: >"$LOG"; chmod 0600 "$LOG"
exec > >(tee -a "$LOG") 2>&1

die() { printf 'PHASE_A_FAIL_CLOSED=%s\n' "$1" >&2; exit 1; }
phase() { printf '\n=== PHASE_A_%s UTC=%s ===\n' "$1" "$(date -u --iso-8601=ns)"; }
driver_name() { basename "$(readlink -f "$DEV/driver")"; }
assert_bdf_node() {
  local node=$1 path
  test -c "$node" || die "missing_character_device:$node"
  path=$(udevadm info -q path -n "$node") || die "udevadm_failed:$node"
  case "$path" in *"/$BDF"|*"/$BDF/"*) printf 'NODE_BDF_OK=%s:%s\n' "$node" "$path";; *) die "node_wrong_bdf:$node:$path";; esac
}
assert_adb_openable() {
  python3 - /dev/mhi_ADB <<'PY'
import os, sys
fd = os.open(sys.argv[1], os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
os.close(fd)
print('ADB_OPEN_OK=1')
PY
}
assert_next_coldboot_native_contract() {
  # Phase A never performs the unsafe reverse transition.  Before it leaves
  # native MHI, prove that existing persistent maintenance will gate MM.
  test -f /etc/modules-load.d/zz-dw5934e-mbim.conf && test ! -L /etc/modules-load.d/zz-dw5934e-mbim.conf || die native_nextboot_modules_missing
  grep -Fqx mhi_pci_generic /etc/modules-load.d/zz-dw5934e-mbim.conf || die native_nextboot_pci_module_missing
  grep -Fqx mhi_wwan_mbim /etc/modules-load.d/zz-dw5934e-mbim.conf || die native_nextboot_mbim_module_missing
  test -f /etc/modprobe.d/99-dw5934e-e11d-native-mbim.conf && test ! -L /etc/modprobe.d/99-dw5934e-e11d-native-mbim.conf || die vendor_nextboot_block_missing
  grep -Fqx 'blacklist pcie_mhi' /etc/modprobe.d/99-dw5934e-e11d-native-mbim.conf || die vendor_nextboot_not_blacklisted
  test -f /etc/systemd/system/dw5934e-maintenance-radio-off.service && test ! -L /etc/systemd/system/dw5934e-maintenance-radio-off.service || die maintenance_unit_missing
  test -L /etc/systemd/system/multi-user.target.wants/dw5934e-maintenance-radio-off.service || die maintenance_unit_not_enabled
  test "$(readlink /etc/systemd/system/multi-user.target.wants/dw5934e-maintenance-radio-off.service)" = ../dw5934e-maintenance-radio-off.service || die maintenance_enable_link_unexpected
  test -f /etc/systemd/system/ModemManager.service.d/10-dw5934e-maintenance.conf && test ! -L /etc/systemd/system/ModemManager.service.d/10-dw5934e-maintenance.conf || die modemmanager_gate_missing
  grep -Fqx 'Requires=dw5934e-maintenance-radio-off.service' /etc/systemd/system/ModemManager.service.d/10-dw5934e-maintenance.conf || die modemmanager_requires_gate_missing
  grep -Fqx 'After=dw5934e-maintenance-radio-off.service' /etc/systemd/system/ModemManager.service.d/10-dw5934e-maintenance.conf || die modemmanager_after_gate_missing
  printf '%s\n' 'NEXT_COLD_BOOT_NATIVE_MAINTENANCE_CONTRACT_OK=1'
}
assert_low_power() {
  local result
  result=$(timeout 20 qmicli -d /dev/mhi_QMI0 --device-open-qmi --dms-get-operating-mode 2>&1) || die dms_mode_read_failed
  printf '%s\n' "$result"
  printf '%s\n' "$result" | grep -Eq "Mode: 'low-power'" || die dms_mode_not_low_power
  printf '%s\n' 'VENDOR_DMS_LOW_POWER_VERIFIED=1'
}

phase PRECHECK_NATIVE
test "$(id -u)" -eq 0 || die not_root
test -d "$DEV" || die pci_missing
test "$(cat "$DEV/vendor"):$(cat "$DEV/device"):$(cat "$DEV/subsystem_vendor"):$(cat "$DEV/subsystem_device")" = 0x17cb:0x0309:0x105b:0xe11d || die unexpected_pci_identity
test "$(driver_name)" = mhi-pci-generic || die not_native_mhi_pci_generic
assert_bdf_node /dev/wwan0mbim0
test -f "$ADB_HELPER" && test ! -L "$ADB_HELPER" || die adb_helper_missing_or_symlink
systemctl stop ModemManager.service 2>/dev/null || true
test "$(systemctl is-active ModemManager.service 2>/dev/null || true)" != active || die modemmanager_still_active
assert_next_coldboot_native_contract

phase NATIVE_TO_VENDOR_ONCE
# The direction below is the only live driver transition in this stage.
printf '%s' "$BDF" > /sys/bus/pci/drivers/mhi-pci-generic/unbind
modprobe -r mhi_wwan_mbim 2>/dev/null || true
modprobe -r mhi_pci_generic
modprobe pcie_mhi
sleep 1
if test ! -L "$DEV/driver"; then printf '%s' "$BDF" > /sys/bus/pci/drivers/mhi_q/bind; fi
test "$(driver_name)" = mhi_q || die vendor_bind_failed
deadline=$((SECONDS + 45))
while { test ! -c /dev/mhi_ADB || test ! -c /dev/mhi_QMI0; } && test "$SECONDS" -lt "$deadline"; do sleep 1; done
assert_bdf_node /dev/mhi_ADB
assert_bdf_node /dev/mhi_QMI0
assert_adb_openable || die adb_not_openable
assert_low_power

phase MODULE_RESTORE_RC_LOCAL
# The escaped substitutions below belong to the module-side shell, while the
# three fixed file hashes and backup path are expanded on the host.
module_cmd=$(cat <<EOF
set -eu
for item in \
  '$DMS_SHA256  /data/dw_dms' \
  '$DMS_CTL_SHA256  /data/dw_dms_ctl' \
  '$DMS_INIT_SHA256  /etc/init.d/dw_dms'; do
  printf '%s\n' "\$item" | sha256sum -c -
done
test -f '$RC_BACKUP' && test ! -L '$RC_BACKUP'
test "\$(sha256sum '$RC_BACKUP' | awk '{print \$1}')" = '$RC_SHA256'
cp -p -- '$RC_BACKUP' /etc/rc.local
sync
test -f /etc/rc.local && test ! -L /etc/rc.local
test "\$(sha256sum /etc/rc.local | awk '{print \$1}')" = '$RC_SHA256'
for item in \
  '$DMS_SHA256  /data/dw_dms' \
  '$DMS_CTL_SHA256  /data/dw_dms_ctl' \
  '$DMS_INIT_SHA256  /etc/init.d/dw_dms'; do
  printf '%s\n' "\$item" | sha256sum -c -
done
printf 'MODULE_BUSINESS_SENTINELS_OK=1\n'
printf 'MODULE_RC_LOCAL_SHA256=%s\n' "\$(sha256sum /etc/rc.local | awk '{print \$1}')"
printf 'MODULE_RC_LOCAL_RESTORED_NEXT_COLD_BOOT_ONLY=1\n'
EOF
)
adb_output=$(timeout 120 /usr/bin/python3 "$ADB_HELPER" --device /dev/mhi_ADB --timeout 90 "$module_cmd" 2>&1) || { printf '%s\n' "$adb_output"; die module_restore_failed; }
printf '%s\n' "$adb_output"
printf '%s\n' "$adb_output" | grep -Fx 'MODULE_BUSINESS_SENTINELS_OK=1' >/dev/null || die business_sentinels_unconfirmed
printf '%s\n' "$adb_output" | grep -Fx "MODULE_RC_LOCAL_SHA256=$RC_SHA256" >/dev/null || die final_rc_local_hash_unconfirmed
printf '%s\n' "$adb_output" | grep -Fx 'MODULE_RC_LOCAL_RESTORED_NEXT_COLD_BOOT_ONLY=1' >/dev/null || die next_coldboot_contract_unconfirmed

phase COMPLETE
printf 'PHASE_A_COMPLETE=1\n'
printf 'PHASE_A_DRIVER_LEFT=mhi_q\n'
printf 'PHASE_A_NEXT_ACTION=PERFORM_A_REAL_COLD_BOOT__DO_NOT_RUNTIME_SWITCH_TO_NATIVE\n'
printf 'LOG=%s\n' "$LOG"
