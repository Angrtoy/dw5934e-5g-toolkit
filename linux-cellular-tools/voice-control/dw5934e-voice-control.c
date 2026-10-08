/* Control-only DW5934e QMI VOICE utility.  No audio path is implemented. */
#include <gio/gio.h>
#include <glib-unix.h>
#include <libqmi-glib.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define DEV "/dev/wwan0mbim0"
#define TMO 20

/*
 * There is deliberately just one outstanding asynchronous operation.  In
 * particular, a signal does not tear down objects under an outstanding
 * callback: it cancels the operational request and that callback performs
 * its *_finish(), then drives cleanup.  cleanup_cancel is never cancelled.
 */
typedef enum {
    PHASE_NEW, PHASE_CREATING, PHASE_OPENING, PHASE_ALLOCATING, PHASE_BINDING, PHASE_WORKING,
    PHASE_RELEASING, PHASE_CLOSING, PHASE_DONE
} Phase;
typedef enum {
    INFLIGHT_NONE, INFLIGHT_CREATE, INFLIGHT_OPEN, INFLIGHT_ALLOCATE, INFLIGHT_BIND,
    INFLIGHT_WORK, INFLIGHT_RELEASE, INFLIGHT_CLOSE
} Inflight;
typedef enum {
    OP_CAP, OP_STATUS, OP_VOICE_DOMAIN, OP_DIAL, OP_DIAL_IMS, OP_ANSWER, OP_HANGUP,
    OP_DIAL_IMMEDIATE_HANGUP
} Op;

#define COMBINED_END_MAX_ATTEMPTS 2

static GMainLoop *loop;
static GCancellable *work_cancel;
static GCancellable *cleanup_cancel;
static QmiDevice *dev;
static QmiClientVoice *voice;
static int rc = 1;
static Phase phase = PHASE_NEW;
static Inflight inflight = INFLIGHT_NONE;
/* These are monotonic terminal latches.  No late success may clear either. */
static gboolean stop_requested;
static gboolean terminal_error;
static gboolean cleanup_started;
static gboolean cleanup_failed;
static gboolean device_opened;
static gboolean operation_succeeded;
static Op op;
static const char *dial_number;
static guint8 action_call_id;
/* Combined fixed-call action latches.  They are intentionally independent of
 * generic stop_requested: SIGINT/TERM/HUP must not cancel an owned immediate
 * End Call after this operation has sent Dial and before End has settled. */
static gboolean combined_critical;
static gboolean combined_dial_callback_seen;
static gboolean combined_end_callback_seen;
static guint combined_end_attempts;
static guint8 combined_call_id;
static gboolean combined_signal_masked;
static sigset_t combined_previous_signal_mask;

static void maybe_begin_cleanup(void);
static void start_work(void);
static void start_combined_end(void);
static void fail_terminal(const char *where, GError *error);

static gboolean publish_combined_success(guint8 id, GError **error)
{
    struct stat output_stat;

    g_print("DIAL_IMMEDIATE_HANGUP_OK call_id=%u\n", id);
    if (fflush(stdout) != 0) {
        g_set_error(error, G_FILE_ERROR, g_file_error_from_errno(errno),
                    "cannot flush combined action result: %s", g_strerror(errno));
        return FALSE;
    }
    /* A wrapper redirects stdout to its invocation-scoped combined.log.  Sync a
     * regular file before allowing a zero exit; terminals/pipes intentionally
     * retain their normal non-fsync semantics. */
    if (fstat(STDOUT_FILENO, &output_stat) == 0 && S_ISREG(output_stat.st_mode) &&
        fsync(STDOUT_FILENO) != 0) {
        g_set_error(error, G_FILE_ERROR, g_file_error_from_errno(errno),
                    "cannot sync combined action result: %s", g_strerror(errno));
        return FALSE;
    }
    return TRUE;
}

static gboolean enter_combined_critical(GError **error)
{
    sigset_t blocked;

    sigemptyset(&blocked);
    sigaddset(&blocked, SIGINT);
    sigaddset(&blocked, SIGTERM);
    sigaddset(&blocked, SIGHUP);
    if (sigprocmask(SIG_BLOCK, &blocked, &combined_previous_signal_mask) != 0) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_FAILED,
                    "cannot block combined-action signals: %s", g_strerror(errno));
        return FALSE;
    }
    combined_signal_masked = TRUE;
    combined_critical = TRUE;
    return TRUE;
}

static gboolean leave_combined_critical(GError **error)
{
    combined_critical = FALSE;
    if (combined_signal_masked &&
        sigprocmask(SIG_SETMASK, &combined_previous_signal_mask, NULL) != 0) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_FAILED,
                    "cannot restore combined-action signals: %s", g_strerror(errno));
        return FALSE;
    }
    combined_signal_masked = FALSE;
    return TRUE;
}

