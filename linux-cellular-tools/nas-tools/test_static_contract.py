#!/usr/bin/env python3
"""Offline source contract for the constrained NAS usage-preference tool."""
from pathlib import Path
import re
import sys

source = Path(__file__).with_name("dw5934e-nas-usage-preference.c")
text = source.read_text(encoding="utf-8")

def require(condition, message):
    if not condition:
        print(f"STATIC_CONTRACT_FAIL: {message}", file=sys.stderr)
        sys.exit(1)

setter_prefix = "qmi_message_nas_set_system_selection_preference_input_set_"
setters = re.findall(r"\b" + re.escape(setter_prefix) + r"[a-z0-9_]+", text)
require(setters == [setter_prefix + "usage_preference"],
        f"expected exactly the Usage Preference setter, found {setters!r}")
all_nas_input_setters = re.findall(r"\bqmi_message_nas_[a-z0-9_]+_input_set_[a-z0-9_]+", text)
require(all_nas_input_setters == [setter_prefix + "usage_preference"],
        f"other NAS input setter is prohibited, found {all_nas_input_setters!r}")

for required in (
    '"get"', '"set-voice-centric"', '"set-data-centric"', '"--confirm"',
    "QMI_NAS_USAGE_PREFERENCE_VOICE_CENTRIC",
    "QMI_NAS_USAGE_PREFERENCE_DATA_CENTRIC",
    "QMI_DEVICE_OPEN_FLAGS_PROXY | QMI_DEVICE_OPEN_FLAGS_MBIM",
    "qmi_device_allocate_client(device, QMI_SERVICE_NAS, QMI_CID_NONE",
    "qmi_client_nas_get_system_selection_preference",
    "qmi_client_nas_set_system_selection_preference",
    "QMI_DEVICE_RELEASE_CLIENT_FLAGS_RELEASE_CID",
    "qmi_device_release_client",
    "qmi_device_close_async",
    "qmi_message_nas_get_system_selection_preference_output_get_usage_preference",
    "OLD=%s", "REQUESTED=%s", "READBACK=%s",
    "g_unix_signal_add(SIGINT", "g_unix_signal_add(SIGTERM", "g_unix_signal_add(SIGHUP",
):
    require(required in text, f"missing required contract token: {required}")

require("qmi_message_new(" not in text and "qmi_device_command" not in text,
        "raw QMI construction/command path is not permitted")
require("value <" not in text and "strtoul" not in text,
        "numeric/raw command input must not be accepted")
require(re.search(r"release_ready[\s\S]*?begin_close\(\);", text) is not None,
        "release completion must proceed to close")
require(re.search(r"if \(nas && device\)[\s\S]*?RELEASE_CID[\s\S]*?return;[\s\S]*?begin_close\(\);", text) is not None,
        "cleanup must release an allocated NAS CID before closing")
require(re.search(r"if \(value != requested\)[\s\S]*?ERROR=readback-mismatch[\s\S]*?begin_cleanup", text) is not None,
        "readback mismatch must fail and clean up")
require(re.search(r"if \(!is_supported_usage_preference\(\*preference\)\)[\s\S]*?return FALSE;", text) is not None,
        "old/readback values must be limited to the two public enum values")

print("STATIC_CONTRACT_OK")
