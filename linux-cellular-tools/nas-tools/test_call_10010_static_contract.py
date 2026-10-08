#!/usr/bin/env python3
"""Offline contract for the fixed one-call LTE-only orchestration."""
from pathlib import Path
import re
import sys

s = Path(__file__).with_name("dw5934e-lte-only-call-10010-experiment.sh").read_text(encoding="utf-8")

def require(ok, message):
    if not ok:
        print(f"STATIC_CONTRACT_FAIL: {message}", file=sys.stderr)
        raise SystemExit(1)

require("experiment-call-10010 --execute-authorized-call" in s, "fixed entry/token missing")
require(s.count("dial 10010 --confirm") == 1, "exactly one fixed number-only dial required")
require("dial-ims" not in s, "IMS-dial path forbidden")
for item in ("flock -n 9", "NAS_MODE_PREFERENCE=${initial_mask}",
             'wait_for_network_and_ims "${lte_mask}"',
             "IMSA_REGISTRATION_STATUS=registered",
             "IMSA_VOICE_STATUS=available", "IMSA_VOICE_TECHNOLOGY=wwan",
             "packet-service-state[[:space:]]*:[[:space:]]*attached",
             "access-technologies[^:]*:[[:space:]]*.*(lte|4g)",
             "CALL_COUNT=0", "restore-0x0058 --confirm-restore",
             'wait_for_network_and_ims "${initial_mask}"',
             'hangup "${call_id}" --confirm'):
    require(item in s, f"missing contract: {item}")
require(s.count("require_no_existing_calls") >= 3, "zero-call gate required before/after")
require('if [[ -n "${call_id}" ]]; then' in s and 'owned_call_id=1' in s and
        'run_observer_after_call_id' in s, "observer must require an owned call ID")
require("readonly observer_window_seconds=2" in s and 'sleep "${observer_window_seconds}"' in s,
        "observer window must be fixed and within hangup budget")
require("readonly prehangup_deadline_seconds=8" in s and
        "SECONDS - call_id_started_seconds > prehangup_deadline_seconds" in s and
        "DEADLINE_BREACH=PREHANGUP" in s,
        "pre-hangup deadline check missing")
require(s.count('"${voice_tool}" hangup "${call_id}" --confirm') == 1,
        "only attempt_hangup may invoke voice hangup")
require("watchdog" not in s and ") &" not in s,
        "background hangup/watchdog forbidden")
require(s.count("timeout --signal=TERM --kill-after=1s 1s \"${observer_tool}\"") >= 2 and
        s.count("timeout --signal=TERM --kill-after=1s 2s \"${observer_tool}\"") >= 1,
        "observer start/mark/stop timeout budget missing")
require("TO_BE_REPLACED" not in s, "asset hashes must be pinned")
require("systemctl stop" not in s and "NetworkManager" not in s, "service stop forbidden")

def target_mm_ready(text):
    return (
        re.search(r"^[\s]*modem\.3gpp\.registration-state[\s]*:[\s]*(home|roaming)[\s]*$", text, re.I | re.M)
        and re.search(r"^[\s]*modem\.3gpp\.packet-service-state[\s]*:[\s]*attached[\s]*$", text, re.I | re.M)
        and re.search(r"^[\s]*modem\.generic\.access-technologies[^:]*:[\s]*.*(lte|4g)", text, re.I | re.M)
    )

target_mm_lte = """modem.3gpp.registration-state : home
modem.3gpp.packet-service-state : attached
modem.generic.access-technologies : lte
"""
target_mm_4g = """modem.3gpp.registration-state : roaming
modem.3gpp.packet-service-state : attached
modem.generic.access-technologies : 4g
"""
target_mm_bad = """modem.3gpp.registration-state : searching
modem.3gpp.packet-service-state : detached
modem.generic.access-technologies : umts
"""
require(target_mm_ready(target_mm_lte), "target colon-format LTE sample must pass")
require(target_mm_ready(target_mm_4g), "target colon-format 4g sample must pass")
require(not target_mm_ready(target_mm_bad), "non-ready colon-format sample must fail")
target_mm_5gnr_restore = """modem.3gpp.registration-state : home
modem.3gpp.packet-service-state : attached
modem.generic.access-technologies : 5gnr
"""
require("(umts|3g|lte|4g|5gnr|5g)" in s and "5gnr" in target_mm_5gnr_restore,
        "restore mask must accept the real 5gnr recovery sample")
require("CLEANUP_STATUS=HANGUP_FAILED" in s and
        "CLEANUP_STATUS=FINAL_CALL_COUNT_NOT_ZERO_OR_UNAVAILABLE" in s and
        "CLEANUP_STATUS=RESTORE_OR_RECOVERY_FAILED" in s,
        "cleanup failure aggregation status codes missing")
require("workflow_failed=1" in s and "EXPERIMENT_STATUS=INCOMPLETE" in s,
        "no-call-id/readiness incomplete result must be nonzero")
for forbidden in ("imsi", "iccid", "own-number", "msisdn"):
    require(forbidden not in s.lower(), f"identifier surface forbidden: {forbidden}")
print("STATIC_CALL_10010_CONTRACT_OK")
