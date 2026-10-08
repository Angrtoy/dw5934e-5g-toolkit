"""No-I/O audit of the production combined Dial/End source path."""
from pathlib import Path

s = Path(__file__).with_name("dw5934e-voice-control.c").read_text(encoding="utf-8")

# Command is explicitly fixed and confirmation-gated, rather than becoming a
# general alternate dial interface.
assert '"dial-immediate-hangup"' in s
assert 'strcmp(argv[2], "10010")' in s
assert 'OP_DIAL_IMMEDIATE_HANGUP' in s
assert 'DIAL_IMMEDIATE_HANGUP_OK call_id=%u\\n' in s
assert "publish_combined_success" in s and "fsync(STDOUT_FILENO)" in s

# One Dial completion obtains the invocation-owned ID and directly starts End
# on the same global VOICE client.  No status path occurs in this function.
combined = s[s.index("static void combined_end_done"):s.index("static void action_done")]
assert "qmi_client_voice_end_call_finish(client" in combined
assert "qmi_client_voice_end_call(voice, input, TMO, work_cancel, combined_end_done" in combined
assert "qmi_message_voice_end_call_input_set_call_id(input, combined_call_id" in combined
assert "COMBINED_END_MAX_ATTEMPTS 2" in s
assert "combined_end_attempts < COMBINED_END_MAX_ATTEMPTS" in combined
assert "qmi_client_voice_dial_call" not in combined
assert "get_all_call_info" not in combined and "status" not in combined

dial_branch = s[s.index("if (op == OP_DIAL_IMMEDIATE_HANGUP)"):s.index("if (op == OP_DIAL) {")]
assert "qmi_client_voice_dial_call_finish(client" in dial_branch
assert "combined_call_id = id;" in dial_branch
assert "start_combined_end();" in dial_branch
assert 'fail_terminal("dial-immediate-hangup Dial' in dial_branch
assert "qmi_client_voice_end_call" not in dial_branch  # no End on Dial error branch

# The production signal callback itself, not a shell test, preserves the work
# cancellable across the critical window.  Ordinary commands retain old path.
signal = s[s.index("static gboolean on_signal"):s.index("static void usage")]
assert "op == OP_DIAL_IMMEDIATE_HANGUP && combined_critical" in signal
assert "return G_SOURCE_CONTINUE;" in signal
assert "g_cancellable_cancel(work_cancel);" in signal
start_work = s[s.index("static void start_work"):s.index("static void allocated")]
assert "enter_combined_critical(&error)" in start_work
assert "sigprocmask(SIG_BLOCK" in s and "sigprocmask(SIG_SETMASK" in s
assert "qmi_client_voice_dial_call(voice, input, TMO, work_cancel, action_done" in start_work

# Duplicate/late callbacks cannot start an extra End or mutate an outstanding
# retry.  Success is printed only after End response confirms the same ID.
assert "combined_dial_callback_seen" in s
assert "combined_end_callback_seen" in s
assert "id != combined_call_id" in combined
assert "publish_combined_success(combined_call_id, &error)" in combined
assert combined.index("publish_combined_success(combined_call_id, &error)") < combined.rindex("leave_combined_critical(&error)")

print("COMBINED_DIAL_IMMEDIATE_HANGUP_SOURCE_CONTRACT_OK")
