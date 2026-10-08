"""Offline source contract for the read-only raw QMI VOICE Get Config query."""
from pathlib import Path
import re

source = Path(__file__).with_name("dw5934e-voice-control.c").read_text(encoding="utf-8")

assert "OP_VOICE_DOMAIN" in source
assert '"voice-domain"' in source
assert "else if (op == OP_VOICE_DOMAIN)" in source

start = source.index("static void start_voice_domain(void)")
end = source.index("static void action_done", start)
request = source[start:end]
for needle in (
    "qmi_message_new(QMI_SERVICE_VOICE,",
    "qmi_client_get_cid(QMI_CLIENT(voice))",
    "qmi_client_get_next_transaction_id(QMI_CLIENT(voice))",
    "0x0041",
    "qmi_message_tlv_write_init(request, 0x18, &error)",
    "qmi_message_tlv_write_guint8(request, 0x01, &error)",
    "qmi_message_tlv_write_complete(request, tlv_offset, &error)",
    "qmi_device_command_full(dev, request, NULL, TMO, work_cancel, voice_domain_done, NULL)",
):
    assert needle in request, needle
assert re.findall(r"qmi_message_tlv_write_init\(request, (0x[0-9A-F]+), &error\)", request) == ["0x18"]
assert "0x0040" not in request

parser_start = source.index("static gboolean voice_domain_response_succeeded")
parser_end = source.index("static void voice_domain_done", parser_start)
parser = source[parser_start:parser_end]
for needle in (
    "qmi_message_get_raw_tlv(response, 0x02, &result_length)",
    "qmi_message_get_raw_tlv(response, 0x17, &domain_length)",
    "status != 0",
    "QMI_PROTOCOL_ERROR",
    "domain_length < 1",
):
    assert needle in parser, needle

for value, name in ((0, "CS-only"), (1, "PS-only"),
                    (2, "CS-preferred"), (3, "PS-preferred")):
    assert f'case {value}: return "{name}";' in source
assert 'g_print("VOICE_DOMAIN_PREFERENCE=%u %s\\n", preference, name);' in source
assert 'g_print("VOICE_DOMAIN_PREFERENCE=%u unknown(%u)\\n", preference, preference);' in source

# It is a non-capability command, so allocation must take the existing bind gate.
assert "if (op == OP_CAP)\n        start_work();\n    else\n        start_bind();" in source
print("VOICE_DOMAIN_CONTRACT_OK")
