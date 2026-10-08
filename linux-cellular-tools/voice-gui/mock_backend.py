#!/usr/bin/env python3
"""Offline deterministic backend for GUI tests; it never opens a modem device."""
import os
import sys
mode = os.environ.get("DW5934E_MOCK_MODE", "empty")
args = sys.argv[1:]
if mode == "error":
    print("ERROR mock controlled failure", file=sys.stderr); raise SystemExit(1)
if mode == "cleanup-error":
    print("CLEANUP_CLOSE_FAILED: mock cleanup", file=sys.stderr); raise SystemExit(1)
if args == ["status"]:
    if mode == "active": print("CALL_COUNT=1\nCALL id=7 state=3 type=0 direction=1 mode=9")
    elif mode == "malformed": print("CALL_COUNT=1")
    else: print("CALL_COUNT=0")
elif len(args) == 3 and args[0] in {"dial", "answer", "hangup"} and args[2] == "--confirm":
    print("%s_ACCEPTED call_id=7" % args[0].upper())
else:
    print("REFUSED mock invalid command", file=sys.stderr); raise SystemExit(64)
