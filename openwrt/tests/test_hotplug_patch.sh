#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP=${TMPDIR:-/tmp}/dw-hotplug-patch-$$
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/net/modemmanager/files/etc/hotplug.d/net"
cat > "$TMP/net/modemmanager/files/etc/hotplug.d/net/25-modemmanager-net" <<'EOF'
#!/bin/sh

[ "$ACTION" = add ] || exit 0

[ -n "$DEVPATH" ] || exit 0

mmcli --report-kernel-event="action=$ACTION,subsystem=net,name=$INTERFACE"
EOF
(cd "$TMP" && patch --fuzz=0 -p1 --dry-run < "$ROOT/patches/modemmanager/100-bpi-r4-ignore-wireless-net-hotplug.patch")
(cd "$TMP" && patch --fuzz=0 -p1 < "$ROOT/patches/modemmanager/100-bpi-r4-ignore-wireless-net-hotplug.patch")
python "$ROOT/build/hotplug_audit.py" "$TMP/net/modemmanager/files/etc/hotplug.d/net/25-modemmanager-net" >/dev/null
grep -q 'dw5934e-autonet: skip wireless interfaces' "$TMP/net/modemmanager/files/etc/hotplug.d/net/25-modemmanager-net"
grep -q '/sys/class/net/$INTERFACE/wireless' "$TMP/net/modemmanager/files/etc/hotplug.d/net/25-modemmanager-net"
echo 'PASS: version-bounded ModemManager Wi-Fi hotplug patch fixture'