static void combined_fail_terminal(const char *where, GError *error)
{
    GError *restore_error = NULL;

    if (!leave_combined_critical(&restore_error)) {
        g_clear_error(&error);
        error = restore_error;
    }
    fail_terminal(where, error);
}

static gboolean terminal(void)
{
    return stop_requested || terminal_error;
}

static void fail_terminal(const char *where, GError *error)
{
    g_printerr("ERROR %s: %s\n", where, error ? error->message : "unknown");
    g_clear_error(&error);
    terminal_error = TRUE;
    rc = 1;
    maybe_begin_cleanup();
}

static gboolean valid_id(const char *text, guint8 *out)
{
    char *end;
    unsigned long value;

    if (!text || !*text)
        return FALSE;
    value = strtoul(text, &end, 10);
    if (*end || value < 1 || value > 255)
        return FALSE;
    *out = (guint8)value;
    return TRUE;
}

static gboolean emergency(const char *number)
{
    static const char *const numbers[] = {
        "110", "112", "119", "120", "122", "911", "999", "000", NULL
    };
    guint i;

    for (i = 0; numbers[i]; i++)
        if (!strcmp(number, numbers[i]))
            return TRUE;
    return FALSE;
}

static gboolean valid_number(const char *number)
{
    size_t length;
    size_t i;

    if (!number || (length = strlen(number)) < 3 || length > 32 || emergency(number))
        return FALSE;
    for (i = 0; i < length; i++)
        if (number[i] < '0' || number[i] > '9')
            return FALSE;
    return TRUE;
}

static void finish_program(void)
{
    phase = PHASE_DONE;
    /* Success is committed only after release and close completed. */
    if (!terminal() && operation_succeeded && !cleanup_failed)
        rc = 0;
    else
        rc = 1;
    g_main_loop_quit(loop);
}

static void close_done(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;

    (void)user_data;
    /* Use callback source, not dev: dev remains valid but cleanup may clear it later. */
    if (!qmi_device_close_finish(QMI_DEVICE(source), result, &error)) {
        g_printerr("CLEANUP_CLOSE_FAILED: %s\n", error->message);
        g_clear_error(&error);
        cleanup_failed = TRUE;
        terminal_error = TRUE;
    }
    inflight = INFLIGHT_NONE;
    finish_program();
}

static void start_close(void)
{
    if (!device_opened || !dev) {
        finish_program();
        return;
    }
    phase = PHASE_CLOSING;
    inflight = INFLIGHT_CLOSE;
    qmi_device_close_async(dev, TMO, cleanup_cancel, close_done, NULL);
}

static void release_done(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;

    (void)user_data;
    /* Release failure is recorded, but never prevents the mandatory close. */
    if (!qmi_device_release_client_finish(QMI_DEVICE(source), result, &error)) {
        g_printerr("CLEANUP_RELEASE_FAILED: %s\n", error->message);
        g_clear_error(&error);
        cleanup_failed = TRUE;
        terminal_error = TRUE;
    }
    inflight = INFLIGHT_NONE;
    g_clear_object(&voice);
    start_close();
}

static void maybe_begin_cleanup(void)
{
    if (cleanup_started || inflight != INFLIGHT_NONE)
        return;
    cleanup_started = TRUE;
    if (voice && device_opened && dev) {
        phase = PHASE_RELEASING;
        inflight = INFLIGHT_RELEASE;
        qmi_device_release_client(dev, QMI_CLIENT(voice),
                                  QMI_DEVICE_RELEASE_CLIENT_FLAGS_RELEASE_CID,
                                  TMO, cleanup_cancel, release_done, NULL);
        return;
    }
    start_close();
}

static void work_succeeded(void)
{
    /* Do not commit rc here: cleanup errors and signals still win. */
    if (!terminal())
        operation_succeeded = TRUE;
    maybe_begin_cleanup();
}

/*
 * Bind the allocated VOICE CID to subscription 0 (the primary subscription)
 * before every operational request except the capability probe.  This request
 * is not generated by libqmi, so preserve the generated-client conventions:
 * use the client's CID and next transaction ID, then inspect Result TLV 0x02.
 */
static gboolean bind_response_succeeded(QmiMessage *response, GError **error)
{
    const guint8 *result;
    guint16 result_length = 0;
    guint16 status;
    guint16 protocol_error;

    result = qmi_message_get_raw_tlv(response, 0x02, &result_length);
    if (!result || result_length < 4) {
        g_set_error(error, QMI_CORE_ERROR, QMI_CORE_ERROR_INVALID_MESSAGE,
                    "Bind Subscription response lacks a complete Result TLV");
        return FALSE;
    }
    status = (guint16)result[0] | ((guint16)result[1] << 8);
    protocol_error = (guint16)result[2] | ((guint16)result[3] << 8);
    if (status == 0)
        return TRUE;
    g_set_error(error, QMI_PROTOCOL_ERROR, (QmiProtocolError)protocol_error,
                "Bind Subscription QMI protocol error (%u): '%s'",
                protocol_error,
                qmi_protocol_error_get_string((QmiProtocolError)protocol_error));
    return FALSE;
}

