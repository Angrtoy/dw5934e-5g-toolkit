# BPI-R4 DW5934e AutoNet

This is an **OpenWrt feed source**, not a firmware image and not a collection of
kernel modules.  It provides the `dw5934e-autonet` package, which manages only
Foxconn DW5934e endpoints `105b:e11d` (eSIM; the known target) and `105b:e11e`
(non-eSIM).

The package uses the supported data-plane split:

```text
matching MHI/WWAN kernel modules -> ModemManager -> netifd proto modemmanager
                                            -> cellular -> firewall wan zone
```

It deliberately does not include a `.ko`, PCI `new_id`, `driver_override`,
bind/unbind, reset, EDL, firmware update, AT command, APN database, or a
Quectel-CM invocation.  In particular, a stock `quectel-CM` is not assumed to
be an appropriate controller for this Foxconn MBIM modem.

## Important status and scope

Only PCI enumeration (`105b:e11d`) is known for the target described by this
delivery.  No BPI-R4/QWRT kernel ABI, actual bound driver, MHI READY state,
control node, SIM, carrier, or APN has been tested.  This source must therefore
be built into, or installed from packages matching, the actual target image.
It makes no claim that a particular QWRT release has the necessary kmods.

The package acts after the kernel has created the MHI/MBIM devices.  It never
tries to make a missing PCI/MHI driver appear.  Its status command explains
which prerequisite is currently missing.

## Customer paths: start on the router, build only when required

Run `onekey-build.sh` on Ubuntu/WSL against the
*same exact* OpenWrt/QWRT source tree used for the router.  It applies the
version-bounded Wi-Fi hotplug patch at build time, builds IPKs through OpenWrt,
and creates an offline directory containing `packages/`, `manifest`, and
`install.sh`.  Copy that directory to the router and run `--check`, then
`--install`.  Set `DW_BOARD_NAME`, `DW_KERNEL_ABI`, and `DW_ARCHITECTURE`
from this collector before building; this prevents a guessed manifest.

Example build-side invocation (the three values must be copied from the target,
not invented from the host):

```sh
DW_BOARD_NAME='bananapi,bpi-r4' \
DW_KERNEL_ABI='EXACT_opkg_status_kernel_Version' \
DW_ARCHITECTURE='EXACT_opkg_status_kernel_Architecture' \
./onekey-build.sh /absolute/path/to/the/exact/openwrt-or-qwrt-tree
```

The script requires an already selected `CONFIG_TARGET_mediatek=y`,
`CONFIG_TARGET_mediatek_filogic=y`, and `bananapi_bpi-r4` profile.  It does not
select a vendor target by name guessing.  It runs `make target/linux/prepare`
and audits the expanded `pci_generic.c`: if `105b:e11d` is absent it stops for
a reviewed official, version-bounded Foxconn SDX72 backport rather than
fabricating a one-line PCI ID patch.  To bake the components into an image,
run the same script first and retain the enabled package symbols in `.config`,
then use the exact tree's normal `make`; an IPK build is not proof of SIM or
carrier service.

After feed/package installation and `make defconfig`, the build path performs a
canonical `make clean` before preparing or compiling the target. This can take
time on the next build, but downloads remain available and no pre-existing IPK
is reused: `bin/` is scanned immediately after clean and any remaining IPK is a
STOP. The subsequent complete build is therefore the provenance boundary for
every bundled IPK in this exact tree/configuration. `build/ipk_closure.py`
parses every control archive, rejects any distinct eligible whole-IPK duplicate
rather than choosing by mtime, enforces target architecture and kmod kernel
dependency, syntax- and structure-audits the patched ModemManager data payload,
and resolves the direct/transitive closure. A closure gap or provenance
ambiguity is a STOP.

## First use: collect only safe target facts

Copy `tools/collect_target_info.sh` to the router and run it as root:

```sh
sh collect_target_info.sh > /tmp/dw5934e-target-info.txt
```

It has no network operation, no AT operation, and performs no writes.  Its
output is deliberately limited to board/kernel ABI, installed package names and
versions, PCI/MHI/WWAN driver/sysfs facts, and device-node names.  Review it
before sharing: it intentionally does not read modem identifiers, SIM data,
cellular configuration, logs, or credentials.

