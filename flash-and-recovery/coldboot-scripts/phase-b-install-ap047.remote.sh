#!/usr/bin/env bash
# Run only through dw5934e-ap047-phase-b.service after a NEW cold boot.
# No QMI/DMS command, PCI unbind/bind, modprobe, or driver transition is present.
set -Eeuo pipefail
umask 077
export LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin

readonly BDF=0000:07:00.0
readonly DEV=/sys/bus/pci/devices/$BDF
readonly MM_MODEL=DP25-42843-47
readonly SOURCE_VERSION=FDE2.F0.0.0.1.2.CU.001
readonly TARGET_VERSION=FDE2.F0.0.0.1.2.CU.001.047
readonly TARGET_GUID=666d7968-3783-513c-8981-49c6fab13626
readonly CAB_NAME=027620d0577139fa66000c660e1e448bb9de8eb1f7bfc2ad37ce3ae9165a0a00-20250109-dell-DW5934E.FDE2.F0.0.0.1.2.047.cab
readonly CAB=$HOME/dw5934e-fw/$CAB_NAME
readonly CAB_SHA256=027620d0577139fa66000c660e1e448bb9de8eb1f7bfc2ad37ce3ae9165a0a00
readonly MAINT_SERVICE=dw5934e-maintenance-radio-off.service
readonly MAINT_MARK=/run/dw5934e-maintenance-radio-off.state
readonly LOGDIR=/var/log/dw5934e-ap047
readonly LOG="$LOGDIR/phase-b-$(date -u +%Y%m%dT%H%M%SZ).log"
INSTALL_STARTED=0

mkdir -p -m 0700 "$LOGDIR"
: >"$LOG"; chmod 0600 "$LOG"
exec > >(tee -a "$LOG") 2>&1
phase() { printf '\n=== PHASE_B_%s UTC=%s ===\n' "$1" "$(date -u --iso-8601=ns)"; }
die() { printf 'PHASE_B_FAIL_CLOSED=%s\n' "$1" >&2; exit 1; }
driver_name() { basename "$(readlink -f "$DEV/driver")"; }
assert_bdf_node() {
  local node=$1 path
  test -c "$node" || die "missing_character_device:$node"
  path=$(udevadm info -q path -n "$node") || die "udevadm_failed:$node"
  case "$path" in *"/$BDF"|*"/$BDF/"*) printf 'NODE_BDF_OK=%s:%s\n' "$node" "$path";; *) die "node_wrong_bdf:$node:$path";; esac
}
abort_before_install() {
  local rc=$?
  trap - EXIT
  if test "$rc" -ne 0 && test "$INSTALL_STARTED" -eq 0; then
    systemctl stop ModemManager.service 2>/dev/null || true
    printf 'PHASE_B_PREINSTALL_ABORT_MM_STOPPED=1\n'
  elif test "$rc" -ne 0; then
    printf 'PHASE_B_POSTINSTALL_ABORT_NO_DRIVER_MM_OR_DMS_ACTION=1\n'
  fi
  printf 'LOG=%s\n' "$LOG"
  exit "$rc"
}
trap abort_before_install EXIT

fwupd_exact_target() {
  python3 - "$1" "$SOURCE_VERSION" "$TARGET_GUID" <<'PY'
import json, sys
path, version, guid = sys.argv[1:]
with open(path, encoding='utf-8') as f: root=json.load(f)
def walk(v):
    if isinstance(v, dict):
        yield v
        for x in v.values(): yield from walk(x)
    elif isinstance(v, list):
        for x in v: yield from walk(x)
matches=[]
for d in walk(root):
    name=str(d.get('Name', d.get('DeviceName', '')))
    rev=str(d.get('Version', d.get('FirmwareVersion', '')))
    guids=d.get('Guid', d.get('GUID', d.get('Guids', d.get('GUIDs', []))))
    if isinstance(guids, str): guids=[guids]
    if name == 'DW5934E' and rev == version and [str(x).lower() for x in guids].count(guid) == 1:
        matches.append((name, rev, guids))
if len(matches) != 1: raise SystemExit('FWUPD_EXACT_TARGET_COUNT=%d' % len(matches))
print('FWUPD_EXACT_TARGET_OK=1')
PY
}
assert_no_current_boot_n78_crash() {
  if journalctl -k -b --no-pager 2>/dev/null | grep -qiE 'n78.*(crash|fatal|error)|((crash|fatal|error).*n78)'; then
    die n78_crash_already_recorded_this_boot
  fi
  printf 'N78_CRASH_ABSENT_CURRENT_BOOT=1\n'
}

