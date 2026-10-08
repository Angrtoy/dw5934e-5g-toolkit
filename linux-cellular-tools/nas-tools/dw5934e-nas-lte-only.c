/*
 * DW5934e constrained NAS LTE-only experiment primitive.
 *
 * This source deliberately uses generated libqmi messages only.  In
 * particular, the one NAS Set System Selection Preference request has only
 * the Mode Preference TLV populated; it never supplies a duration, band,
 * domain, usage, acquisition, or network-selection preference.
 */
#include <gio/gio.h>
#include <glib-unix.h>
#include <libqmi-glib.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#define DEVICE_PATH "/dev/wwan0mbim0"
#define TIMEOUT_SECONDS 25
#define INITIAL_MODE_MASK ((QmiNasRatModePreference)0x0058)
#define LTE_ONLY_MODE_MASK ((QmiNasRatModePreference)0x0010)

typedef enum {
    OP_INSPECT,
    OP_SET_LTE_ONLY,
    OP_RESTORE_INITIAL
} Operation;

static GMainLoop *loop;
static QmiDevice *device;
static QmiClientNas *nas;
static QmiClientImsa *imsa;
static Operation operation;
static QmiNasRatModePreference requested_mode;
static gboolean signal_requested;
static gboolean cleanup_started;
static gboolean close_started;
static gboolean cleanup_failed;
static gboolean operation_succeeded;
static int exit_status = 1;

static void begin_cleanup(void);

static void fail(const char *stage, GError *error)
{
    g_printerr("ERROR=%s:%s\n", stage, error ? error->message : "unknown");
    g_clear_error(&error);
    operation_succeeded = FALSE;
    begin_cleanup();
}

static void finish(void)
{
    exit_status = operation_succeeded && !cleanup_failed && !signal_requested ? 0 : 1;
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
    QmiClient *released = QMI_CLIENT(user_data);

    if (!qmi_device_release_client_finish(QMI_DEVICE(source), result, &error)) {
        g_printerr("ERROR=release-cid:%s\n", error->message);
        g_clear_error(&error);
        cleanup_failed = TRUE;
    }
    if (released == QMI_CLIENT(nas))
        g_clear_object(&nas);
    if (released == QMI_CLIENT(imsa))
        g_clear_object(&imsa);
    begin_cleanup();
}

