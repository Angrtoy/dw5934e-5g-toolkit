#!/bin/sh
# Read-only, privacy-minimised collection for a BPI-R4/OpenWrt target.
# It deliberately does not call AT/MM/QMI/MBIM tools, access a network, read
# dmesg, read cellular UCI, or print modem/SIM identifiers.

set -u

say() { printf '%s\n' "$*"; }
read_one() { [ -r "$1" ] && cat "$1" 2>/dev/null || printf '%s' '(unavailable)'; }

say '===== board and kernel ABI ====='
say "kernel_release=$(uname -r 2>/dev/null || echo unavailable)"
for f in /tmp/sysinfo/board_name /tmp/sysinfo/model /etc/board.json /etc/openwrt_release; do
	[ -r "$f" ] || continue
	case "$f" in
		/etc/board.json)
			# Board JSON has no modem identity; restrict it to identity-free board keys
			if command -v jsonfilter >/dev/null 2>&1; then
				printf 'board_name='; jsonfilter -i "$f" -e '@.model.id' 2>/dev/null; echo
				printf 'board_model='; jsonfilter -i "$f" -e '@.model.name' 2>/dev/null; echo
			fi
			;;
		*) printf '%s=' "$(basename "$f")"; read_one "$f"; echo ;;
	esac
done
if command -v opkg >/dev/null 2>&1; then
	# Kernel's opkg version is OpenWrt's concrete package/ABI compatibility key.
	opkg status kernel 2>/dev/null | awk -F': ' '/^(Package|Version|Architecture):/ { print "kernel_" tolower($1) "=" $2 }'
else
	say 'kernel_package=opkg-unavailable'
fi

say '===== installed packages (name and version only) ====='
if command -v opkg >/dev/null 2>&1; then
	opkg list-installed 2>/dev/null || say '(package-list-unavailable)'
else
	say '(opkg-unavailable)'
fi

say '===== PCI endpoint and bound driver ====='
for d in /sys/bus/pci/devices/*; do
	[ -r "$d/vendor" ] || continue
	vendor="$(read_one "$d/vendor")"
	device="$(read_one "$d/device")"
	# All PCI facts are useful for ABI/driver diagnosis; no config-space writes.
	say "pci_bdf=$(basename "$d") vendor=$vendor device=$device subsystem_vendor=$(read_one "$d/subsystem_vendor") subsystem_device=$(read_one "$d/subsystem_device")"
	printf 'pci_modalias='; read_one "$d/modalias"; echo
	printf 'pci_driver='; readlink -f "$d/driver" 2>/dev/null || printf '%s' '(unbound)'; echo
done

say '===== loaded MHI/WWAN drivers ====='
if command -v lsmod >/dev/null 2>&1; then
	lsmod | awk 'NR == 1 || $1 ~ /^(mhi|wwan|qrtr)/ { print }'
else
	say '(lsmod-unavailable)'
fi

say '===== MHI and WWAN sysfs paths ====='
for root in /sys/bus/mhi/devices /sys/class/mhi /sys/class/wwan; do
	[ -d "$root" ] || { say "$root=(absent)"; continue; }
	find "$root" -maxdepth 3 -print 2>/dev/null
done

say '===== relevant device node names ====='
found=0
for n in /dev/wwan* /dev/cdc-wdm* /dev/mhi_*; do
	[ -e "$n" ] || continue
	# Name/type only: no contents, modem commands, or unique hardware identifiers.
	printf '%s ' "$n"; [ -c "$n" ] && say 'char-device' || say 'node'
	found=1
done
[ "$found" = 1 ] || say '(none)'
