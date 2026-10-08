#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP=${TMPDIR:-/tmp}/dw5934e-autonet-test-$$
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/offline/packages" "$TMP/bin" "$TMP/sysinfo" "$TMP/sys/bus/pci/devices/0000:01:00.0"
cp "$ROOT/offline/install.sh" "$TMP/offline/install.sh"
cp "$ROOT/offline/ipk-meta.sh" "$TMP/offline/ipk-meta.sh"
chmod +x "$TMP/offline/install.sh" "$TMP/offline/ipk-meta.sh"
printf 'test-board\n' > "$TMP/sysinfo/board_name"
printf '0x105b\n' > "$TMP/sys/bus/pci/devices/0000:01:00.0/vendor"
printf '0xe11d\n' > "$TMP/sys/bus/pci/devices/0000:01:00.0/device"
for pkg in kmod-mhi-bus kmod-mhi-pci-generic kmod-wwan kmod-mhi-wwan-ctrl kmod-mhi-wwan-mbim libmbim mbim-utils libqmi qmi-utils modemmanager dw5934e-autonet; do
	printf 'minimal-ipk-fixture:%s\n' "$pkg" > "$TMP/offline/packages/$pkg.ipk"
	printf 'Package: %s\nVersion: 1\nArchitecture: aarch64\n' "$pkg" > "$TMP/offline/packages/$pkg.ipk.control"
	case "$pkg" in kmod-*) printf 'Depends: kernel (= 6.6.1~testabi)\n' >> "$TMP/offline/packages/$pkg.ipk.control";; esac
	if [ "$pkg" = modemmanager ]; then printf 'dw5934e-autonet: skip wireless interfaces\n' > "$TMP/offline/packages/$pkg.ipk.data"; else printf 'payload\n' > "$TMP/offline/packages/$pkg.ipk.data"; fi
done
{
	echo 'format=dw5934e-autonet-offline-v1'
	echo 'board_name=test-board'
	echo 'kernel_abi=6.6.1~testabi'
	echo 'architecture=aarch64'
	echo 'builder_schema=dw5934e-builder-v2'
	printf 'verified_modemmanager_sha256=%s\n' "$(sha256sum "$TMP/offline/packages/modemmanager.ipk" | awk '{print $1}')"
	for f in "$TMP"/offline/packages/*.ipk; do
		base=$(basename "$f")
		name=${base%.ipk}
		printf 'package|%s|%s|%s\n' "$name" "$base" "$(sha256sum "$f" | awk '{print $1}')"
	done
} > "$TMP/offline/manifest"
cp "$TMP/offline/manifest" "$TMP/offline/manifest.good"
cat > "$TMP/bin/opkg" <<'EOF_OPKG'
#!/bin/sh
if [ "$1" = status ] && [ "$2" = kernel ]; then
  printf 'Package: kernel\nVersion: 6.6.1~testabi\nArchitecture: aarch64\n\n'
  exit 0
fi
if [ "$1" = --noaction ]; then echo 'mock noaction'; exit 0; fi
if [ "$1" = install ]; then echo 'mock install'; exit 0; fi
exit 1
EOF_OPKG
chmod +x "$TMP/bin/opkg"
cat > "$TMP/bin/ar" <<'EOF_AR'
#!/bin/sh
case "$1" in
 t) printf 'debian-binary\ncontrol.tar.gz\ndata.tar.gz\n';;
 p) case "$3" in control.tar.gz) cat "$2.control";; data.tar.gz) cat "$2.data";; esac;;
 *) exit 1;;
esac
EOF_AR
chmod +x "$TMP/bin/ar"
cat > "$TMP/bin/tar" <<'EOF_TAR'
#!/bin/sh
# The fixture ar helper emits the selected control/data member directly.
cat
EOF_TAR
chmod +x "$TMP/bin/tar"
cat > "$TMP/bin/id" <<'EOF_ID'
#!/bin/sh
[ "$1" = -u ] && { echo 0; exit 0; }
exit 1
EOF_ID
chmod +x "$TMP/bin/id"

PATH="$TMP/bin:$PATH" TMPDIR="$TMP" SYSINFO_DIR="$TMP/sysinfo" SYSFS_ROOT="$TMP/sys" /bin/sh "$TMP/offline/install.sh" --check > "$TMP/out"
grep -q 'check complete: no writes requested' "$TMP/out"

# A kernel mismatch must stop before it can reach either simulated install form.
sed 's/6\.6\.1~testabi/not-the-kernel/' "$TMP/offline/manifest" > "$TMP/offline/bad"
mv "$TMP/offline/bad" "$TMP/offline/manifest"
if PATH="$TMP/bin:$PATH" TMPDIR="$TMP" SYSINFO_DIR="$TMP/sysinfo" SYSFS_ROOT="$TMP/sys" /bin/sh "$TMP/offline/install.sh" --install > "$TMP/badout" 2>&1; then
	echo 'installer unexpectedly accepted ABI mismatch' >&2; exit 1
fi
grep -q 'kernel ABI mismatch' "$TMP/badout"
! grep -q 'mock install' "$TMP/badout"

# Architecture mismatch stops before the solver and installer too.
sed 's/architecture=aarch64/architecture=wrongarch/' "$TMP/offline/manifest.good" > "$TMP/offline/manifest"
if PATH="$TMP/bin:$PATH" TMPDIR="$TMP" SYSINFO_DIR="$TMP/sysinfo" SYSFS_ROOT="$TMP/sys" /bin/sh "$TMP/offline/install.sh" --install > "$TMP/archout" 2>&1; then
	echo 'installer unexpectedly accepted architecture mismatch' >&2; exit 1
fi
grep -q 'architecture mismatch' "$TMP/archout"
! grep -q 'mock noaction\|mock install' "$TMP/archout"

# T99W640 e118 by itself is deliberately not a DW5934e acceptance condition.
cp "$TMP/offline/manifest.good" "$TMP/offline/manifest"
printf '0xe118\n' > "$TMP/sys/bus/pci/devices/0000:01:00.0/device"
if PATH="$TMP/bin:$PATH" TMPDIR="$TMP" SYSINFO_DIR="$TMP/sysinfo" SYSFS_ROOT="$TMP/sys" /bin/sh "$TMP/offline/install.sh" --install > "$TMP/pciout" 2>&1; then
	echo 'installer unexpectedly accepted non-DW PCI device' >&2; exit 1
fi
grep -q 'no DW5934e PCI endpoint' "$TMP/pciout"
! grep -q 'mock noaction\|mock install' "$TMP/pciout"

# Structural duplicates are rejected before the opkg solver.
printf '0xe11d\n' > "$TMP/sys/bus/pci/devices/0000:01:00.0/device"
cat "$TMP/offline/manifest.good" "$TMP/offline/manifest.good" > "$TMP/offline/manifest"
if PATH="$TMP/bin:$PATH" TMPDIR="$TMP" SYSINFO_DIR="$TMP/sysinfo" SYSFS_ROOT="$TMP/sys" /bin/sh "$TMP/offline/install.sh" --install > "$TMP/dupout" 2>&1; then exit 1; fi
grep -q 'duplicate manifest header' "$TMP/dupout"; ! grep -q 'mock noaction\|mock install' "$TMP/dupout"
echo 'PASS: offline installer accepts exact mocked bundle and rejects ABI/architecture/PCI/duplicate-manifest mismatch before install'
