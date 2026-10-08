"""Offline wire-contract guard for the explicit PS-domain IMS Dial path."""
from pathlib import Path
import re

source = Path(__file__).with_name("dw5934e-voice-control.c").read_text(encoding="utf-8")

assert "OP_DIAL_IMS" in source
assert '"dial-ims"' in source
assert '!strcmp(argv[1], "dial-ims") ? OP_DIAL_IMS : OP_DIAL_IMMEDIATE_HANGUP' in source

start = source.index("static void start_dial_ims(void)")
end = source.index("static const char *voice_domain_name", start)
ims = source[start:end]

# The request is raw QMI VOICE Dial Call with the allocated CID and next client
# transaction. Exact TLV order is number, Voice-IP type, TX|RX attributes, 0.
for needle in (
    "qmi_message_new(QMI_SERVICE_VOICE,",
    "qmi_client_get_cid(QMI_CLIENT(voice))",
    "qmi_client_get_next_transaction_id(QMI_CLIENT(voice))",
    "0x0020",
    "qmi_message_tlv_write_string(request, 0, dial_number, -1, &error)",
    "qmi_message_tlv_write_guint8(request, 0x02, &error)",
    "qmi_message_tlv_write_guint64(request, QMI_ENDIAN_LITTLE, 0x03, &error)",
    "qmi_message_tlv_write_guint64(request, QMI_ENDIAN_LITTLE, 0x00, &error)",
    "qmi_device_command_full(dev, request, NULL, TMO, work_cancel, dial_ims_done, NULL)",
):
    assert needle in ims, needle

tlv_types = re.findall(r"qmi_message_tlv_write_init\(request, (0x[0-9A-F]+), &error\)", ims)
assert tlv_types == ["0x01", "0x10", "0x18", "0x19"], tlv_types

# No service type, CLIR/PI, or other hand-written request TLV belongs here.
assert len(tlv_types) == 4
for forbidden in ("service_type", "clir", "CLIR", "presentation"):
    assert forbidden not in ims, forbidden

# Raw response must propagate a protocol Result failure and require Call ID.
done_start = source.index("static gboolean dial_ims_response_succeeded")
done_end = source.index("static void dial_ims_done", done_start)
parser = source[done_start:done_end]
assert "qmi_message_get_raw_tlv(response, 0x02, &result_length)" in parser
assert "qmi_message_get_raw_tlv(response, 0x10, &call_id_length)" in parser
assert "status != 0" in parser
assert "QMI_PROTOCOL_ERROR" in parser
assert "call_id_length < 1" in parser
assert 'g_print("DIAL_ACCEPTED call_id=%u\\n", id);' in source

# Public dial remains generated and retains its sole public input setter.
setters = re.findall(r"qmi_message_voice_dial_call_input_set_[a-z_]+", source)
assert setters == ["qmi_message_voice_dial_call_input_set_calling_number"], setters
print("DIAL_IMS_PROTOCOL_CONTRACT_OK")
