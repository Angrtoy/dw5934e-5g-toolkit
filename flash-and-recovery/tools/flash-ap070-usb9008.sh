#!/bin/bash -p
case $- in *p*) ;; *) echo "REFUSE: start with direct executable or /bin/bash -p; ordinary bash is not trusted" >&2; exit 126;; esac
# Experimental lab recovery. Mode defaults to safe qdl --dry-run.
set -Eeuo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
IFS=$' 	
'
umask 077
unset BASH_ENV ENV CDPATH GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_CONFIG_NOSYSTEM GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM GIT_CONFIG_COUNT PYTHONPATH PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT GCONV_PATH QDL
for _v in ${!GIT_CONFIG@}; do unset "$_v"; done
SOURCE="${BASH_SOURCE[0]}"
case "$SOURCE" in /*) ;; *) SOURCE="$(pwd -P)/$SOURCE";; esac
SDIR="${SOURCE%/*}"; [ "$SDIR" = "$SOURCE" ] && SDIR=.
cd -P -- "$SDIR/.."
R="$(pwd -P)"
P="$R/firmware/AP070-Recovery-R"
Q="$R/tools/qdl-v2.7.1/build/qdl"
mode=dry-run;mode_seen=0;variant="";ackefs=0;ackbackup=0;logdir="$R/logs";trust_test=0
bad(){ echo "$*" >&2;exit 64;}
while (($#));do case "$1" in
 --check|--dry-run) ((mode_seen==0))||bad "REFUSE: --check/--dry-run and --execute are mutually exclusive";mode=dry-run;mode_seen=1;;
 --execute) ((mode_seen==0))||bad "REFUSE: --check/--dry-run and --execute are mutually exclusive";mode=execute;mode_seen=1;;
 --variant) shift;(($#))||bad "missing variant";variant="$1";;
 --ack-efs2-erase) ackefs=1;;--ack-same-card-backup) ackbackup=1;;
 --log-dir) shift;(($#))||bad "missing log directory";logdir="$1";;
 --self-test-trust-boundary) trust_test=1;;
 *) bad "unknown argument: $1";;esac;shift;done
# Mode conflict and non-E118 execute rejection occur before verifier/qdl/USB/write commands.
if ((trust_test));then [ "$mode" = dry-run ]&&[ "$mode_seen" = 0 ]||bad "trust self-test takes no mode";echo "TRUST-BOUNDARY SELF-TEST PASS";exit 0;fi
if [ "$mode" = execute ]&&[ "$variant" != E118 ];then echo "REFUSE E11D/E11E: AP070 closure only historical E118." >&2;exit 2;fi
/bin/bash -p "$R/tools/verify-bundle.sh"
[ -x "$Q" ]||{ echo "Run bash tools/build-qdl-ubuntu.sh" >&2;exit 1;}
[ -L "$Q" ]&&{ echo "REFUSE: fixed qdl build output may not be a symlink" >&2;exit 2;}
QREAL=$(/usr/bin/realpath -e "$Q")
[ "$QREAL" = "$R/tools/qdl-v2.7.1/build/qdl" ]||{ echo "REFUSE: qdl realpath differs from fixed package build path" >&2;exit 2;}
[ "$(/usr/bin/git -C "$R/tools/qdl-v2.7.1" describe --exact-match --tags HEAD)" = v2.7.1 ]||exit 2
[ "$(/usr/bin/git -C "$R/tools/qdl-v2.7.1" rev-parse HEAD)" = a248f28ecd54f66c660bbc3a88657d4c62f1445d ]||exit 2
x="$P/rawprogram_nand_p4K_b256K.xml"
if [ "$mode" = dry-run ];then
 if ! "$QREAL" --dry-run "$P/xbl_s_devprg_ns.melf" "$x";then x="$P/PACKAGE-DERIVED-NOT-OFFICIAL-qdl.xml";"$QREAL" --dry-run "$P/xbl_s_devprg_ns.melf" "$x";fi
 echo "SAFE DRY-RUN: no device write.";exit 0
fi
((ackefs&&ackbackup))||{ echo "REFUSE require EFS2 and same-card backup acks." >&2;exit 2;};[ "$(/usr/bin/id -u)" = 0 ]||{ echo "REFUSE root required" >&2;exit 2;}
[ -x /usr/bin/lsusb ]||exit 1
mhi=$(for d in /sys/bus/pci/devices/*;do [ -r "$d/vendor" ]&&[ "$(/usr/bin/cat "$d/vendor")" = 0x105b ]&&{ [ "$(/usr/bin/cat "$d/device")" = 0xe11d ]||[ "$(/usr/bin/cat "$d/device")" = 0xe11e ]||[ "$(/usr/bin/cat "$d/device")" = 0xe118 ];}&&echo x;done|/usr/bin/wc -l)
[ "$(/usr/bin/lsusb -d 05c6:9008|/usr/bin/wc -l)" = 1 ]&&[ "$(/usr/bin/lsusb -d 0489:e131|/usr/bin/wc -l)" = 0 ]&&[ "$mhi" = 0 ]||{ echo "REFUSE exact one USB9008 and no other EDL/MHI EDL device" >&2;exit 2;}
/usr/bin/mkdir -p "$logdir";exec "$QREAL" "$P/xbl_s_devprg_ns.melf" "$x" 2>&1|/usr/bin/tee "$logdir/qdl-$(/usr/bin/date -u +%Y%m%dT%H%M%SZ).log"
