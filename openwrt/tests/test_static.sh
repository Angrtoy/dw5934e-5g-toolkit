#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
AUTO="$ROOT/package/dw5934e-autonet/files/usr/sbin/dw5934e-autonet"
INIT="$ROOT/package/dw5934e-autonet/files/etc/init.d/dw5934e-autonet"
COLLECT="$ROOT/tools/collect_target_info.sh"
INSTALL="$ROOT/offline/install.sh"
BUILD="$ROOT/onekey-build.sh"
ROUTER="$ROOT/router-install.sh"

for f in "$AUTO" "$INIT" "$COLLECT" "$INSTALL" "$ROUTER"; do sh -n "$f"; done
bash -n "$BUILD"

grep -q '105b:e11d' "$ROOT/README.md"
grep -q '+kmod-mhi-pci-generic' "$ROOT/package/dw5934e-autonet/Makefile"
grep -q '+modemmanager' "$ROOT/package/dw5934e-autonet/Makefile"
grep -q 'add_protocol modemmanager' "$AUTO"
grep -q 'auto_sim_slot' "$AUTO"
grep -q 'fcc-method-unverified' "$AUTO"
if grep -q -- '--fox-set-fcc-authentication' "$AUTO"; then
	echo 'unverified FOX FCC command must not be invoked' >&2; exit 1
fi
grep -q 'opkg --noaction install' "$INSTALL"
grep -q 'architecture mismatch' "$INSTALL"
grep -q '105b:e11d/e11e' "$INSTALL"
grep -q 'target-coldplug-reported' "$AUTO"
grep -q 'modem.generic.physdev' "$AUTO"
grep -q '\[ -d "\$HERE/packages" \]' "$ROUTER"
grep -q 'exec sh "\$HERE/install.sh" "\$@"' "$ROUTER"
grep -q 'find bin -type f -name' "$BUILD"
grep -q '^make clean$' "$BUILD"
grep -q 'make clean left preexisting IPKs in bin' "$BUILD"
grep -q 'preexisting_bin_ipks=0' "$BUILD"
clean_line=$(grep -n '^make clean$' "$BUILD" | cut -d: -f1)
prepare_line=$(grep -n '^make target/linux/prepare V=s$' "$BUILD" | cut -d: -f1)
[ "$clean_line" -lt "$prepare_line" ]
grep -q -- '--fresh-after "$STAMP_EPOCH"' "$BUILD"
if grep -q 'find bin .* -newer "\$STAMP"' "$BUILD"; then
	echo 'closure candidate discovery must include all bin IPKs, not only fresh files' >&2; exit 1
fi
grep -q 'dw5934e-autonet: skip wireless interfaces' "$ROOT/patches/modemmanager/100-bpi-r4-ignore-wireless-net-hotplug.patch"
grep -q '/sys/class/net/$INTERFACE/wireless' "$ROOT/patches/modemmanager/100-bpi-r4-ignore-wireless-net-hotplug.patch"

# The delivered default must never contain an operator-specific APN or a PIN.
grep -q "option apn ''" "$ROOT/package/dw5934e-autonet/files/etc/config/dw5934e-autonet"
grep -q "option pincode ''" "$ROOT/package/dw5934e-autonet/files/etc/config/dw5934e-autonet"

# Safety contract: no state-changing PCI override, reset/EDL, carrier-specific
# dialer, remote fetch, or forced dependency escape in automation/installer.
if grep -Ein '(new_id|driver_override|/bind|/unbind|trigger_edl|soc_reset|quectel-[Cc][Mm]|--force|https?://|wget|curl)' "$AUTO" "$COLLECT" "$INSTALL"; then
	echo 'forbidden unsafe operation found' >&2
	exit 1
fi

echo 'PASS: shell syntax and static safety/dependency assertions'