static void bind_done(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;
    QmiMessage *response;

    (void)user_data;
    response = qmi_device_command_full_finish(QMI_DEVICE(source), result, &error);
    inflight = INFLIGHT_NONE;
    if (!response) {
        if (terminal()) { g_clear_error(&error); maybe_begin_cleanup(); }
        else fail_terminal("VOICE Bind Subscription transport", error);
        return;
    }
    if (terminal()) {
        qmi_message_unref(response);
        maybe_begin_cleanup();
        return;
    }
    if (!bind_response_succeeded(response, &error)) {
        qmi_message_unref(response);
        fail_terminal("VOICE Bind Subscription result", error);
        return;
    }
    qmi_message_unref(response);
    start_work();
}

static void start_bind(void)
{
    GError *error = NULL;
    QmiMessage *request;
    gsize tlv_offset;

    if (terminal()) { maybe_begin_cleanup(); return; }
    request = qmi_message_new(QMI_SERVICE_VOICE,
                              qmi_client_get_cid(QMI_CLIENT(voice)),
                              qmi_client_get_next_transaction_id(QMI_CLIENT(voice)),
                              0x0044);
    tlv_offset = qmi_message_tlv_write_init(request, 0x01, &error);
    if (!tlv_offset ||
        !qmi_message_tlv_write_guint8(request, 0, &error) ||
        !qmi_message_tlv_write_complete(request, tlv_offset, &error)) {
        qmi_message_unref(request);
        fail_terminal("VOICE Bind Subscription request", error);
        return;
    }
    phase = PHASE_BINDING;
    inflight = INFLIGHT_BIND;
    qmi_device_command_full(dev, request, NULL, TMO, work_cancel, bind_done, NULL);
    qmi_message_unref(request);
}

static gboolean dial_ims_response_succeeded(QmiMessage *response, guint8 *id, GError **error)
{
    const guint8 *result;
    const guint8 *call_id;
    guint16 result_length = 0;
    guint16 call_id_length = 0;
    guint16 status;
    guint16 protocol_error;

    result = qmi_message_get_raw_tlv(response, 0x02, &result_length);
    if (!result || result_length < 4) {
        g_set_error(error, QMI_CORE_ERROR, QMI_CORE_ERROR_INVALID_MESSAGE,
                    "Dial IMS response lacks a complete Result TLV");
        return FALSE;
    }
    status = (guint16)result[0] | ((guint16)result[1] << 8);
    protocol_error = (guint16)result[2] | ((guint16)result[3] << 8);
    if (status != 0) {
        g_set_error(error, QMI_PROTOCOL_ERROR, (QmiProtocolError)protocol_error,
                    "Dial IMS QMI protocol error (%u): '%s'",
                    protocol_error,
                    qmi_protocol_error_get_string((QmiProtocolError)protocol_error));
        return FALSE;
    }
    call_id = qmi_message_get_raw_tlv(response, 0x10, &call_id_length);
    if (!call_id || call_id_length < 1) {
        g_set_error(error, QMI_CORE_ERROR, QMI_CORE_ERROR_INVALID_MESSAGE,
                    "Dial IMS response lacks a Call ID TLV");
        return FALSE;
    }
    *id = call_id[0];
    return TRUE;
}

static void dial_ims_done(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;
    QmiMessage *response;
    guint8 id = 0;

    (void)user_data;
    response = qmi_device_command_full_finish(QMI_DEVICE(source), result, &error);
    inflight = INFLIGHT_NONE;
    if (!response) {
        if (terminal()) { g_clear_error(&error); maybe_begin_cleanup(); }
        else fail_terminal("dial-ims transport", error);
        return;
    }
    if (terminal()) {
        qmi_message_unref(response);
        maybe_begin_cleanup();
        return;
    }
    if (!dial_ims_response_succeeded(response, &id, &error)) {
        qmi_message_unref(response);
        fail_terminal("dial-ims result", error);
        return;
    }
    qmi_message_unref(response);
    g_print("DIAL_ACCEPTED call_id=%u\n", id);
    work_succeeded();
}

/*
 * Explicit QCRIL ordinary PS-domain IMS voice Dial Call form.  Keep this
 * distinct from OP_DIAL, which intentionally remains the public libqmi
 * number-only request contract.
 */