## Add the package to an OpenWrt/QWRT source tree

Use a local feed (no network fetch is necessary):

```sh
echo "src-link dw5934e_autonet /absolute/path/to/BPI-R4_DW5934e_AutoNet_20260830/package" >> feeds.conf.default
./scripts/feeds update dw5934e_autonet
./scripts/feeds install -p dw5934e_autonet dw5934e-autonet
make menuconfig
```

Select `Utilities -> dw5934e-autonet`.  The package declares the following as
**external OpenWrt dependencies**, so the build system/package manager selects
the target's ABI-matched packages rather than this delivery shipping modules:

- `kmod-mhi-bus`, `kmod-mhi-pci-generic`, `kmod-wwan`,
  `kmod-mhi-wwan-ctrl`, `kmod-mhi-wwan-mbim`;
- `modemmanager`, `libmbim`, `mbim-utils`, `libqmi`, and `qmi-utils`.

The selected ModemManager package must have both MBIM and netifd support.  The
runtime checks specifically require `mmcli` and
`/lib/netifd/proto/modemmanager.sh` containing `add_protocol modemmanager`.
For a custom image also explicitly enable the ModemManager MBIM/netifd build
features in the exact package revision used by that image.

For BPI-R4, the final `modemmanager` IPK must be rebuilt after applying this
delivery's `patches/modemmanager/100-bpi-r4-ignore-wireless-net-hotplug.patch`.
It filters MT7996 `phy*-ap*` wireless net events before they reach
`25-modemmanager-net`, avoiding the known Wi-Fi reload loop.  AutoNet checks
the build marker before enabling ModemManager; it never overwrites the
package-owned hotplug file at runtime.  A vendor source whose patch context
does not match is intentionally a build STOP.

The feed package's post-install hook enables and starts ModemManager and
AutoNet on a live target.  In image-builder staging (`IPKG_INSTROOT`), it does
not start services; they start normally on the installed router.  AutoNet then
waits non-destructively for the precise endpoint and a ModemManager modem whose
reported sysfs path contains that endpoint BDF.  It will not select a different
modem merely because it was listed first.

## Configuration

The package installs `/etc/config/dw5934e-autonet`:

```text
config autonet 'main'
        option enabled '1'
        option interface 'cellular'
        option apn ''
        option pincode ''
        option allow_roaming '0'
        option reconnect_interval '60'
```

An empty `apn` is intentional: AutoNet omits `network.<interface>.apn`, leaving
ModemManager to use its automatic carrier/database configuration.  It never
uses a hard-coded operator APN.  Set an APN only when the carrier supplied one:

```sh
uci set dw5934e-autonet.main.apn='carrier-provided-apn'
uci set dw5934e-autonet.main.pincode='SIM-PIN-if-required'
uci commit dw5934e-autonet
/etc/init.d/dw5934e-autonet restart
```

PIN and any optional APN credentials belong to router-local UCI configuration;
do not put them in a ticket, collect output, or this source tree.  The current
minimal configuration intentionally has no username/password fields: add them
only after verifying the exact `proto modemmanager` schema in the pinned
ModemManager package and receiving carrier requirements.

AutoNet creates/manages only the configured `cellular` interface.  If an
interface of that name already exists and does not have
`option autonet_managed '1'`, it stops with `network-section-owned-by-user`
instead of overwriting it.  It adds the interface only to an existing firewall
zone named `wan`, preserving existing zone members.  A missing `wan` zone is a
safe stop, not an excuse to create unknown firewall policy.

### Guarded SIM-slot handling; FCC method intentionally unverified

Recent ModemManager/libmbim releases can report SIM slots and choose a primary
slot.  `auto_sim_slot` defaults to `1`, but AutoNet changes the primary slot
only when all of these are true: ModemManager advertises the slot-selection
command, it explicitly says the active slot is empty, at least one other slot
is explicitly reported, and **exactly one** other reported slot has a SIM
object.  Missing, unrecognised, dual-present, or dual-empty information is a
no-op.  It records only `from-N-to-N`, never SIM information, and makes at
most one attempt per boot.  Set `auto_sim_slot=0` to disable it.

