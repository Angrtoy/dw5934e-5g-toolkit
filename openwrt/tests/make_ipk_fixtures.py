#!/usr/bin/env python3
import io
import tarfile

VALID_MODEMMANAGER_HOTPLUG = '''#!/bin/sh
# dw5934e-autonet: skip wireless interfaces
[ -n "$INTERFACE" ] || exit 0
if [ -e "/sys/class/net/$INTERFACE/wireless" ] || \\
   [ -e "/sys/class/net/$INTERFACE/phy80211" ]; then
    exit 0
fi
mmcli --report-kernel-event=x
'''

def tar(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for name, content in files.items():
            entry = tarfile.TarInfo('./' + name)
            encoded = content.encode()
            entry.size = len(encoded)
            archive.addfile(entry, io.BytesIO(encoded))
    return stream.getvalue()

def ipk(path, pkg, arch='aarch64', depends='', guard=True, body=None):
    control = 'Package: %s\nVersion: 1\nArchitecture: %s\n%s' % (
        pkg, arch, ('Depends: ' + depends + '\n') if depends else '')
    if body is not None:
        data = {'etc/hotplug.d/net/25-modemmanager-net': body}
    elif pkg == 'modemmanager' and guard:
        data = {'etc/hotplug.d/net/25-modemmanager-net': VALID_MODEMMANAGER_HOTPLUG}
    else:
        data = {'marker': 'dw5934e-autonet: skip wireless interfaces'}
    members = [('debian-binary', b'2.0\n'),
               ('control.tar.gz', tar({'control': control})),
               ('data.tar.gz', tar(data))]
    with open(path, 'wb') as artifact:
        artifact.write(b'!<arch>\n')
        for name, content in members:
            header = (name + '/').ljust(16).encode()
            header += b'0           0     0     100644  '
            header += str(len(content)).ljust(10).encode() + b'`\n'
            artifact.write(header)
            artifact.write(content)
            if len(content) % 2:
                artifact.write(b'\n')
