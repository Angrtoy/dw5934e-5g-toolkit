#!/bin/bash -p
case $- in *p*) ;; *) echo "REFUSE: start with direct executable or /bin/bash -p; ordinary bash is not trusted" >&2; exit 126;; esac
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
cd "$R";/usr/bin/sha256sum -c SHA256SUMS
/usr/bin/python3 - <<'PY'
from pathlib import Path
import xml.etree.ElementTree as E,subprocess
f=Path("firmware/AP070-Recovery-R");a=[p for p in f.iterdir() if p.is_file() and not p.name.startswith("PACKAGE-DERIVED")]
assert len(a)==27 and sum(x.stat().st_size for x in a)==163934470
def h(p):return subprocess.check_output(["/usr/bin/sha256sum",str(p)],text=True).split()[0]
assert h(f/"rawprogram_nand_p4K_b256K.xml")=="a45c48486f344959596f506983609aa24a062727707e57a088ecab4955fe91f9"
assert h(f/"xbl_s_devprg_ns.melf")=="4e06ea4801178f97e8ec8bdedcf4843c5b4afa0eea8a753637fe13d3e53e8515"
d=E.parse(f/"rawprogram_nand_p4K_b256K.xml").getroot();p=d.findall("program");e=d.findall("erase");assert len(p)==39 and len(e)==31
q=Path("tools/qdl-v2.7.1");assert (q/"LICENSE").is_file();assert subprocess.check_output(["/usr/bin/git","-C",str(q),"describe","--exact-match","--tags","HEAD"],text=True).strip()=="v2.7.1";assert subprocess.check_output(["/usr/bin/git","-C",str(q),"rev-parse","HEAD"],text=True).strip()=="a248f28ecd54f66c660bbc3a88657d4c62f1445d"
print("PASS payload 27/163934470, key hashes, XML 39/31, qdl pin")
PY