static void start_dial_ims(void)
{
    GError *error = NULL;
    QmiMessage *request;
    gsize tlv_offset;

    request = qmi_message_new(QMI_SERVICE_VOICE,
                              qmi_client_get_cid(QMI_CLIENT(voice)),
                              qmi_client_get_next_transaction_id(QMI_CLIENT(voice)),
                              0x0020);
    /* TLV order is protocol evidence: number, VOICE_IP call type, TX|RX, 0. */
    tlv_offset = qmi_message_tlv_write_init(request, 0x01, &error);
    if (!tlv_offset ||
        !qmi_message_tlv_write_string(request, 0, dial_number, -1, &error) ||
        !qmi_message_tlv_write_complete(request, tlv_offset, &error))
        goto build_failed;
    tlv_offset = qmi_message_tlv_write_init(request, 0x10, &error);
    if (!tlv_offset ||
        !qmi_message_tlv_write_guint8(request, 0x02, &error) ||
        !qmi_message_tlv_write_complete(request, tlv_offset, &error))
        goto build_failed;
    tlv_offset = qmi_message_tlv_write_init(request, 0x18, &error);
    if (!tlv_offset ||
        !qmi_message_tlv_write_guint64(request, QMI_ENDIAN_LITTLE, 0x03, &error) ||
        !qmi_message_tlv_write_complete(request, tlv_offset, &error))
        goto build_failed;
    tlv_offset = qmi_message_tlv_write_init(request, 0x19, &error);
    if (!tlv_offset ||
        !qmi_message_tlv_write_guint64(request, QMI_ENDIAN_LITTLE, 0x00, &error) ||
        !qmi_message_tlv_write_complete(request, tlv_offset, &error))
        goto build_failed;
    qmi_device_command_full(dev, request, NULL, TMO, work_cancel, dial_ims_done, NULL);
    qmi_message_unref(request);
    return;

build_failed:
    qmi_message_unref(request);
    inflight = INFLIGHT_NONE;
    fail_terminal("dial-ims request", error);
}

static const char *voice_domain_name(guint8 preference)
{
    switch (preference) {
    case 0: return "CS-only";
    case 1: return "PS-only";
    case 2: return "CS-preferred";
    case 3: return "PS-preferred";
    default: return NULL;
    }
}

static gboolean voice_domain_response_succeeded(QmiMessage *response,
                                                guint8 *preference,
                                                GError **error)
{
    const guint8 *result;
    const guint8 *domain;
    guint16 result_length = 0;
    guint16 domain_length = 0;
    guint16 status;
    guint16 protocol_error;

    result = qmi_message_get_raw_tlv(response, 0x02, &result_length);
    if (!result || result_length < 4) {
        g_set_error(error, QMI_CORE_ERROR, QMI_CORE_ERROR_INVALID_MESSAGE,
                    "Get Config response lacks a complete Result TLV");
        return FALSE;
    }
    status = (guint16)result[0] | ((guint16)result[1] << 8);
    protocol_error = (guint16)result[2] | ((guint16)result[3] << 8);
    if (status != 0) {
        g_set_error(error, QMI_PROTOCOL_ERROR, (QmiProtocolError)protocol_error,
                    "Get Config QMI protocol error (%u): '%s'",
                    protocol_error,
                    qmi_protocol_error_get_string((QmiProtocolError)protocol_error));
        return FALSE;
    }
    domain = qmi_message_get_raw_tlv(response, 0x17, &domain_length);
    if (!domain || domain_length < 1) {
        g_set_error(error, QMI_CORE_ERROR, QMI_CORE_ERROR_INVALID_MESSAGE,
                    "Get Config response lacks Voice Domain Preference TLV");
        return FALSE;
    }
    *preference = domain[0];
    return TRUE;
}

static void voice_domain_done(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;
    QmiMessage *response;
    guint8 preference = 0;
    const char *name;

    (void)user_data;
    response = qmi_device_command_full_finish(QMI_DEVICE(source), result, &error);
    inflight = INFLIGHT_NONE;
    if (!response) {
        if (terminal()) { g_clear_error(&error); maybe_begin_cleanup(); }
        else fail_terminal("voice-domain transport", error);
        return;
    }
    if (terminal()) {
        qmi_message_unref(response);
        maybe_begin_cleanup();
        return;
    }
    if (!voice_domain_response_succeeded(response, &preference, &error)) {
        qmi_message_unref(response);
        fail_terminal("voice-domain result", error);
        return;
    }
    qmi_message_unref(response);
    name = voice_domain_name(preference);
    if (name)
        g_print("VOICE_DOMAIN_PREFERENCE=%u %s\n", preference, name);
    else
        g_print("VOICE_DOMAIN_PREFERENCE=%u unknown(%u)\n", preference, preference);
    work_succeeded();
}

static void start_voice_domain(void)
{
    GError *error = NULL;
    QmiMessage *request;
    gsize tlv_offset;

    request = qmi_message_new(QMI_SERVICE_VOICE,
                              qmi_client_get_cid(QMI_CLIENT(voice)),
                              qmi_client_get_next_transaction_id(QMI_CLIENT(voice)),
                              0x0041);
    tlv_offset = qmi_message_tlv_write_init(request, 0x18, &error);
    if (!tlv_offset ||
        !qmi_message_tlv_write_guint8(request, 0x01, &error) ||
        !qmi_message_tlv_write_complete(request, tlv_offset, &error)) {
        qmi_message_unref(request);
        inflight = INFLIGHT_NONE;
        fail_terminal("voice-domain request", error);
        return;
    }
    qmi_device_command_full(dev, request, NULL, TMO, work_cancel, voice_domain_done, NULL);
    qmi_message_unref(request);
}

