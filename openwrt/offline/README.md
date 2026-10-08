# Offline bundle procedure

This directory intentionally ships **no** `.ipk` and no live `manifest`: there
is no known target ABI.  A release engineer, after building the exact target
image/feed, copies the complete direct-and-transitive package dependency
closure (including AutoNet) into `packages/`, calculates their SHA-256, and
makes a real `manifest` by replacing every placeholder in `manifest.example`.

Use the `Version` and `Architecture` fields from `opkg status kernel` exactly
as `kernel_abi` and `architecture`, not merely `uname -r`.  Use the exact
contents of `/tmp/sysinfo/board_name` as `board_name`.  Keep filenames simple
basenames; the installer rejects paths and duplicate labels.  Before any solver
or installation operation it additionally verifies a local `105b:e11d/e11e`
PCI endpoint; `105b:e118` alone is rejected.

The installer does not contact feeds or the Internet.  It checks the whole
bundle and requests a complete `opkg --noaction install` before any local IPK
is written.  Do not replace that check with `--force-depends`.

```sh
sh install.sh --check       # zero writes
sh install.sh --install     # one non-interactive local installation after check
```
