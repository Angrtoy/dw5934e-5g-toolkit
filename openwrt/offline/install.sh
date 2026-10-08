#!/bin/sh
# Offline-only installer.  A missing/inexact manifest is a successful safety stop.

set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
MANIFEST="$HERE/manifest"
PACKAGES="$HERE/packages"
MODE=${1:---check}
SYSINFO_DIR=${SYSINFO_DIR:-/tmp/sysinfo}
SYSFS_ROOT=${SYSFS_ROOT:-/sys}

die() { echo "STOP: $*" >&2; exit 1; }
note() { echo "CHECK: $*"; }

[ "$(id -u 2>/dev/null || echo 1)" = 0 ] || die 'must run as root on the OpenWrt target'
case "$MODE" in --check|--install) ;; *) die 'usage: install.sh [--check|--install]' ;; esac
[ -r "$MANIFEST" ] || die 'offline/manifest is absent; build an exact bundle from manifest.example first'
[ -d "$PACKAGES" ] || die 'packages directory is absent'
command -v opkg >/dev/null 2>&1 || die 'opkg is absent'
command -v sha256sum >/dev/null 2>&1 || die 'sha256sum is absent'

format=''
expected_board=''
expected_kernel=''
expected_architecture=''
ipks=''
names=''
seen_lines=0
seen_packages='|'
seen_files='|'
seen_headers='|'

while IFS= read -r line || [ -n "$line" ]; do
	case "$line" in ''|'#'*) continue;; esac
	case "$line" in
		package\|*)
			IFS='|' read -r record pkg filename checksum extra <<EOF_RECORD
$line
EOF_RECORD
			[ "$record" = package ] && [ -n "$pkg" ] && [ -n "$filename" ] && [ -n "$checksum" ] && [ -z "${extra:-}" ] || die 'malformed package record (package|name|file.ipk|sha256)'
			case "$filename" in ''|.*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+~-]*) die "unsafe package filename: $filename";; esac
				case "$pkg" in ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+~-]*) die "unsafe package name: $pkg";; esac
				case "$seen_packages" in *"|$pkg|"*) die "duplicate manifest package label: $pkg";; esac
				case "$seen_files" in *"|$filename|"*) die "duplicate manifest filename: $filename";; esac
				seen_packages="${seen_packages}${pkg}|"; seen_files="${seen_files}${filename}|"
			[ "${#checksum}" = 64 ] || die "invalid SHA-256 length for $filename"
			case "$checksum" in *[!0123456789abcdef]*) die "invalid SHA-256 for $filename";; esac
			ipks="$ipks $PACKAGES/$filename"
			names="$names $pkg"
			seen_lines=$((seen_lines + 1))
			;;
		*=*)
				key=${line%%=*}
				value=${line#*=}
				case "$seen_headers" in *"|$key|"*) die "duplicate manifest header: $key";; esac
				seen_headers="${seen_headers}${key}|"
				case "$key" in
				format) format=$value ;;
				board_name) expected_board=$value ;;
				kernel_abi) expected_kernel=$value ;;
					architecture) expected_architecture=$value ;;
					builder_schema) builder_schema=$value ;;
					verified_modemmanager_sha256) verified_mm_sha=$value ;;
				*) die "unknown manifest key: $key";;
			esac
			;;
		*) die "malformed manifest line: $line";;
	esac
done < "$MANIFEST"

[ "$format" = 'dw5934e-autonet-offline-v1' ] || die 'wrong or placeholder manifest format'
case "$expected_board$expected_kernel$expected_architecture${builder_schema:-}${verified_mm_sha:-}" in *REPLACE*|'') die 'manifest has unfilled required header placeholder';; esac
[ "$seen_lines" -gt 0 ] || die 'manifest names no packages'
mm_row_sha=$(awk -F'|' '$1=="package" && $2=="modemmanager" {print $4; exit}' "$MANIFEST")
[ -n "$mm_row_sha" ] || die 'manifest lacks modemmanager package row'
[ "$mm_row_sha" = "$verified_mm_sha" ] || die 'verified_modemmanager_sha256 does not bind modemmanager row'

actual_board="$(cat "$SYSINFO_DIR/board_name" 2>/dev/null || true)"
[ -n "$actual_board" ] || die "$SYSINFO_DIR/board_name unavailable; cannot prove board"
[ "$actual_board" = "$expected_board" ] || die "board mismatch (expected $expected_board; got $actual_board)"
actual_kernel="$(opkg status kernel 2>/dev/null | awk -F': ' '$1 == "Version" { print $2; exit }')"
[ -n "$actual_kernel" ] || die 'installed kernel package version unavailable'
[ "$actual_kernel" = "$expected_kernel" ] || die "kernel ABI mismatch (expected $expected_kernel; got $actual_kernel)"
actual_architecture="$(opkg status kernel 2>/dev/null | awk -F': ' '$1 == "Architecture" { print $2; exit }')"
[ -n "$actual_architecture" ] || die 'installed kernel package architecture unavailable'
[ "$actual_architecture" = "$expected_architecture" ] || die "architecture mismatch (expected $expected_architecture; got $actual_architecture)"

pci_ok=0
for p in "$SYSFS_ROOT"/bus/pci/devices/*; do
	[ "$(cat "$p/vendor" 2>/dev/null)" = 0x105b ] || continue
	case "$(cat "$p/device" 2>/dev/null)" in 0xe11d|0xe11e) pci_ok=1;; esac
done
[ "$pci_ok" = 1 ] || die 'no DW5934e PCI endpoint 105b:e11d/e11e is enumerated (e118 alone is rejected)'

required='kmod-mhi-bus kmod-mhi-pci-generic kmod-wwan kmod-mhi-wwan-ctrl kmod-mhi-wwan-mbim libmbim mbim-utils libqmi qmi-utils modemmanager dw5934e-autonet'
for required_name in $required; do
	case " $names " in *" $required_name "*) ;; *) die "bundle lacks required package: $required_name";; esac
done

for ipk in $ipks; do
	[ -f "$ipk" ] || die "missing artifact: $(basename "$ipk")"
		base=$(basename "$ipk")
		expected=$(awk -F'|' -v f="$base" '$1 == "package" && $3 == f { print $4; exit }' "$MANIFEST")
	actual=$(sha256sum "$ipk" | awk '{print $1}')
	[ "$actual" = "$expected" ] || die "SHA-256 mismatch: $base"
	done

note 'board, exact kernel package ABI, required package set, and all checksums match'
# A complete solver pass is intentionally performed before any opkg write.
if ! opkg --noaction install $ipks; then
	die 'opkg dependency/ABI simulation failed; no package has been written'
fi
note 'opkg --noaction accepted the complete local set'
[ "$MODE" = --check ] && { note 'check complete: no writes requested'; exit 0; }

opkg install $ipks || die 'opkg install failed after preflight; inspect opkg output before retrying'
note 'local bundle installed; package post-install enables ModemManager and AutoNet'