/*
 * This is deliberately a same-client, same-process continuation, rather than
 * a wrapper-level dial/log/second-process sequence.  A transient End response
 * failure gets one bounded retry for the already-proven ID; it never reissues
 * Dial, consults status, or discovers another call ID.
 */
static void combined_end_done(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;
    QmiMessageVoiceEndCallOutput *output;
    QmiClientVoice *client = QMI_CLIENT_VOICE(source);
    guint8 id = 0;
    gboolean ok;

    (void)user_data;
    output = qmi_client_voice_end_call_finish(client, result, &error);
    /* A GLib async operation calls its finish method exactly once, but retain a
     * fail-closed latch so a duplicated/late callback cannot launch another
     * End Call or clear the retry operation currently in flight. */
    if (combined_end_callback_seen) {
        if (output)
            qmi_message_voice_end_call_output_unref(output);
        g_clear_error(&error);
        return;
    }
    combined_end_callback_seen = TRUE;
    inflight = INFLIGHT_NONE;
    if (!output) {
        if (combined_end_attempts < COMBINED_END_MAX_ATTEMPTS) {
            g_clear_error(&error);
            start_combined_end();
            return;
        }
        combined_fail_terminal("dial-immediate-hangup End Call transport", error);
        return;
    }
    ok = qmi_message_voice_end_call_output_get_result(output, &error);
    if (ok)
        ok = qmi_message_voice_end_call_output_get_call_id(output, &id, &error);
    qmi_message_voice_end_call_output_unref(output);
    if (!ok || id != combined_call_id) {
        if (ok) {
            g_set_error(&error, QMI_CORE_ERROR, QMI_CORE_ERROR_INVALID_MESSAGE,
                        "End Call response ID %u does not match owned ID %u",
                        id, combined_call_id);
        }
        if (combined_end_attempts < COMBINED_END_MAX_ATTEMPTS) {
            g_clear_error(&error);
            start_combined_end();
            return;
        }
        combined_fail_terminal("dial-immediate-hangup End Call result", error);
        return;
    }
    if (!publish_combined_success(combined_call_id, &error)) {
        combined_fail_terminal("dial-immediate-hangup result publication", error);
        return;
    }
    if (!leave_combined_critical(&error)) {
        fail_terminal("dial-immediate-hangup signal restore", error);
        return;
    }
    work_succeeded();
}

static void start_combined_end(void)
{
    QmiMessageVoiceEndCallInput *input;

    /* combined_call_id is assigned only by the successful Dial response. */
    combined_end_attempts++;
    combined_end_callback_seen = FALSE;
    phase = PHASE_WORKING;
    inflight = INFLIGHT_WORK;
    input = qmi_message_voice_end_call_input_new();
    qmi_message_voice_end_call_input_set_call_id(input, combined_call_id, NULL);
    qmi_client_voice_end_call(voice, input, TMO, work_cancel, combined_end_done, NULL);
    qmi_message_voice_end_call_input_unref(input);
}