The libqmi FOX FCC operation requires a vendor-specific
`[magic-string,magic-number]` argument.  No official open-source source
confirms a DW5934e/X72 value.  AutoNet therefore **never invokes** that command
and never guesses a parameter; if MM reports an FCC/radio lock it logs
`fcc-method-unverified` and continues the normal MM/netifd diagnostic path.
The installed `fcc_authentication=0` is an explicit documentation/safety
default, not an automatic unlock feature.

## Operation and recovery

```sh
/etc/init.d/dw5934e-autonet status
dw5934e-autonet-status
logread -e dw5934e-autonet
ifstatus cellular
```

The procd daemon waits for MHI/MBIM/ModemManager readiness, detects a missing
SIM from ModemManager state, writes idempotent UCI only after it has selected
the `105b:e11d` modem, joins `wan`, and requests `ifup` when the interface is
not up.  `force_connection=1` and netifd/ModemManager own the actual reconnect
logic; the daemon's retry throttle avoids an `ifup` storm.

To disable it without removing its configuration:

```sh
uci set dw5934e-autonet.main.enabled='0'
uci commit dw5934e-autonet
/etc/init.d/dw5934e-autonet stop
```

To remove the managed network section after `ifdown cellular`, delete only a
section that still says `autonet_managed=1`; do not blindly delete a user-owned
`cellular` section.

## QModem / T99W640 coexistence

QModem can remain installed as a UI/discovery tool, including for a distinct
T99W640 (`105b:e118`).  AutoNet is intentionally narrowed to DW5934e
`105b:e11d/e11e` and does not alter QModem configuration, scans, drivers, or
interfaces.  However,
two management stacks must never control the **same** DW5934e MBIM channel.
Configure QModem not to dial/manage this endpoint before enabling AutoNet; use
one control plane per modem.  QModem's own documentation likewise says it
cannot compensate for a missing matching kernel driver.

## Offline installer scaffold

`offline/install.sh` is deliberately a scaffold rather than a misleading
universal installer.  A release builder places the exact target `.ipk` files in
`offline/packages/` and creates `offline/manifest` from
`offline/manifest.example`.  The manifest binds the bundle to the installed
`kernel` package version (OpenWrt's kernel ABI) and board name, names every
artifact in the complete direct-and-transitive dependency closure, and pins
each SHA-256.

`sh offline/install.sh --check` performs all checks without writes.
`sh offline/install.sh --install` first verifies *all* artifacts and executes
one `opkg --noaction install` over the full set.  Only after that succeeds does
it invoke local `opkg install`; no package is written when the manifest,
kernel ABI, board, checksums, package set, or dependency simulation is missing
or incompatible.  It has no `opkg update`, URL, force flag, or remote access.

## Local tests

From this delivery directory on a POSIX shell host:

```sh
sh tests/test_static.sh
sh tests/test_offline_installer.sh
```

These are source/static and mocked-installer tests only.  They do not load a
kernel module, run ModemManager, write a router, contact a network, or prove
hardware/host compatibility.

## Source basis

The companion deployment guide establishes the relevant boundaries: MHI PCI
ID/configuration must be supplied by a matching kernel; `105b:e11d` is the
DW5934e eSIM variant; `105b:e118` is T99W640; and ModemManager + netifd is the
preferred MBIM route.  Linux upstream commit `bf30a75e6e00` added Foxconn SDX72
support; current upstream `pci_generic.c` associates `105b:e11d` with the
`foxconn_sdx72` configuration (including a 50-second READY timeout and MBIM
channels) and identifies `105b:e11e` as the non-eSIM variant.  Those are
kernel-source facts, not proof that the unknown target image carries that
commit/configuration.

The local QModem source confirms QModem discovers PCIe modems but cannot
replace missing kernel drivers, and its package makes its MHI driver
dependencies optional UI choices.  This delivery therefore keeps MHI kmods
external/precise and does not reuse QModem's dialer for DW5934e.  The supplied
QModem README also requires one management application per AT/control channel;
that is why this source selects only its matched DW5934e ModemManager object
and documents the one-control-plane rule.
