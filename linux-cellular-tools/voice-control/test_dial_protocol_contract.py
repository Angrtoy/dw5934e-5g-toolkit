"""Offline guard for the public QMI VOICE Dial Call wire contract.

This test deliberately validates the *public* libqmi schema used to build the
tool.  It does not open a QMI device or try a call.  In particular, do not add
guessed Call Type or audio-attribute TLVs merely because a modem rejects a
proper legacy Dial Call request: those are not Dial Call input fields in the
installed/upstream libqmi API this program uses.
"""
from pathlib import Path
import re


tool_dir = Path(__file__).resolve().parent
root = tool_dir.parents[1]
source = (tool_dir / "dw5934e-voice-control.c").read_text(encoding="utf-8")
schema = (root / "analysis" / "vendor" / "libqmi" / "data" / "qmi-service-voice.json").read_text(
    encoding="utf-8"
)

# The source file is JSON-with-comments, so isolate the Dial Call object rather
# than using json.loads().  Its opening follows a stable section marker and its
# next object begins with End Call.
dial = schema.split('{  "name"    : "Dial Call",', 1)[1].split(
    '{  "name"    : "End Call",', 1
)[0]

assert '"service" : "VOICE"' in dial
assert '"id"      : "0x0020"' in dial
assert dial.count('"type"          : "TLV"') == 1
assert '"name"          : "Calling Number"' in dial
assert '"id"            : "0x01"' in dial
assert '"format"        : "string"' in dial
assert '"name"      : "Call ID"' in dial
assert '"id"        : "0x10"' in dial

# The tool must set the single mandatory request field and must not grow a
# hand-crafted extension through an unsupported generated setter.
assert "qmi_message_voice_dial_call_input_set_calling_number(input, dial_number, &error)" in source
setters = re.findall(r"qmi_message_voice_dial_call_input_set_[a-z_]+", source)
assert setters == ["qmi_message_voice_dial_call_input_set_calling_number"], setters
assert "qmi_client_voice_dial_call(voice, input" in source

print("DIAL_PROTOCOL_CONTRACT_OK")
