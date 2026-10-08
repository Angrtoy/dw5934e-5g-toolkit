#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
AUTO="$ROOT/package/dw5934e-autonet/files/usr/sbin/dw5934e-autonet"
F="$ROOT/tests/fixtures/mmcli-1.24-keyvalue.txt"
[ "$(sh "$AUTO" key-from-facts "$F" modem.generic.device)" = '/sys/devices/platform/11280000.pcie/pci0000:00/0000:00:00.0/0000:01:00.0/mhi0' ]
[ "$(sh "$AUTO" key-from-facts "$F" modem.generic.physdev)" = '/sys/devices/platform/11280000.pcie/pci0000:00/0000:00:00.0/0000:01:00.0' ]
[ "$(sh "$AUTO" key-from-facts "$F" modem.generic.sim-slots.length)" = 2 ]
[ "$(sh "$AUTO" slot-from-facts "$F" 1)" = / ]
[ "$(sh "$AUTO" slot-from-facts "$F" 2)" = '/org/freedesktop/ModemManager1/SIM/1' ]
echo 'PASS: padded ModemManager 1.24 key/value and SIM-slot array parsing'