phase PRECHECK_COLD_BOOT_NATIVE
test "$(id -u)" -eq 0 || die not_root
test -d "$DEV" || die pci_missing
test "$(cat "$DEV/vendor"):$(cat "$DEV/device"):$(cat "$DEV/subsystem_vendor"):$(cat "$DEV/subsystem_device")" = 0x17cb:0x0309:0x105b:0xe11d || die unexpected_pci_identity
test "$(driver_name)" = mhi-pci-generic || die not_native_mhi_pci_generic
assert_bdf_node /dev/wwan0mbim0
test -f "$CAB" && test ! -L "$CAB" || die cab_missing_or_symlink
test "$(sha256sum "$CAB" | awk '{print $1}')" = "$CAB_SHA256" || die cab_sha256_mismatch
printf 'CAB_SHA256_OK=%s\n' "$CAB_SHA256"
assert_no_current_boot_n78_crash

phase SET_RADIO_OFF_ONCE
systemctl stop ModemManager.service 2>/dev/null || true
radio_off=$(timeout -k 2 8 mbimcli -d /dev/wwan0mbim0 --set-radio-state=off 2>&1) || { printf '%s\n' "$radio_off"; die native_radio_off_failed; }
printf '%s\n' "$radio_off"
printf 'MAINTENANCE_RADIO_OFF_SUCCESS_CURRENT_BOOT=1\n'

phase START_MM_AND_STRICT_ENUMERATION
systemctl unmask ModemManager.service
systemctl start ModemManager.service || die modemmanager_start_failed
deadline=$((SECONDS + 45)); mm_path=''
while test "$SECONDS" -lt "$deadline"; do
  mm_path=$(timeout 5 mmcli -L 2>/dev/null | grep -Eo '/org/freedesktop/ModemManager1/Modem/[0-9]+' | sort -u || true)
  test "$(printf '%s\n' "$mm_path" | sed '/^$/d' | wc -l)" = 1 && break
  sleep 1
done
test -n "$mm_path" || die modemmanager_single_modem_missing
mm_detail=$(timeout 10 mmcli -m "$mm_path" -K 2>&1) || die modemmanager_detail_failed
printf '%s\n' "$mm_detail"
printf '%s\n' "$mm_detail" | grep -Eq "^modem\\.generic\\.model[[:space:]]*:[[:space:]]*$MM_MODEL[[:space:]]*$" || die model_not_exact
printf '%s\n' "$mm_detail" | python3 -c 'import sys; want=sys.argv[1]; got=[x.split(":",1)[1].strip().removesuffix(r"\\n").rstrip() for x in sys.stdin if x.startswith("modem.generic.revision") and ":" in x]; raise SystemExit(0 if got == [want] else 1)' "$SOURCE_VERSION" || die source_version_not_exact
printf 'MM_EXACT_MODEL_AND_SOURCE_VERSION_OK=1\n'
fwjson=$(mktemp /run/dw5934e-ap047-fwupd.XXXXXX)
cleanup_fwjson() { rm -f -- "$fwjson"; abort_before_install; }
trap cleanup_fwjson EXIT
timeout 30 fwupdmgr get-devices --json >"$fwjson" || die fwupd_enumeration_failed
fwupd_exact_target "$fwjson" || die fwupd_exact_guid_source_target_missing
assert_no_current_boot_n78_crash

phase INSTALL_LOCAL_AP047_ONCE
INSTALL_STARTED=1
# Do not put a timeout around a live firmware write and do not recover by changing driver/MM/DMS.
fwupdmgr install --no-reboot "$CAB" || die fwupd_install_failed
printf 'AP047_INSTALL_COMMAND_SUCCEEDED=1\n'

phase POSTINSTALL_READBACK
postjson=$(mktemp /run/dw5934e-ap047-post.XXXXXX)
cleanup_all() { rm -f -- "$fwjson" "$postjson"; abort_before_install; }
trap cleanup_all EXIT
deadline=$((SECONDS + 240))
while test "$SECONDS" -lt "$deadline"; do
  if timeout 15 fwupdmgr get-devices --json >"$postjson" 2>/dev/null; then
    if python3 - "$postjson" "$TARGET_VERSION" "$TARGET_GUID" <<'PY'
import json, sys
root=json.load(open(sys.argv[1], encoding='utf-8')); version, guid=sys.argv[2:]
def walk(v):
 if isinstance(v,dict):
  yield v
  for x in v.values(): yield from walk(x)
 elif isinstance(v,list):
  for x in v: yield from walk(x)
for d in walk(root):
 g=d.get('Guid',d.get('GUID',d.get('Guids',d.get('GUIDs',[]))))
 if isinstance(g,str): g=[g]
 if str(d.get('Name',d.get('DeviceName',''))) == 'DW5934E' and str(d.get('Version',d.get('FirmwareVersion',''))) == version and guid in [str(x).lower() for x in g]: raise SystemExit(0)
raise SystemExit(1)
PY
    then printf 'AP047_READBACK_VERIFIED=1\n'; break; fi
  fi
  sleep 2
done
grep -q '^AP047_READBACK_VERIFIED=1$' "$LOG" || die target_version_not_read_back
printf 'PHASE_B_COMPLETE=1\n'
