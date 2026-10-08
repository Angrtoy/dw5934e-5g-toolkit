#!/usr/bin/env bash
#
# Authorised, serialised experiment driver.  The default is read-only inspect.
# State changes require the separate, exact --execute token.
set -euo pipefail

tool_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
tool="${tool_dir}/dw5934e-nas-lte-only"
lock_file=/run/lock/dw5934e-nas-lte-only-experiment.lock
poll_seconds=5
wait_seconds=180
set_issued=0
restore_done=0

usage() {
    printf '%s\n' "usage: $0 inspect | experiment --execute" >&2
}

require_root() {
    if [[ ${EUID} -ne 0 ]]; then
        printf '%s\n' 'ERROR=must-run-as-root' >&2
        exit 2
    fi
}

release_guard() {
    local status=$?
    # Once the set command is about to be invoked, any normal error or trapped
    # INT/TERM/HUP takes the fixed restoration path.  This cannot handle a
    # SIGKILL, power loss, kernel crash, or an interrupted process which never
    # executes its trap.
    if [[ ${set_issued} -eq 1 && ${restore_done} -eq 0 ]]; then
        restore_done=1
        printf '%s\n' '=== FIXED_RESTORE_0x0058 ===' >&2
        "${tool}" restore-0x0058 --confirm-restore >&2 || \
            printf '%s\n' 'ERROR=fixed-restore-failed' >&2
    fi
    exit "${status}"
}

read_only_mm_state() {
    mmcli -m 0 --output-keyvalue
}

require_preflight() {
    local inspect_out mm_out
    inspect_out=$("${tool}" inspect)
    printf '%s\n' "${inspect_out}"
    mm_out=$(read_only_mm_state)
    printf '%s\n' "${mm_out}"
    grep -qx 'NAS_MODE_PREFERENCE=0x0058' <<<"${inspect_out}"
    # This verifies that the required read-only IMSA fields were observable;
    # it intentionally does not require IMS to be healthy before the trial.
    grep -q '^IMSA_REGISTRATION_STATUS=' <<<"${inspect_out}"
    grep -q '^IMSA_VOICE_STATUS=' <<<"${inspect_out}"
    grep -q '^IMSA_VOICE_TECHNOLOGY=' <<<"${inspect_out}"
}

postcondition_ready() {
    local inspect_out=$1 mm_out=$2
    grep -qx 'NAS_MODE_PREFERENCE=0x0010' <<<"${inspect_out}" &&
        grep -qx 'IMSA_REGISTRATION_STATUS=registered' <<<"${inspect_out}" &&
        grep -qx 'IMSA_VOICE_STATUS=available' <<<"${inspect_out}" &&
        grep -qx 'IMSA_VOICE_TECHNOLOGY=wwan' <<<"${inspect_out}" &&
        grep -Eiq '^modem\.3gpp\.registration-state=(home|roaming)$' <<<"${mm_out}" &&
        grep -Eiq '^modem\.3gpp\.packet-service-state=attached$' <<<"${mm_out}" &&
        grep -Eiq '^modem\.generic\.access-technologies.*=.*lte' <<<"${mm_out}"
}

wait_for_postcondition() {
    local deadline inspect_out mm_out
    deadline=$((SECONDS + wait_seconds))
    while (( SECONDS < deadline )); do
        inspect_out=$("${tool}" inspect)
        mm_out=$(read_only_mm_state)
        printf '%s\n' '=== POSTCONDITION_SAMPLE ==='
        printf '%s\n' "${inspect_out}"
        printf '%s\n' "${mm_out}"
        if postcondition_ready "${inspect_out}" "${mm_out}"; then
            printf '%s\n' 'POSTCONDITION=LTE_REGISTERED_PS_ATTACHED_IMS_REGISTERED_IMS_VOICE_AVAILABLE_WWAN'
            return 0
        fi
        sleep "${poll_seconds}"
    done
    printf '%s\n' 'ERROR=postcondition-timeout' >&2
    return 1
}

main() {
    case ${1-} in
        inspect)
            [[ $# -eq 1 ]] || { usage; return 2; }
            require_root
            exec 9>"${lock_file}"
            flock -n 9 || { printf '%s\n' 'ERROR=experiment-lock-held' >&2; return 1; }
            "${tool}" inspect
            read_only_mm_state
            ;;
        experiment)
            [[ $# -eq 2 && ${2} == --execute ]] || { usage; return 2; }
            require_root
            exec 9>"${lock_file}"
            flock -n 9 || { printf '%s\n' 'ERROR=experiment-lock-held' >&2; return 1; }
            trap release_guard EXIT INT TERM HUP
            printf '%s\n' '=== PRE_MUTATION_READONLY ==='
            require_preflight
            # Do not move this latch below the command: a transport failure
            # after request submission must also invoke the fixed restoration.
            set_issued=1
            printf '%s\n' '=== LTE_ONLY_SET ==='
            "${tool}" set-lte-only --confirm-lte-only
            wait_for_postcondition
            printf '%s\n' '=== FIXED_RESTORE_0x0058 ==='
            "${tool}" restore-0x0058 --confirm-restore
            restore_done=1
            printf '%s\n' '=== RESTORE_READBACK ==='
            "${tool}" inspect | grep -qx 'NAS_MODE_PREFERENCE=0x0058'
            trap - EXIT INT TERM HUP
            ;;
        *) usage; return 2 ;;
    esac
}

main "$@"
