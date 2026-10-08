# Build-time patches

`modemmanager/100-bpi-r4-ignore-wireless-net-hotplug.patch` is intentionally
applied only by `onekey-build.sh`, only to an exact OpenWrt packages feed whose
unpatched `net/modemmanager/files/etc/hotplug.d/net/25-modemmanager-net` has the
expected source context.  The script uses `patch --dry-run` first; a changed
QWRT/vendor handler is a **STOP**, not permission to overwrite a package-owned
file on a router.  The marker is checked by AutoNet post-install before it can
enable ModemManager on a live target.

The patch filters only interfaces that Linux itself labels wireless under
`/sys/class/net/$INTERFACE/{wireless,phy80211}`.  It retains all non-wireless
modem net events.  It is a build input: the final offline set must include the
`modemmanager` IPK built after this patch, rather than a stock package.
