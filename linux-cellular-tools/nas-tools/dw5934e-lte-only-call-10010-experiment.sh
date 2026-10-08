#!/usr/bin/env bash
# Fixed authorised DW5934e LTE-only/10010/audio-observer experiment.
# This separate entry preserves the original inspect and pure experiment entrypoints.
set -euo pipefail

tool_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
nas_tool="${tool_dir}/dw5934e-nas-lte-only"
voice_tool="${tool_dir}/dw5934e-voice-control"
observer_tool="${tool_dir}/dw5934e-voice-audio-endpoint-observer.sh"
lock_file=/run/lock/dw5934e-nas-lte-only-experiment.lock
voice_binary_sha256=4c9fbd080af18705f628bdae6af2b3bbe7a8c3e6532ee1a6723106e329de270e
observer_script_sha256=d84f3812ee7bebf07f8a2e6f0084576631af3f167af1d0d10753813d181b0a90
readonly lte_mask=0x0010
readonly initial_mask=0x0058
readonly observer_window_seconds=2
readonly prehangup_deadline_seconds=8
readonly readiness_timeout_seconds=180
readonly poll_seconds=5

mode_set_armed=0
mode_restored=0
call_id=""
call_id_started_seconds=0
owned_call_id=0
hangup_complete=0
observer_session=""
cleanup_active=0
workflow_failed=0

usage() {
    printf '%s\n' "usage: $0 experiment-call-10010 --execute-authorized-call" >&2
}

require_root_and_assets() {
    [[ ${EUID} -eq 0 ]] || { printf '%s\n' 'ERROR=must-run-as-root' >&2; exit 2; }
    [[ -x "${nas_tool}" && -x "${voice_tool}" && -x "${observer_tool}" ]] || {
        printf '%s\n' 'ERROR=required-fixed-tool-missing-or-not-executable' >&2; exit 2;
    }
    [[ $(sha256sum "${voice_tool}" | awk '{print $1}') == "${voice_binary_sha256}" ]] || {
        printf '%s\n' 'ERROR=voice-binary-hash-mismatch' >&2; exit 2;
    }
    [[ $(sha256sum "${observer_tool}" | awk '{print $1}') == "${observer_script_sha256}" ]] || {
        printf '%s\n' 'ERROR=observer-script-hash-mismatch' >&2; exit 2;
    }
}

read_mm_state() {
    mmcli -m 0 --output-keyvalue
}

network_and_ims_ready() {
    local expected_mask=$1 inspect_out mm_out
    inspect_out=$("${nas_tool}" inspect)
    mm_out=$(read_mm_state)
    grep -qx "NAS_MODE_PREFERENCE=${expected_mask}" <<<"${inspect_out}" &&
        grep -qx 'IMSA_REGISTRATION_STATUS=registered' <<<"${inspect_out}" &&
        grep -qx 'IMSA_VOICE_STATUS=available' <<<"${inspect_out}" &&
        grep -qx 'IMSA_VOICE_TECHNOLOGY=wwan' <<<"${inspect_out}" &&
        grep -Eiq '^[[:space:]]*modem\.3gpp\.registration-state[[:space:]]*:[[:space:]]*(home|roaming)[[:space:]]*$' <<<"${mm_out}" &&
        grep -Eiq '^[[:space:]]*modem\.3gpp\.packet-service-state[[:space:]]*:[[:space:]]*attached[[:space:]]*$' <<<"${mm_out}" &&
        if [[ "${expected_mask}" == "${lte_mask}" ]]; then
            grep -Eiq '^[[:space:]]*modem\.generic\.access-technologies[^:]*:[[:space:]]*.*(lte|4g)' <<<"${mm_out}"
        else
            grep -Eiq '^[[:space:]]*modem\.generic\.access-technologies[^:]*:[[:space:]]*.*(umts|3g|lte|4g|5gnr|5g)' <<<"${mm_out}"
        fi
}

wait_for_network_and_ims() {
    local expected_mask=$1 deadline
    deadline=$((SECONDS + readiness_timeout_seconds))
    while (( SECONDS < deadline )); do
        if network_and_ims_ready "${expected_mask}"; then
            return 0
        fi
        sleep "${poll_seconds}"
    done
    printf '%s\n' 'ERROR=network-imsa-readiness-timeout' >&2
    return 1
}

require_preflight() {
    local inspect_out
    inspect_out=$("${nas_tool}" inspect)
    grep -qx "NAS_MODE_PREFERENCE=${initial_mask}" <<<"${inspect_out}"
    grep -q '^IMSA_REGISTRATION_STATUS=' <<<"${inspect_out}"
    grep -q '^IMSA_VOICE_STATUS=' <<<"${inspect_out}"
    grep -q '^IMSA_VOICE_TECHNOLOGY=' <<<"${inspect_out}"
}

require_no_existing_calls() {
    local status_out
    status_out=$("${voice_tool}" status)
    grep -qx 'CALL_COUNT=0' <<<"${status_out}"
}