static void action_done(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;
    guint8 id = 0;
    gboolean ok;
    QmiClientVoice *client = QMI_CLIENT_VOICE(source);

    (void)user_data;
    if (op == OP_DIAL_IMMEDIATE_HANGUP) {
        QmiMessageVoiceDialCallOutput *output =
            qmi_client_voice_dial_call_finish(client, result, &error);
        if (combined_dial_callback_seen) {
            if (output)
                qmi_message_voice_dial_call_output_unref(output);
            g_clear_error(&error);
            return;
        }
        combined_dial_callback_seen = TRUE;
        inflight = INFLIGHT_NONE;
        if (!output) {
            combined_fail_terminal("dial-immediate-hangup Dial transport", error);
            return;
        }
        ok = qmi_message_voice_dial_call_output_get_result(output, &error);
        if (ok)
            ok = qmi_message_voice_dial_call_output_get_call_id(output, &id, &error);
        qmi_message_voice_dial_call_output_unref(output);
        if (!ok) {
            combined_fail_terminal("dial-immediate-hangup Dial result", error);
            return;
        }
        combined_call_id = id;
        start_combined_end();
        return;
    }
    inflight = INFLIGHT_NONE;
    if (op == OP_DIAL) {
        QmiMessageVoiceDialCallOutput *output =
            qmi_client_voice_dial_call_finish(client, result, &error);
        if (!output) {
            if (terminal()) { g_clear_error(&error); maybe_begin_cleanup(); }
            else fail_terminal("dial transport", error);
            return;
        }
        if (terminal()) { qmi_message_voice_dial_call_output_unref(output); maybe_begin_cleanup(); return; }
        ok = qmi_message_voice_dial_call_output_get_result(output, &error);
        if (ok)
            ok = qmi_message_voice_dial_call_output_get_call_id(output, &id, &error);
        qmi_message_voice_dial_call_output_unref(output);
        if (!ok) { fail_terminal("dial result", error); return; }
        g_print("DIAL_ACCEPTED call_id=%u\n", id);
    } else if (op == OP_ANSWER) {
        QmiMessageVoiceAnswerCallOutput *output =
            qmi_client_voice_answer_call_finish(client, result, &error);
        if (!output) {
            if (terminal()) { g_clear_error(&error); maybe_begin_cleanup(); }
            else fail_terminal("answer transport", error);
            return;
        }
        if (terminal()) { qmi_message_voice_answer_call_output_unref(output); maybe_begin_cleanup(); return; }
        ok = qmi_message_voice_answer_call_output_get_result(output, &error);
        if (ok)
            ok = qmi_message_voice_answer_call_output_get_call_id(output, &id, &error);
        qmi_message_voice_answer_call_output_unref(output);
        if (!ok) { fail_terminal("answer result", error); return; }
        g_print("ANSWER_ACCEPTED call_id=%u\n", id);
    } else {
        QmiMessageVoiceEndCallOutput *output =
            qmi_client_voice_end_call_finish(client, result, &error);
        if (!output) {
            if (terminal()) { g_clear_error(&error); maybe_begin_cleanup(); }
            else fail_terminal("hangup transport", error);
            return;
        }
        if (terminal()) { qmi_message_voice_end_call_output_unref(output); maybe_begin_cleanup(); return; }
        ok = qmi_message_voice_end_call_output_get_result(output, &error);
        if (ok)
            ok = qmi_message_voice_end_call_output_get_call_id(output, &id, &error);
        qmi_message_voice_end_call_output_unref(output);
        if (!ok) { fail_terminal("hangup result", error); return; }
        g_print("HANGUP_ACCEPTED call_id=%u\n", id);
    }
    work_succeeded();
}

static void read_done(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;
    QmiClientVoice *client = QMI_CLIENT_VOICE(source);

    (void)user_data;
    inflight = INFLIGHT_NONE;
    if (op == OP_CAP) {
        QmiMessageVoiceGetSupportedMessagesOutput *output =
            qmi_client_voice_get_supported_messages_finish(client, result, &error);
        GArray *array = NULL;
        guint count = 0, i;

        if (!output) {
            if (terminal()) { g_clear_error(&error); maybe_begin_cleanup(); }
            else fail_terminal("capabilities transport", error);
            return;
        }
        if (terminal()) { qmi_message_voice_get_supported_messages_output_unref(output); maybe_begin_cleanup(); return; }
        if (!qmi_message_voice_get_supported_messages_output_get_result(output, &error) ||
            !qmi_message_voice_get_supported_messages_output_get_list(output, &array, &error)) {
            qmi_message_voice_get_supported_messages_output_unref(output);
            fail_terminal("capabilities result", error);
            return;
        }
        for (i = 0; array && i < array->len; i++) {
            guint8 byte = g_array_index(array, guint8, i);
            guint bit;
            for (bit = 0; bit < 8; bit++)
                if (byte & (1u << bit))
                    count++;
        }
        g_print("VOICE_SUPPORTED_COUNT=%u\n", count);
        for (i = 0; array && i < array->len; i++) {
            guint8 byte = g_array_index(array, guint8, i);
            guint bit;
            for (bit = 0; bit < 8; bit++)
                if (byte & (1u << bit))
                    g_print("VOICE_MESSAGE=0x%04X\n", bit + 8 * i);
        }
        qmi_message_voice_get_supported_messages_output_unref(output);
        work_succeeded();
        return;
    }
    {
        QmiMessageVoiceGetAllCallInfoOutput *output =
            qmi_client_voice_get_all_call_info_finish(client, result, &error);
        GArray *array = NULL;
        guint i;

        if (!output) {
            if (terminal()) { g_clear_error(&error); maybe_begin_cleanup(); }
            else fail_terminal("status transport", error);
            return;
        }
        if (terminal()) { qmi_message_voice_get_all_call_info_output_unref(output); maybe_begin_cleanup(); return; }
        if (!qmi_message_voice_get_all_call_info_output_get_result(output, &error)) {
            qmi_message_voice_get_all_call_info_output_unref(output);
            fail_terminal("status result", error);
            return;
        }
        if (!qmi_message_voice_get_all_call_info_output_get_call_information(output, &array, &error)) {
            /* No Call Information TLV means no calls, not a failed status request. */
            g_clear_error(&error);
            g_print("CALL_COUNT=0\n");
            qmi_message_voice_get_all_call_info_output_unref(output);
            work_succeeded();
            return;
        }
        g_print("CALL_COUNT=%u\n", array->len);
        for (i = 0; i < array->len; i++) {
            QmiMessageVoiceGetAllCallInfoOutputCallInformationCall *call =
                &g_array_index(array, QmiMessageVoiceGetAllCallInfoOutputCallInformationCall, i);
            g_print("CALL id=%u state=%u type=%u direction=%u mode=%u\n",
                    call->id, call->state, call->type, call->direction, call->mode);
        }
        qmi_message_voice_get_all_call_info_output_unref(output);
        work_succeeded();
    }
}

