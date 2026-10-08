/*
 * DW5934e NAS Usage Preference experiment.
 *
 * This is deliberately a small control-plane-only tool.  It uses the public
 * libqmi NAS System Selection Preference API; it does not construct raw QMI
 * packets and it does not activate a data session or make a call.
 */
#include <gio/gio.h>
#include <glib-unix.h>
#include <libqmi-glib.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#define DEVICE_PATH "/dev/wwan0mbim0"
#define TIMEOUT_SECONDS 20

typedef enum {
    OP_GET,
    OP_SET
} Operation;

static GMainLoop *loop;
static QmiDevice *device;
static QmiClientNas *nas;
static Operation operation;
static QmiNasUsagePreference requested;
static gboolean signal_requested;
static gboolean cleanup_started;
static gboolean close_started;
static gboolean cleanup_failed;
static gboolean operation_succeeded;
static int exit_status = 1;

static void begin_cleanup(void);

static const char *usage_preference_name(QmiNasUsagePreference value)
{
    switch (value) {
    case QMI_NAS_USAGE_PREFERENCE_VOICE_CENTRIC:
        return "voice-centric";
    case QMI_NAS_USAGE_PREFERENCE_DATA_CENTRIC:
        return "data-centric";
    default:
        return NULL;
    }
}

static gboolean is_supported_usage_preference(QmiNasUsagePreference value)
{
    return usage_preference_name(value) != NULL;
}

static void fail(const char *stage, GError *error)
{
    g_printerr("ERROR=%s:%s\n", stage, error ? error->message : "unknown");
    g_clear_error(&error);
    operation_succeeded = FALSE;
    begin_cleanup();
}

static void finish(void)
{
    if (operation_succeeded && !cleanup_failed && !signal_requested)
        exit_status = 0;
    else
        exit_status = 1;
    g_main_loop_quit(loop);
}

static void close_ready(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;

    (void)user_data;
    if (!qmi_device_close_finish(QMI_DEVICE(source), result, &error)) {
        g_printerr("ERROR=close:%s\n", error->message);
        g_clear_error(&error);
        cleanup_failed = TRUE;
    }
    finish();
}

static void begin_close(void)
{
    if (close_started)
        return;
    close_started = TRUE;
    if (!device) {
        finish();
        return;
    }
    qmi_device_close_async(device, TIMEOUT_SECONDS, NULL, close_ready, NULL);
}

static void release_ready(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;

    (void)user_data;
    if (!qmi_device_release_client_finish(QMI_DEVICE(source), result, &error)) {
        g_printerr("ERROR=release-cid:%s\n", error->message);
        g_clear_error(&error);
        cleanup_failed = TRUE;
    }
    g_clear_object(&nas);
    begin_close();
}

static void begin_cleanup(void)
{
    if (cleanup_started)
        return;
    cleanup_started = TRUE;
    if (nas && device) {
        qmi_device_release_client(device, QMI_CLIENT(nas),
                                  QMI_DEVICE_RELEASE_CLIENT_FLAGS_RELEASE_CID,
                                  TIMEOUT_SECONDS, NULL, release_ready, NULL);
        return;
    }
    begin_close();
}

static gboolean signal_cleanup(gpointer user_data)
{
    const char *name = user_data;

    if (!signal_requested)
        g_printerr("SIGNAL=%s\n", name);
    signal_requested = TRUE;
    /*
     * Do not destroy a client while an async request still owns it.  Every
     * outstanding request has a finite timeout and its completion callback
     * observes this latch before sending the next operation.
     */
    return G_SOURCE_CONTINUE;
}

static gboolean stop_requested(void)
{
    if (!signal_requested)
        return FALSE;
    operation_succeeded = FALSE;
    begin_cleanup();
    return TRUE;
}

static gboolean get_usage_preference(QmiMessageNasGetSystemSelectionPreferenceOutput *output,
                                     QmiNasUsagePreference *preference,
                                     GError **error)
{
    if (!qmi_message_nas_get_system_selection_preference_output_get_result(output, error))
        return FALSE;
    if (!qmi_message_nas_get_system_selection_preference_output_get_usage_preference(output,
                                                                                       preference,
                                                                                       error))
        return FALSE;
    if (!is_supported_usage_preference(*preference)) {
        g_set_error_literal(error, G_IO_ERROR, G_IO_ERROR_NOT_SUPPORTED,
                            "modem usage preference is not voice-centric or data-centric");
        return FALSE;
    }
    return TRUE;
}

static void readback_ready(QmiClientNas *client, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;
    QmiMessageNasGetSystemSelectionPreferenceOutput *output;
    QmiNasUsagePreference value;
    const char *name;

    (void)user_data;
    output = qmi_client_nas_get_system_selection_preference_finish(client, result, &error);
    if (!output) {
        fail("readback-transport", error);
        return;
    }
    if (stop_requested()) {
        qmi_message_nas_get_system_selection_preference_output_unref(output);
        return;
    }
    if (!get_usage_preference(output, &value, &error)) {
        qmi_message_nas_get_system_selection_preference_output_unref(output);
        fail("readback-result", error);
        return;
    }
    name = usage_preference_name(value);
    g_print("READBACK=%s\n", name);
    qmi_message_nas_get_system_selection_preference_output_unref(output);
    if (value != requested) {
        g_printerr("ERROR=readback-mismatch\n");
        operation_succeeded = FALSE;
        begin_cleanup();
        return;
    }
    operation_succeeded = TRUE;
    begin_cleanup();
}

