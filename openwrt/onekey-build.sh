#!/usr/bin/env bash
# Build-side path B: run on Ubuntu/WSL, never on the router.
set -euo pipefail
TREE=${1:?Usage: ./onekey-build.sh /absolute/path/to/exact-openwrt-or-qwrt-tree}
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[[ -n ${DW_BOARD_NAME:-} && -n ${DW_KERNEL_ABI:-} && -n ${DW_ARCHITECTURE:-} ]] || {
  echo 'STOP: set DW_BOARD_NAME, DW_KERNEL_ABI and DW_ARCHITECTURE from router collect_target_info.sh; do not guess manifest identity' >&2; exit 1;
}
[[ $TREE = /* && -d $TREE && -x $TREE/scripts/feeds ]] || { echo 'STOP: supply an absolute exact OpenWrt/QWRT source tree' >&2; exit 1; }
[[ -d $TREE/target/linux/mediatek ]] || { echo 'STOP: source tree lacks mediatek target' >&2; exit 1; }
[[ -f $TREE/.config ]] || { echo 'STOP: configure the exact BPI-R4 image first; refusing to guess a target/profile' >&2; exit 1; }
grep -qx 'CONFIG_TARGET_mediatek=y' "$TREE/.config" || { echo 'STOP: .config is not mediatek' >&2; exit 1; }
grep -qx 'CONFIG_TARGET_mediatek_filogic=y' "$TREE/.config" || { echo 'STOP: .config is not filogic' >&2; exit 1; }
grep -q 'bananapi_bpi-r4' "$TREE/.config" || { echo 'STOP: .config does not select bananapi_bpi-r4' >&2; exit 1; }
cd "$TREE"
[[ -d "$TREE/feeds/packages/.git" ]] || { echo 'STOP: exact fixed feeds/packages checkout is required; no feeds update/network fetch is performed' >&2; exit 1; }
FEED_REV=$(git -C "$TREE/feeds/packages" rev-parse HEAD)
SRC_REV=$(git -C "$TREE" rev-parse HEAD 2>/dev/null || echo non-git-source)
./scripts/feeds install -p packages modemmanager libmbim libqmi
MM="$TREE/feeds/packages/net/modemmanager/files/etc/hotplug.d/net/25-modemmanager-net"
[[ -f $MM ]] || { echo 'STOP: exact packages feed lacks expected ModemManager hotplug source' >&2; exit 1; }
python3 "$ROOT/build/hotplug_audit.py" "$MM" >/dev/null 2>&1 || {
  (cd "$TREE/feeds/packages" && patch --fuzz=0 -p1 --dry-run < "$ROOT/patches/modemmanager/100-bpi-r4-ignore-wireless-net-hotplug.patch")
  (cd "$TREE/feeds/packages" && patch --fuzz=0 -p1 < "$ROOT/patches/modemmanager/100-bpi-r4-ignore-wireless-net-hotplug.patch")
  python3 "$ROOT/build/hotplug_audit.py" "$MM" || { echo 'STOP: patched hotplug handler failed strict audit' >&2; exit 1; }
}
mkdir -p package/dw5934e-autonet
cp -a "$ROOT/package/dw5934e-autonet/." package/dw5934e-autonet/
./scripts/config --enable PACKAGE_dw5934e-autonet
for s in kmod-mhi-bus kmod-mhi-pci-generic kmod-wwan kmod-mhi-wwan-ctrl kmod-mhi-wwan-mbim modemmanager libmbim mbim-utils libqmi qmi-utils; do ./scripts/config --enable "PACKAGE_$s"; done
./scripts/config --enable MODEMMANAGER_WITH_MBIM --enable MODEMMANAGER_WITH_QMI --enable MODEMMANAGER_WITH_NETIFD --enable MODEMMANAGER_WITH_BUILTIN_PLUGINS
make defconfig
# Canonical clean is the provenance boundary: do not inherit same-architecture
# non-kmod IPKs produced by another tree/configuration.
make clean
mapfile -t PREEXISTING_IPKS < <(find bin -type f -name '*.ipk' -print)
(( ${#PREEXISTING_IPKS[@]} == 0 )) || { echo 'STOP: make clean left preexisting IPKs in bin; refusing mixed-build provenance' >&2; exit 1; }
STAMP=$(mktemp); trap 'rm -f "$STAMP"' EXIT; touch "$STAMP"
make download
# Verify the actual expanded kernel source before building.  No incomplete ID
# line is synthesized: a missing official Foxconn SDX72 backport is a STOP.
make target/linux/prepare V=s
BUILD_DIR=$(make -s val.BUILD_DIR)
[[ -n $BUILD_DIR && $BUILD_DIR != undefined ]] || { echo 'STOP: current config has no BUILD_DIR' >&2; exit 1; }
BUILD_DIR=$(realpath "$BUILD_DIR"); [[ $BUILD_DIR == "$TREE"/build_dir/* ]] || { echo 'STOP: BUILD_DIR escapes current TOPDIR/build_dir' >&2; exit 1; }
KROOT="$BUILD_DIR/linux-mediatek_filogic"
mapfile -t KSRC < <(find "$KROOT" -mindepth 1 -maxdepth 1 -type d -name 'linux-*' -exec test -e '{}/.prepared' ';' -print)
(( ${#KSRC[@]} == 1 )) || { echo 'STOP: current target has not exactly one prepared linux-mediatek_filogic source' >&2; exit 1; }
python3 "$ROOT/build/kernel_audit.py" "${KSRC[0]}/drivers/bus/mhi/host/pci_generic.c"
REQ=(kmod-mhi-bus kmod-mhi-pci-generic kmod-wwan kmod-mhi-wwan-ctrl kmod-mhi-wwan-mbim modemmanager libmbim mbim-utils libqmi qmi-utils dw5934e-autonet)
[[ -f package/feeds/packages/modemmanager/Makefile ]] || { echo 'STOP: verified packages feed modemmanager build target absent' >&2; exit 1; }
make package/feeds/packages/modemmanager/clean V=s
make package/feeds/packages/modemmanager/compile V=s
make package/dw5934e-autonet/clean V=s
make package/dw5934e-autonet/compile V=s
# Canonical full build is required for kernel subpackages and the dependency
# closure.  A failure is not masked; rerun make -j1 V=s for diagnosis.
make -j"${JOBS:-$(nproc)}" || { echo 'STOP: full build failed; rerun make -j1 V=s in this exact tree' >&2; exit 1; }
STAMP_EPOCH=$(stat -c %Y "$STAMP")
mapfile -t CANDIDATES < <(find bin -type f -name '*.ipk' -print)
(( ${#CANDIDATES[@]} )) || { echo 'STOP: no IPK candidates visible in current exact tree' >&2; exit 1; }
OUT="$ROOT/out/$(date +%Y%m%d%H%M%S)"; mkdir -p "$OUT"
ROWS=$(python3 "$ROOT/build/ipk_closure.py" --out "$OUT/packages" --arch "$DW_ARCHITECTURE" --kernel "$DW_KERNEL_ABI" --fresh-after "$STAMP_EPOCH" --required "${REQ[@]}" -- "${CANDIDATES[@]}")
cp "$ROOT/offline/install.sh" "$OUT/install.sh"
chmod +x "$OUT/install.sh"
cat > "$OUT/README.txt" <<'EOF'
Copy this whole directory to the exact target router. Run: sh install.sh --check
Then, only after CHECK succeeds: sh install.sh --install
This bundle was produced only after canonical `make clean` and an empty-bin IPK
assertion in the exact source tree/configuration; no pre-existing IPK was reused.
EOF
printf 'source_revision=%s\npackages_feed_revision=%s\nconfig_sha256=%s\nclean_build=make_clean_then_empty_bin_ipk_assertion\npreexisting_bin_ipks=0\nprovenance=all_bundle_ipks_built_after_clean_in_this_exact_tree_and_config\n' "$SRC_REV" "$FEED_REV" "$(sha256sum .config | awk '{print $1}')" > "$OUT/build-evidence.txt"
{
  echo 'format=dw5934e-autonet-offline-v1'
  printf 'board_name=%s\n' "$DW_BOARD_NAME"
  printf 'kernel_abi=%s\n' "$DW_KERNEL_ABI"
  printf 'architecture=%s\n' "$DW_ARCHITECTURE"
  echo 'builder_schema=dw5934e-builder-v2'
  printf 'verified_modemmanager_sha256=%s\n' "$(printf '%s\n' "$ROWS" | awk -F'|' '$1=="modemmanager"{print $3;exit}')"
  printf '%s\n' "$ROWS" | awk -F'|' 'NF==6 { printf "package|%s|%s|%s\n", $1,$2,$3 }'
} > "$OUT/manifest"
echo "BUILD OUTPUT: $OUT (layout: packages/, manifest, install.sh, README.txt)"