stop_observer_if_started() {
    local result=0
    if [[ -n "${observer_session}" ]]; then
        timeout --signal=TERM --kill-after=1s 2s "${observer_tool}" stop --session-dir "${observer_session}" --phase end >/dev/null || {
            result=1
            printf '%s\n' 'ERROR=observer-stop-failed' >&2
        }
        observer_session=""
    fi
    return "${result}"
}

attempt_hangup() {
    [[ ${hangup_complete} -eq 0 ]] || return 0
    [[ ${owned_call_id} -eq 1 ]] || {
        printf '%s\n' 'HANGUP_ATTEMPT=NO_OWNED_CALL_ID' >&2
        return 0
    }
    "${voice_tool}" hangup "${call_id}" --confirm
    hangup_complete=1
}

restore_fixed_mode_and_verify() {
    [[ ${mode_set_armed} -eq 1 && ${mode_restored} -eq 0 ]] || return 0
    printf '%s\n' '=== FIXED_RESTORE_0x0058 ===' >&2
    "${nas_tool}" restore-0x0058 --confirm-restore
    mode_restored=1
    wait_for_network_and_ims "${initial_mask}"
}

cleanup() {
    local original_status=$?
    local cleanup_failed=0
    local final_status
    [[ ${cleanup_active} -eq 0 ]] || exit 1
    cleanup_active=1
    set +e
    if ! attempt_hangup; then
        printf '%s\n' 'CLEANUP_STATUS=HANGUP_FAILED' >&2
        cleanup_failed=1
    fi
    if ! stop_observer_if_started; then
        printf '%s\n' 'CLEANUP_STATUS=OBSERVER_STOP_FAILED' >&2
        cleanup_failed=1
    fi
    if ! require_no_existing_calls; then
        printf '%s\n' 'CLEANUP_STATUS=FINAL_CALL_COUNT_NOT_ZERO_OR_UNAVAILABLE' >&2
        cleanup_failed=1
    fi
    if ! restore_fixed_mode_and_verify; then
        printf '%s\n' 'CLEANUP_STATUS=RESTORE_OR_RECOVERY_FAILED' >&2
        cleanup_failed=1
    fi
    set -e
    final_status=0
    [[ ${original_status} -eq 0 && ${cleanup_failed} -eq 0 ]] || final_status=1
    exit "${final_status}"
}

run_observer_after_call_id() {
    local start_out
    start_out=$(timeout --signal=TERM --kill-after=1s 1s "${observer_tool}" start --interval 2)
    observer_session=$(sed -n 's/^SESSION_DIR=//p' <<<"${start_out}" | head -n 1)
    [[ -n "${observer_session}" ]] || { printf '%s\n' 'ERROR=observer-session-missing' >&2; return 1; }
    timeout --signal=TERM --kill-after=1s 1s "${observer_tool}" mark --session-dir "${observer_session}" --phase dial >/dev/null
    # Fixed observation window begins only after a concrete call ID and is below 30 seconds.
    sleep "${observer_window_seconds}"
    if (( SECONDS - call_id_started_seconds > prehangup_deadline_seconds )); then
        printf '%s\n' 'DEADLINE_BREACH=PREHANGUP' >&2
        workflow_failed=1
    fi
    attempt_hangup
    timeout --signal=TERM --kill-after=1s 2s "${observer_tool}" stop --session-dir "${observer_session}" --phase end >/dev/null
    observer_session=""
}

main() {
    [[ $# -eq 2 && $1 == experiment-call-10010 && $2 == --execute-authorized-call ]] || { usage; return 2; }
    require_root_and_assets
    exec 9>"${lock_file}"
    flock -n 9 || { printf '%s\n' 'ERROR=experiment-lock-held' >&2; return 1; }
    require_no_existing_calls
    trap cleanup EXIT INT TERM HUP

    printf '%s\n' '=== PRE_MUTATION_READONLY ==='
    require_preflight
    mode_set_armed=1
    printf '%s\n' '=== LTE_ONLY_SET ==='
    "${nas_tool}" set-lte-only --confirm-lte-only
    if wait_for_network_and_ims "${lte_mask}"; then
        require_no_existing_calls
        # This is the single fixed number-only Dial Call invocation.
        local dial_out
        dial_out=$("${voice_tool}" dial 10010 --confirm) || true
        call_id=$(sed -n 's/^DIAL_ACCEPTED call_id=\([0-9][0-9]*\)$/\1/p' <<<"${dial_out}" | head -n 1)
        if [[ -n "${call_id}" ]]; then
            owned_call_id=1
            call_id_started_seconds=${SECONDS}
            run_observer_after_call_id
        else
            printf '%s\n' 'DIAL_RESULT=NO_CALL_ID' >&2
            workflow_failed=1
        fi
    else
        printf '%s\n' 'DIAL_SKIPPED=LTE_IMSA_NOT_READY' >&2
        workflow_failed=1
    fi
    attempt_hangup
    require_no_existing_calls
    restore_fixed_mode_and_verify
    require_no_existing_calls
    trap - EXIT INT TERM HUP
    if [[ ${workflow_failed} -ne 0 ]]; then
        printf '%s\n' 'EXPERIMENT_STATUS=INCOMPLETE' >&2
        return 1
    fi
}

main "$@"