static void set_ready(QmiClientNas *client, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;
    QmiMessageNasSetSystemSelectionPreferenceOutput *output;

    (void)user_data;
    output = qmi_client_nas_set_system_selection_preference_finish(client, result, &error);
    if (!output) {
        fail("set-transport", error);
        return;
    }
    if (stop_requested()) {
        qmi_message_nas_set_system_selection_preference_output_unref(output);
        return;
    }
    if (!qmi_message_nas_set_system_selection_preference_output_get_result(output, &error)) {
        qmi_message_nas_set_system_selection_preference_output_unref(output);
        fail("set-result", error);
        return;
    }
    qmi_message_nas_set_system_selection_preference_output_unref(output);
    qmi_client_nas_get_system_selection_preference(nas, NULL, TIMEOUT_SECONDS, NULL,
                                                    (GAsyncReadyCallback)readback_ready, NULL);
}

static void start_set(void)
{
    GError *error = NULL;
    QmiMessageNasSetSystemSelectionPreferenceInput *input;

    input = qmi_message_nas_set_system_selection_preference_input_new();
    if (!qmi_message_nas_set_system_selection_preference_input_set_usage_preference(input,
                                                                                       requested,
                                                                                       &error)) {
        qmi_message_nas_set_system_selection_preference_input_unref(input);
        fail("set-request", error);
        return;
    }
    g_print("REQUESTED=%s\n", usage_preference_name(requested));
    qmi_client_nas_set_system_selection_preference(nas, input, TIMEOUT_SECONDS, NULL,
                                                    (GAsyncReadyCallback)set_ready, NULL);
    qmi_message_nas_set_system_selection_preference_input_unref(input);
}

static void initial_get_ready(QmiClientNas *client, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;
    QmiMessageNasGetSystemSelectionPreferenceOutput *output;
    QmiNasUsagePreference value;

    (void)user_data;
    output = qmi_client_nas_get_system_selection_preference_finish(client, result, &error);
    if (!output) {
        fail("get-transport", error);
        return;
    }
    if (stop_requested()) {
        qmi_message_nas_get_system_selection_preference_output_unref(output);
        return;
    }
    if (!get_usage_preference(output, &value, &error)) {
        qmi_message_nas_get_system_selection_preference_output_unref(output);
        fail("get-result", error);
        return;
    }
    g_print("OLD=%s\n", usage_preference_name(value));
    qmi_message_nas_get_system_selection_preference_output_unref(output);
    if (operation == OP_GET) {
        operation_succeeded = TRUE;
        begin_cleanup();
        return;
    }
    start_set();
}

static void allocated_ready(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;
    QmiClient *client;

    (void)user_data;
    client = qmi_device_allocate_client_finish(QMI_DEVICE(source), result, &error);
    if (!client) {
        fail("allocate-nas-cid", error);
        return;
    }
    nas = QMI_CLIENT_NAS(client);
    if (stop_requested())
        return;
    qmi_client_nas_get_system_selection_preference(nas, NULL, TIMEOUT_SECONDS, NULL,
                                                    (GAsyncReadyCallback)initial_get_ready, NULL);
}

static void opened_ready(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;

    (void)user_data;
    if (!qmi_device_open_finish(QMI_DEVICE(source), result, &error)) {
        fail("open", error);
        return;
    }
    if (stop_requested())
        return;
    qmi_device_allocate_client(device, QMI_SERVICE_NAS, QMI_CID_NONE, TIMEOUT_SECONDS,
                               NULL, allocated_ready, NULL);
}

static void created_ready(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;

    (void)source;
    (void)user_data;
    device = qmi_device_new_finish(result, &error);
    if (!device) {
        g_printerr("ERROR=create-device:%s\n", error->message);
        g_clear_error(&error);
        g_main_loop_quit(loop);
        return;
    }
    if (stop_requested())
        return;
    qmi_device_open(device, QMI_DEVICE_OPEN_FLAGS_PROXY | QMI_DEVICE_OPEN_FLAGS_MBIM,
                    TIMEOUT_SECONDS, NULL, opened_ready, NULL);
}

static gboolean parse_arguments(int argc, char **argv)
{
    if (argc == 2 && !strcmp(argv[1], "get")) {
        operation = OP_GET;
        return TRUE;
    }
    if (argc == 3 && !strcmp(argv[2], "--confirm")) {
        operation = OP_SET;
        if (!strcmp(argv[1], "set-voice-centric")) {
            requested = QMI_NAS_USAGE_PREFERENCE_VOICE_CENTRIC;
            return TRUE;
        }
        if (!strcmp(argv[1], "set-data-centric")) {
            requested = QMI_NAS_USAGE_PREFERENCE_DATA_CENTRIC;
            return TRUE;
        }
    }
    return FALSE;
}

int main(int argc, char **argv)
{
    GFile *file;

    if (!parse_arguments(argc, argv)) {
        fprintf(stderr, "usage: %s get | set-voice-centric --confirm | set-data-centric --confirm\n",
                argv[0]);
        return 2;
    }
    if (geteuid() != 0) {
        fprintf(stderr, "ERROR=must-run-as-root\n");
        return 2;
    }

    loop = g_main_loop_new(NULL, FALSE);
    g_unix_signal_add(SIGINT, signal_cleanup, "SIGINT");
    g_unix_signal_add(SIGTERM, signal_cleanup, "SIGTERM");
    g_unix_signal_add(SIGHUP, signal_cleanup, "SIGHUP");
    file = g_file_new_for_path(DEVICE_PATH);
    qmi_device_new(file, NULL, created_ready, NULL);
    g_object_unref(file);
    g_main_loop_run(loop);
    g_clear_object(&nas);
    g_clear_object(&device);
    g_main_loop_unref(loop);
    return exit_status;
}
