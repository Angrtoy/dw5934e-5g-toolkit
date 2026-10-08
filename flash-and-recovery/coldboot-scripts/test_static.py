#!/usr/bin/env python3
"""Offline structural tests; does not invoke systemctl, fwupd, MBIM, QMI, or ADB."""
from pathlib import Path
import subprocess

root=Path(__file__).resolve().parent
a=(root/'phase-a-stage-rc-local.remote.sh').read_text(encoding='utf-8')
b=(root/'phase-b-install-ap047.remote.sh').read_text(encoding='utf-8')
unit=(root/'dw5934e-ap047-phase-b.service').read_text(encoding='utf-8')
for f in ('phase-a-stage-rc-local.remote.sh','phase-b-install-ap047.remote.sh','install-host-artifacts.remote.sh','rollback-before-install.remote.sh'):
    subprocess.run(['bash','-n'], input=(root/f).read_bytes(), check=True)
assert 'c21bedf9042f038bdb5017f490df3f666f4811473c85b93b17d562d2b73e0f29' in a
for needle in ('MODULE_BUSINESS_SENTINELS_OK=1','MODULE_RC_LOCAL_SHA256=','/data/rc.local.pre-low-power-20260904','mhi-pci-generic/unbind','mhi_q/bind','ADB_OPEN_OK=1','NEXT_COLD_BOOT_NATIVE_MAINTENANCE_CONTRACT_OK=1','PHASE_A_DRIVER_LEFT=mhi_q'):
    assert needle in a, needle
assert 'mhi_q/unbind' not in a
assert 'mhi-pci-generic/bind' not in a
for needle in ('BDF=0000:07:00.0','MM_MODEL=DP25-42843-47','SOURCE_VERSION=FDE2.F0.0.0.1.2.CU.001','TARGET_GUID=666d7968-3783-513c-8981-49c6fab13626','MAINTENANCE_RADIO_OFF_SUCCESS_CURRENT_BOOT=1','N78_CRASH_ABSENT_CURRENT_BOOT=1','fwupdmgr install --no-reboot "$CAB"'):
    assert needle in b, needle
for forbidden in ('mhi_q/unbind','mhi-pci-generic/bind','dms-set-operating-mode','qmicli ','modprobe '):
    assert forbidden not in b, forbidden
assert 'INSTALL_STARTED=1\n# Do not put a timeout' in b
postinstall=b.split('INSTALL_STARTED=1', 1)[1]
assert 'systemctl stop ModemManager.service' not in postinstall
for script in (a, b):
    for forbidden in ('rfnv', 'mcfg', 'fcc', 'edl'):
        assert forbidden not in script.lower(), forbidden
assert 'Requires=dw5934e-maintenance-radio-off.service' in unit
assert 'After=dw5934e-maintenance-radio-off.service' in unit
assert '\n[Install]\n' not in unit
print('STATIC_TEST_PASS=1')
