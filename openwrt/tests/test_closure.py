#!/usr/bin/env python3
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from make_ipk_fixtures import VALID_MODEMMANAGER_HOTPLUG, ipk
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'build'))
from hotplug_audit import shell_syntax_ok

root = os.path.dirname(os.path.dirname(__file__))
helper = os.path.join(root, 'build', 'ipk_closure.py')
names = ('kmod-mhi-bus kmod-mhi-pci-generic kmod-wwan kmod-mhi-wwan-ctrl '
         'kmod-mhi-wwan-mbim libmbim mbim-utils libqmi qmi-utils modemmanager '
         'dw5934e-autonet').split()

def run(modemmanager_body=VALID_MODEMMANAGER_HOTPLUG):
    # Every invocation writes one complete, otherwise-valid candidate set.
    with tempfile.TemporaryDirectory() as directory:
        paths = []
        for name in names:
            path = os.path.join(directory, name + '.ipk')
            ipk(path, name,
                depends='kernel (= 6.6.1~x)' if name.startswith('kmod-') else '',
                body=modemmanager_body if name == 'modemmanager' else None)
            paths.append(path)
        return subprocess.run(
            [sys.executable, helper, '--out', os.path.join(directory, 'out'),
             '--arch', 'aarch64', '--kernel', '6.6.1~x', '--required'] + names +
            ['--'] + paths, capture_output=True, text=True)

# The positive fixture is actual POSIX shell and closure audits its extracted
# handler with sh -n as well as its exact structural guard check.
assert shell_syntax_ok(VALID_MODEMMANAGER_HOTPLUG)
assert run().returncode == 0

bad = [
    '# dw5934e-autonet: skip wireless interfaces\nmmcli --report-kernel-event=x\n',
    '# dw5934e-autonet: skip wireless interfaces\nmmcli --report-kernel-event=x\nexit 0\n',
    '\n'.join('# ' + line for line in VALID_MODEMMANAGER_HOTPLUG.splitlines()),
    '# dw5934e-autonet: skip wireless interfaces\n[ -n "$INTERFACE" ] || exit 0\nif [ -e "/sys/class/net/$INTERFACE/wireless" ]; then\n exit 0\nfi\nmmcli --report-kernel-event=x\n',
    '[ -n "$INTERFACE" ] || exit 0\nif [ -e "/sys/class/net/$INTERFACE/wireless" ]; then\n exit 0\nfi\nmmcli --report-kernel-event=x\n',
    # This is valid shell syntax but must fail the direct-second-[ structure.
    '# dw5934e-autonet: skip wireless interfaces\n[ -n "$INTERFACE" ] || exit 0\nif [ -e "/sys/class/net/$INTERFACE/wireless" ] || \\\n++ [ -e "/sys/class/net/$INTERFACE/phy80211" ]; then\n exit 0\nfi\nmmcli --report-kernel-event=x\n',
]
for body in bad:
    result = run(body)
    assert result.returncode != 0 and 'hotplug guard invalid' in result.stderr, result.stderr
print('PASS: real ar IPK closure parser, syntax audit, and six isolated invalid-hotplug sets')