static void begin_cleanup(void)
{
    QmiClient *client = NULL;

    if (cleanup_started && !nas && !imsa) {
        begin_close();
        return;
    }
    cleanup_started = TRUE;
    /* Only one temporary CID is live at a time, but keep cleanup robust. */
    if (imsa)
        client = QMI_CLIENT(imsa);
    else if (nas)
        client = QMI_CLIENT(nas);
    if (client) {
        qmi_device_release_client(device, client,
                                  QMI_DEVICE_RELEASE_CLIENT_FLAGS_RELEASE_CID,
                                  TIMEOUT_SECONDS, NULL, release_ready, client);
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
    operation_succeeded = FALSE;
    /* An outstanding async callback owns its client/device until *_finish(). */
    return G_SOURCE_CONTINUE;
}

static gboolean stop_requested(void)
{
    return signal_requested;
}

static gboolean get_mode_preference(QmiMessageNasGetSystemSelectionPreferenceOutput *output,
                                    QmiNasRatModePreference *mode,
                                    GError **error)
{
    if (!qmi_message_nas_get_system_selection_preference_output_get_result(output, error))
        return FALSE;
    if (!qmi_message_nas_get_system_selection_preference_output_get_mode_preference(output,
                                                                                      mode,
                                                                                      error))
        return FALSE;
    return TRUE;
}

static void inspect_services_ready(QmiClientImsa *client, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;
    QmiMessageImsaGetImsServicesStatusOutput *output;
    QmiImsaServiceStatus voice_status;
    QmiImsaRegistrationTechnology voice_technology;

    (void)user_data;
    output = qmi_client_imsa_get_ims_services_status_finish(client, result, &error);
    if (!output) {
        fail("imsa-services-transport", error);
        return;
    }
    if (stop_requested()) {
        qmi_message_imsa_get_ims_services_status_output_unref(output);
        begin_cleanup();
        return;
    }
    if (!qmi_message_imsa_get_ims_services_status_output_get_result(output, &error) ||
        !qmi_message_imsa_get_ims_services_status_output_get_ims_voice_service_status(output,
                                                                                         &voice_status,
                                                                                         &error) ||
        !qmi_message_imsa_get_ims_services_status_output_get_ims_voice_service_registration_technology(output,
                                                                                                          &voice_technology,
                                                                                                          &error)) {
        qmi_message_imsa_get_ims_services_status_output_unref(output);
        fail("imsa-services-result", error);
        return;
    }
    g_print("IMSA_VOICE_STATUS=%s\n", qmi_imsa_service_status_get_string(voice_status));
    g_print("IMSA_VOICE_TECHNOLOGY=%s\n",
            qmi_imsa_registration_technology_get_string(voice_technology));
    qmi_message_imsa_get_ims_services_status_output_unref(output);
    operation_succeeded = TRUE;
    begin_cleanup();
}

static void inspect_registration_ready(QmiClientImsa *client, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;
    QmiMessageImsaGetImsRegistrationStatusOutput *output;
    QmiImsaImsRegistrationStatus registration_status;
    QmiImsaRegistrationTechnology registration_technology;

    (void)user_data;
    output = qmi_client_imsa_get_ims_registration_status_finish(client, result, &error);
    if (!output) {
        fail("imsa-registration-transport", error);
        return;
    }
    if (stop_requested()) {
        qmi_message_imsa_get_ims_registration_status_output_unref(output);
        begin_cleanup();
        return;
    }
    if (!qmi_message_imsa_get_ims_registration_status_output_get_result(output, &error) ||
        !qmi_message_imsa_get_ims_registration_status_output_get_ims_registration_status(output,
                                                                                            &registration_status,
                                                                                            &error) ||
        !qmi_message_imsa_get_ims_registration_status_output_get_ims_registration_technology(output,
                                                                                                &registration_technology,
                                                                                                &error)) {
        qmi_message_imsa_get_ims_registration_status_output_unref(output);
        fail("imsa-registration-result", error);
        return;
    }
    g_print("IMSA_REGISTRATION_STATUS=%s\n",
            qmi_imsa_ims_registration_status_get_string(registration_status));
    g_print("IMSA_REGISTRATION_TECHNOLOGY=%s\n",
            qmi_imsa_registration_technology_get_string(registration_technology));
    qmi_message_imsa_get_ims_registration_status_output_unref(output);
    qmi_client_imsa_get_ims_services_status(imsa, NULL, TIMEOUT_SECONDS, NULL,
                                             (GAsyncReadyCallback)inspect_services_ready, NULL);
}

static void imsa_bind_ready(QmiClientImsa *client, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;
    QmiMessageImsaBindOutput *output;

    (void)user_data;
    output = qmi_client_imsa_bind_finish(client, result, &error);
    if (!output) {
        fail("imsa-bind-transport", error);
        return;
    }
    if (stop_requested()) {
        qmi_message_imsa_bind_output_unref(output);
        begin_cleanup();
        return;
    }
    if (!qmi_message_imsa_bind_output_get_result(output, &error)) {
        qmi_message_imsa_bind_output_unref(output);
        fail("imsa-bind-result", error);
        return;
    }
    qmi_message_imsa_bind_output_unref(output);
    qmi_client_imsa_get_ims_registration_status(imsa, NULL, TIMEOUT_SECONDS, NULL,
                                                 (GAsyncReadyCallback)inspect_registration_ready, NULL);
}

static void imsa_allocated_ready(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;
    QmiClient *client;
    QmiMessageImsaBindInput *input;

    (void)user_data;
    client = qmi_device_allocate_client_finish(QMI_DEVICE(source), result, &error);
    if (!client) {
        fail("allocate-imsa-cid", error);
        return;
    }
    imsa = QMI_CLIENT_IMSA(client);
    if (stop_requested()) {
        begin_cleanup();
        return;
    }
    input = qmi_message_imsa_bind_input_new();
    if (!qmi_message_imsa_bind_input_set_binding(input, 0, &error)) {
        qmi_message_imsa_bind_input_unref(input);
        fail("imsa-bind-request", error);
        return;
    }
    qmi_client_imsa_bind(imsa, input, TIMEOUT_SECONDS, NULL,
                         (GAsyncReadyCallback)imsa_bind_ready, NULL);
    qmi_message_imsa_bind_input_unref(input);
}

static void nas_released_for_imsa_ready(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;

    (void)user_data;
    if (!qmi_device_release_client_finish(QMI_DEVICE(source), result, &error)) {
        fail("release-nas-cid", error);
        return;
    }
    g_clear_object(&nas);
    if (stop_requested()) {
        begin_cleanup();
        return;
    }
    qmi_device_allocate_client(device, QMI_SERVICE_IMSA, QMI_CID_NONE, TIMEOUT_SECONDS,
                               NULL, imsa_allocated_ready, NULL);
}

static void readback_ready(QmiClientNas *client, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;
    QmiMessageNasGetSystemSelectionPreferenceOutput *output;
    QmiNasRatModePreference mode;

    (void)user_data;
    output = qmi_client_nas_get_system_selection_preference_finish(client, result, &error);
    if (!output) {
        fail("readback-transport", error);
        return;
    }
    if (stop_requested()) {
        qmi_message_nas_get_system_selection_preference_output_unref(output);
        begin_cleanup();
        return;
    }
    if (!get_mode_preference(output, &mode, &error)) {
        qmi_message_nas_get_system_selection_preference_output_unref(output);
        fail("readback-result", error);
        return;
    }
    g_print("READBACK_MODE_PREFERENCE=0x%04X\n", (unsigned int)mode);
    qmi_message_nas_get_system_selection_preference_output_unref(output);
    if (mode != requested_mode) {
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
        begin_cleanup();
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
    if (!qmi_message_nas_set_system_selection_preference_input_set_mode_preference(input,
                                                                                     requested_mode,
                                                                                     &error)) {
        qmi_message_nas_set_system_selection_preference_input_unref(input);
        fail("set-request", error);
        return;
    }
    g_print("REQUESTED_MODE_PREFERENCE=0x%04X\n", (unsigned int)requested_mode);
    qmi_client_nas_set_system_selection_preference(nas, input, TIMEOUT_SECONDS, NULL,
                                                    (GAsyncReadyCallback)set_ready, NULL);
    qmi_message_nas_set_system_selection_preference_input_unref(input);
}

static void nas_get_ready(QmiClientNas *client, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;
    QmiMessageNasGetSystemSelectionPreferenceOutput *output;
    QmiNasRatModePreference mode;

    (void)user_data;
    output = qmi_client_nas_get_system_selection_preference_finish(client, result, &error);
    if (!output) {
        fail("nas-get-transport", error);
        return;
    }
    if (stop_requested()) {
        qmi_message_nas_get_system_selection_preference_output_unref(output);
        begin_cleanup();
        return;
    }
    if (!get_mode_preference(output, &mode, &error)) {
        qmi_message_nas_get_system_selection_preference_output_unref(output);
        fail("nas-get-result", error);
        return;
    }
    g_print("NAS_MODE_PREFERENCE=0x%04X\n", (unsigned int)mode);
    qmi_message_nas_get_system_selection_preference_output_unref(output);
    if (operation == OP_INSPECT) {
        /* Release NAS before creating the separately scoped IMSA client. */
        qmi_device_release_client(device, QMI_CLIENT(nas),
                                  QMI_DEVICE_RELEASE_CLIENT_FLAGS_RELEASE_CID,
                                  TIMEOUT_SECONDS, NULL, nas_released_for_imsa_ready, NULL);
        return;
    }
    if (operation == OP_SET_LTE_ONLY && mode != INITIAL_MODE_MASK) {
        g_set_error(&error, G_IO_ERROR, G_IO_ERROR_FAILED,
                    "LTE-only requires exact initial mode preference 0x%04X", (unsigned int)INITIAL_MODE_MASK);
        fail("initial-mode", error);
        return;
    }
    start_set();
}

static void nas_allocated_ready(GObject *source, GAsyncResult *result, gpointer user_data)
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
    if (stop_requested()) {
        begin_cleanup();
        return;
    }
    qmi_client_nas_get_system_selection_preference(nas, NULL, TIMEOUT_SECONDS, NULL,
                                                    (GAsyncReadyCallback)nas_get_ready, NULL);
}

static void opened_ready(GObject *source, GAsyncResult *result, gpointer user_data)
{
    GError *error = NULL;

    (void)user_data;
    if (!qmi_device_open_finish(QMI_DEVICE(source), result, &error)) {
        fail("open", error);
        return;
    }
    if (stop_requested()) {
        begin_cleanup();
        return;
    }
    qmi_device_allocate_client(device, QMI_SERVICE_NAS, QMI_CID_NONE, TIMEOUT_SECONDS,
                               NULL, nas_allocated_ready, NULL);
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
    if (stop_requested()) {
        begin_cleanup();
        return;
    }
    qmi_device_open(device, QMI_DEVICE_OPEN_FLAGS_PROXY | QMI_DEVICE_OPEN_FLAGS_MBIM,
                    TIMEOUT_SECONDS, NULL, opened_ready, NULL);
}

static gboolean parse_arguments(int argc, char **argv)
{
    if (argc == 2 && !strcmp(argv[1], "inspect")) {
        operation = OP_INSPECT;
        return TRUE;
    }
    if (argc == 3 && !strcmp(argv[1], "set-lte-only") &&
        !strcmp(argv[2], "--confirm-lte-only")) {
        operation = OP_SET_LTE_ONLY;
        requested_mode = LTE_ONLY_MODE_MASK;
        return TRUE;
    }
    if (argc == 3 && !strcmp(argv[1], "restore-0x0058") &&
        !strcmp(argv[2], "--confirm-restore")) {
        operation = OP_RESTORE_INITIAL;
        requested_mode = INITIAL_MODE_MASK;
        return TRUE;
    }
    return FALSE;
}

int main(int argc, char **argv)
{
    GFile *file;

    if (!parse_arguments(argc, argv)) {
        fprintf(stderr, "usage: %s inspect | set-lte-only --confirm-lte-only | restore-0x0058 --confirm-restore\n",
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
    g_clear_object(&imsa);
    g_clear_object(&device);
    g_main_loop_unref(loop);
    return exit_status;
}