static void start_work(void)
{
    GError *error = NULL;

    if (terminal()) { maybe_begin_cleanup(); return; }
    phase = PHASE_WORKING;
    inflight = INFLIGHT_WORK;
    if (op == OP_CAP) {
        qmi_client_voice_get_supported_messages(voice, NULL, TMO, work_cancel, read_done, NULL);
    } else if (op == OP_STATUS) {
        qmi_client_voice_get_all_call_info(voice, NULL, TMO, work_cancel, read_done, NULL);
    } else if (op == OP_VOICE_DOMAIN) {
        start_voice_domain();
    } else if (op == OP_DIAL || op == OP_DIAL_IMMEDIATE_HANGUP) {
        QmiMessageVoiceDialCallInput *input = qmi_message_voice_dial_call_input_new();
        if (!qmi_message_voice_dial_call_input_set_calling_number(input, dial_number, &error)) {
            qmi_message_voice_dial_call_input_unref(input);
            inflight = INFLIGHT_NONE;
            fail_terminal("dial input", error);
            return;
        }
        if (op == OP_DIAL_IMMEDIATE_HANGUP) {
            /* Block the three async control signals in this process before the
             * Dial send; on_signal() is a second guard if a queued GLib source
             * runs at a boundary.  This does not depend on caller SIG_IGN. */
            if (!enter_combined_critical(&error)) {
                qmi_message_voice_dial_call_input_unref(input);
                inflight = INFLIGHT_NONE;
                fail_terminal("dial-immediate-hangup signal block", error);
                return;
            }
            combined_dial_callback_seen = FALSE;
            combined_end_callback_seen = FALSE;
            combined_end_attempts = 0;
            combined_call_id = 0;
        }
        qmi_client_voice_dial_call(voice, input, TMO, work_cancel, action_done, NULL);
        qmi_message_voice_dial_call_input_unref(input);
    } else if (op == OP_DIAL_IMS) {
        start_dial_ims();
    } else if (op == OP_ANSWER) {
        QmiMessageVoiceAnswerCallInput *input = qmi_message_voice_answer_call_input_new();
        qmi_message_voice_answer_call_input_set_call_id(input, action_call_id, NULL);
        qmi_client_voice_answer_call(voice, input, TMO, work_cancel, action_done, NULL);
        qmi_message_voice_answer_call_input_unref(input);
    } else {
        QmiMessageVoiceEndCallInput *input = qmi_message_voice_end_call_input_new();
        qmi_message_voice_end_call_input_set_call_id(input, action_call_id, NULL);
        qmi_client_voice_end_call(voice, input, TMO, work_cancel, action_done, NULL);
        qmi_message_voice_end_call_input_unref(input);
    }
}

static void allocated(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;

    (void)user_data;
    voice = QMI_CLIENT_VOICE(qmi_device_allocate_client_finish(QMI_DEVICE(source), result, &error));
    inflight = INFLIGHT_NONE;
    if (!voice) {
        if (terminal()) { g_clear_error(&error); maybe_begin_cleanup(); }
        else fail_terminal("VOICE client", error);
        return;
    }
    /* A signal during allocation still owns a real client, so RELEASE_CID it. */
    if (terminal()) { maybe_begin_cleanup(); return; }
    if (op == OP_CAP)
        start_work();
    else
        start_bind();
}

static void opened(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;

    (void)user_data;
    if (!qmi_device_open_finish(QMI_DEVICE(source), result, &error)) {
        inflight = INFLIGHT_NONE;
        if (terminal()) { g_clear_error(&error); maybe_begin_cleanup(); }
        else fail_terminal("device open", error);
        return;
    }
    inflight = INFLIGHT_NONE;
    device_opened = TRUE;
    /* On a signal during open, a successful open must be paired with close. */
    if (terminal()) { maybe_begin_cleanup(); return; }
    phase = PHASE_ALLOCATING;
    inflight = INFLIGHT_ALLOCATE;
    qmi_device_allocate_client(QMI_DEVICE(source), QMI_SERVICE_VOICE, QMI_CID_NONE,
                               TMO, work_cancel, allocated, NULL);
}

