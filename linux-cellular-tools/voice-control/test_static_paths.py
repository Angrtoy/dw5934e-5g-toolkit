"""Fail-closed source-level audit for the async lifecycle; no device I/O."""
from pathlib import Path

s = Path(__file__).with_name("dw5934e-voice-control.c").read_text(encoding="utf-8")

required = (
    "PHASE_OPENING", "PHASE_ALLOCATING", "PHASE_BINDING", "PHASE_WORKING", "PHASE_RELEASING",
    "INFLIGHT_OPEN", "INFLIGHT_ALLOCATE", "INFLIGHT_BIND", "INFLIGHT_WORK", "INFLIGHT_RELEASE",
    "stop_requested", "terminal_error", "cleanup_started", "cleanup_cancel",
    "QMI_DEVICE_RELEASE_CLIENT_FLAGS_RELEASE_CID", "qmi_device_release_client",
    "qmi_device_close_async", "CLEANUP_RELEASE_FAILED", "CLEANUP_CLOSE_FAILED",
    "SIGINT", "SIGTERM", "SIGHUP", "qmi_device_open_finish(QMI_DEVICE(source)",
    "qmi_device_allocate_client_finish(QMI_DEVICE(source)",
    "qmi_client_voice_dial_call_finish(client", "qmi_client_voice_answer_call_finish(client",
    "qmi_client_voice_end_call_finish(client", "qmi_client_voice_get_supported_messages_finish(client",
    "qmi_client_voice_get_all_call_info_finish(client",
    "OP_DIAL_IMMEDIATE_HANGUP", "combined_critical", "combined_end_done",
    "DIAL_IMMEDIATE_HANGUP_OK", "COMBINED_END_MAX_ATTEMPTS",
)
for needle in required:
    assert needle in s, needle

# The public output is line-oriented, including every capability record.
assert 'VOICE_SUPPORTED_COUNT=%u\\n' in s
assert 'VOICE_MESSAGE=0x%04X\\n' in s
# A signal cancels work but cannot launch release while a finish callback is due.
assert "if (cleanup_started || inflight != INFLIGHT_NONE)" in s
assert "g_cancellable_cancel(work_cancel);" in s
# Cleanup has its own never-cancelled cancellable and release always continues to close.
assert "qmi_device_release_client(dev, QMI_CLIENT(voice)" in s
assert "g_clear_object(&voice);\n    start_close();" in s
# Success is committed only after close, and terminal latches cannot be reset.
assert "if (!terminal() && operation_succeeded && !cleanup_failed)" in s
assert "if (!terminal())\n        operation_succeeded = TRUE;" in s
assert "stop_requested = FALSE" not in s
assert "terminal_error = FALSE" not in s
assert "timeout -k" not in s
# The manually serialized Bind Subscription request is for primary subscription
# on the allocated VOICE CID; it is a real async phase, not a fire-and-forget
# request.  Capability discovery intentionally stays on the original path.
assert "qmi_message_new(QMI_SERVICE_VOICE," in s
assert "qmi_client_get_cid(QMI_CLIENT(voice))" in s
assert "qmi_client_get_next_transaction_id(QMI_CLIENT(voice))" in s
assert "0x0044" in s
assert "qmi_message_tlv_write_init(request, 0x01, &error)" in s
assert "qmi_message_tlv_write_guint8(request, 0, &error)" in s
assert "qmi_message_tlv_write_complete(request, tlv_offset, &error)" in s
assert "qmi_device_command_full(dev, request, NULL, TMO, work_cancel, bind_done, NULL)" in s
assert "qmi_device_command_full_finish(QMI_DEVICE(source), result, &error)" in s
assert "qmi_message_get_raw_tlv(response, 0x02, &result_length)" in s
assert "g_set_error(error, QMI_PROTOCOL_ERROR, (QmiProtocolError)protocol_error," in s
assert "if (op == OP_CAP)\n        start_work();\n    else\n        start_bind();" in s
print("STATIC_LIFECYCLE_AUDIT_OK")
