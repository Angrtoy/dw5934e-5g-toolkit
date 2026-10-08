#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin
readonly BDF=0000:07:00.0 DEV=/sys/bus/pci/devices/0000:07:00.0
readonly H=$HOME/e11d_restore_transaction_20260728/mhi_adb_exec_resync.py
readonly R=/data/rc.local.pre-low-power-20260904
readonly RH=c21bedf9042f038bdb5017f490df3f666f4811473c85b93b17d562d2b73e0f29
test "$(basename "$(readlink -f "$DEV/driver")")" = mhi_q
test -c /dev/mhi_ADB
O=$(timeout 90 python3 "$H" --device /dev/mhi_ADB --timeout 60 "set -eu; echo '60a8592b6310b03230c45f205ee901add65b16591d16a20001763d120174cc61  /data/dw_dms' | sha256sum -c -; echo 'b059e447fe8013e8a4da31cbdba02ceb9172bd821e3aa3766f7d9798d599f6bc  /data/dw_dms_ctl' | sha256sum -c -; echo 'ba2c14950dbe001a601b9041ba2de01abf03d411f7af628843dd2a0ff11b2ac2  /etc/init.d/dw_dms' | sha256sum -c -; echo '$RH  $R' | sha256sum -c -; cp -p '$R' /etc/rc.local; sync; echo '$RH  /etc/rc.local' | sha256sum -c -; echo MODULE_RC_LOCAL_ONLINE_RESTORED=1" 2>&1)
printf '%s\n' "$O"
printf '%s\n' "$O" | grep -Fx MODULE_RC_LOCAL_ONLINE_RESTORED=1 >/dev/null
echo PHASE_A_COMPLETE_NEXT_COLD_BOOT_REQUIRED=1