static void created(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;

    (void)source;
    (void)user_data;
    dev = qmi_device_new_finish(result, &error);
    inflight = INFLIGHT_NONE;
    if (!dev) {
        if (terminal()) { g_clear_error(&error); maybe_begin_cleanup(); }
        else fail_terminal("device create", error);
        return;
    }
    if (terminal()) { maybe_begin_cleanup(); return; }
    phase = PHASE_OPENING;
    inflight = INFLIGHT_OPEN;
    qmi_device_open(dev, QMI_DEVICE_OPEN_FLAGS_PROXY | QMI_DEVICE_OPEN_FLAGS_MBIM,
                    TMO, work_cancel, opened, NULL);
}

static gboolean on_signal(gpointer user_data)
{
    (void)user_data;
    if (op == OP_DIAL_IMMEDIATE_HANGUP && combined_critical) {
        /* The Dial request may already have created a call even if its callback
         * has not run.  Do not cancel it or a proven subsequent End Call.  The
         * bounded End retry/terminal failure path is the only completion path
         * for this critical ownership window.  SIGKILL and power loss remain
         * outside any userspace recovery guarantee. */
        return G_SOURCE_CONTINUE;
    }
    /* Idempotent: do not begin release/close while an operational finish is due. */
    stop_requested = TRUE;
    rc = 1;
    if (work_cancel)
        g_cancellable_cancel(work_cancel);
    /* The outstanding create/open/allocate/work callback starts cleanup after finish(). */
    return G_SOURCE_CONTINUE;
}

static void usage(const char *program)
{
    fprintf(stderr,
            "Usage: %s capabilities|status|voice-domain|dial NUMBER --confirm|dial-ims NUMBER --confirm|dial-immediate-hangup 10010 --confirm|answer CALL_ID --confirm|hangup CALL_ID --confirm|selftest\n"
            "CONTROL-ONLY: no host audio/media is implemented.\n", program);
}

int main(int argc, char **argv)
{
    GFile *file;

    if (argc == 2 && !strcmp(argv[1], "selftest")) {
        if (valid_number("13800138000") && !valid_number("110") &&
            !valid_number("12a") && valid_id("255", &action_call_id) &&
            !valid_id("0", &action_call_id)) {
            puts("SELFTEST_OK");
            return 0;
        }
        return 1;
    }
    if (argc < 2) { usage(argv[0]); return 64; }
    if (!strcmp(argv[1], "capabilities") && argc == 2)
        op = OP_CAP;
    else if (!strcmp(argv[1], "status") && argc == 2)
        op = OP_STATUS;
    else if (!strcmp(argv[1], "voice-domain") && argc == 2)
        op = OP_VOICE_DOMAIN;
    else if ((!strcmp(argv[1], "dial") || !strcmp(argv[1], "dial-ims") ||
              !strcmp(argv[1], "dial-immediate-hangup")) &&
             argc == 4 && !strcmp(argv[3], "--confirm")) {
        if (!valid_number(argv[2])) {
            fputs("REFUSED invalid, empty, non-digit, or emergency number\n", stderr);
            return 64;
        }
        if (!strcmp(argv[1], "dial-immediate-hangup") && strcmp(argv[2], "10010")) {
            fputs("REFUSED dial-immediate-hangup is fixed to 10010\n", stderr);
            return 64;
        }
        op = !strcmp(argv[1], "dial") ? OP_DIAL :
             !strcmp(argv[1], "dial-ims") ? OP_DIAL_IMS : OP_DIAL_IMMEDIATE_HANGUP;
        dial_number = argv[2];
    } else if ((!strcmp(argv[1], "answer") || !strcmp(argv[1], "hangup")) &&
               argc == 4 && !strcmp(argv[3], "--confirm")) {
        if (!valid_id(argv[2], &action_call_id)) {
            fputs("REFUSED invalid call ID\n", stderr);
            return 64;
        }
        op = !strcmp(argv[1], "answer") ? OP_ANSWER : OP_HANGUP;
    } else { usage(argv[0]); return 64; }

    if (geteuid() != 0) {
        fputs("REFUSED root required for existing mbim-proxy socket; use sudo\n", stderr);
        return 77;
    }
    loop = g_main_loop_new(NULL, FALSE);
    work_cancel = g_cancellable_new();
    cleanup_cancel = g_cancellable_new();
    g_unix_signal_add(SIGINT, on_signal, NULL);
    g_unix_signal_add(SIGTERM, on_signal, NULL);
    g_unix_signal_add(SIGHUP, on_signal, NULL);
    file = g_file_new_for_path(DEV);
    phase = PHASE_CREATING;
    inflight = INFLIGHT_CREATE;
    qmi_device_new(file, work_cancel, created, NULL);
    g_object_unref(file);
    g_main_loop_run(loop);
    g_clear_object(&voice);
    g_clear_object(&dev);
    g_clear_object(&work_cancel);
    g_clear_object(&cleanup_cancel);
    g_main_loop_unref(loop);
    return rc;
}
