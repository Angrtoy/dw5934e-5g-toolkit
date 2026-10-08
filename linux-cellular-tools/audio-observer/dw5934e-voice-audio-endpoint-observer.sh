#!/usr/bin/env bash
#
# Read-only real-call audio endpoint observer for Ubuntu.
#
# Purpose:
#   Collect host-visible endpoint/process/audio-related path snapshots in a timestamped
#   sequence while the user executes a "pre -> dial -> connected -> end" flow.
#
# Safety contract:
#   - No writes to modem control nodes.
#   - No calls to qmicli/mbimcli/mmcli.
#   - No automatic dialing.
#   - No remote execution.
#   - Non-root friendly (degrades if files are unreadable).
#
set -euo pipefail
IFS=$'\n\t'
umask 077

readonly SCRIPT_PATH=$(realpath "$0")
readonly SCRIPT_NAME=$(basename "$SCRIPT_PATH")
readonly DEFAULT_SESSION_ROOT="${DW5934E_AUDIO_OBSERVER_ROOT:-${XDG_STATE_HOME:-${HOME}/.local/state}/dw5934e-voice-audio-endpoint-observer}"
readonly DEFAULT_LSPCI_SLOT="0000:07:00.0"
readonly DEFAULT_INTERVAL_SECONDS=2
readonly ALLOWED_PHASES="pre dial connected end"

usage() {
  cat <<'EOF'
Usage:
  dw5934e-voice-audio-endpoint-observer.sh start [options]
  dw5934e-voice-audio-endpoint-observer.sh mark --session-dir PATH --phase pre|dial|connected|end
  dw5934e-voice-audio-endpoint-observer.sh stop --session-dir PATH [--phase end]
  dw5934e-voice-audio-endpoint-observer.sh status --session-dir PATH

Start/stop options:
  --session-dir PATH      Optional: keep all artifacts under PATH.
                         Default: ${DW5934E_AUDIO_OBSERVER_ROOT:-$HOME/.local/state/...}
  --interval SECONDS      Sample interval in whole seconds. Default: 2
  --phase pre|dial|connected|end
                         Initial phase for start. Default: pre
  --lspci-slot SLOT       PCI BDF for lspci check, default 0000:07:00.0
  --with-udev-events      Collect optional read-only udev events into udev-events.log
  --once                  Collect exactly one sample and exit (useful for offline checks).

Control:
  mark command writes a phase marker used by subsequent snapshots.
  stop command signals a running start session to terminate and finalize manifest.

Output:
  <session_dir>/manifest.json  (record index + file hashes)
  <session_dir>/manifest.sha256 (manifest hash)
EOF
}

fatal() {
  echo "ERROR: $*" >&2
  exit 1
}

now_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

generate_session_dir() {
  local base_dir=$1
  local stamp
  local uuid
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  uuid=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || date +%s%N)
  echo "${base_dir}/session-${stamp}-${uuid}"
}

validate_phase() {
  local phase=$1
  case " ${ALLOWED_PHASES} " in
    *" ${phase} "*) return 0 ;;
    *) return 1 ;;
  esac
}

append_section_header() {
  local output_file=$1
  local title=$2
  printf '\n[%s]\n' "$title" >> "$output_file"
}

capture_dir_listing() {
  local output_file=$1
  local title=$2
  local target=$3

  append_section_header "$output_file" "$title"
  if [[ -d "$target" ]]; then
    ls -la "$target" >> "$output_file" 2>&1 || echo "ERROR: ls failed" >> "$output_file"
  else
    echo "MISSING: ${target}" >> "$output_file"
  fi
}

capture_mhi_uevents() {
  local output_file=$1
  local -a devices
  local device

  append_section_header "$output_file" "MHI device uevents"
  shopt -s nullglob
  devices=(/sys/bus/mhi/devices/*)
  shopt -u nullglob
  if ((${#devices[@]} == 0)); then
    echo "NO_MHI_DEVICES" >> "$output_file"
    return
  fi
  for device in "${devices[@]}"; do
    printf '\n-- %s --\n' "$(basename "$device")" >> "$output_file"
    if [[ -r "${device}/uevent" ]]; then
      cat "${device}/uevent" >> "$output_file" 2>&1 || echo "ERROR: read failed" >> "$output_file"
    else
      echo "MISSING: ${device}/uevent" >> "$output_file"
    fi
  done
}

capture_text_file() {
  local output_file=$1
  local title=$2
  local target=$3

  append_section_header "$output_file" "$title"
  if [[ -r "$target" ]]; then
    cat "$target" >> "$output_file" 2>&1 || echo "ERROR: read failed" >> "$output_file"
  else
    echo "MISSING: ${target}" >> "$output_file"
  fi
}

capture_command_output() {
  local output_file=$1
  local title=$2
  shift 2

  append_section_header "$output_file" "$title"
  if (($# == 0)); then
    echo "ERROR: internal capture_command_output missing command" >> "$output_file"
    return
  fi
  if command -v "$1" >/dev/null 2>&1; then
    "$@" >> "$output_file" 2>&1 || true
  else
    echo "MISSING_COMMAND: $1" >> "$output_file"
  fi
}

capture_file_glob_list() {
  local output_file=$1
  local title=$2
  local pattern=$3
  local -a matches

  append_section_header "$output_file" "$title"
  shopt -s nullglob
  matches=(${pattern})
  shopt -u nullglob
  if ((${#matches[@]} == 0)); then
    echo "NO_MATCH" >> "$output_file"
    return
  fi
  local node
  for node in "${matches[@]}"; do
    printf '%s\n' "$node" >> "$output_file"
  done
}

capture_wwan0_status() {
  local output_file=$1
  append_section_header "$output_file" "wwan0 status"
  if [[ -d /sys/class/net/wwan0 ]]; then
    for item in carrier operstate; do
      if [[ -r "/sys/class/net/wwan0/$item" ]]; then
        printf '%s=' "$item" >> "$output_file"
        cat "/sys/class/net/wwan0/$item" >> "$output_file" 2>&1 || echo "ERR" >> "$output_file"
        echo >> "$output_file"
      else
        echo "${item}=MISSING" >> "$output_file"
      fi
    done
  else
    echo "wwan0 not present in /sys/class/net" >> "$output_file"
  fi
}

collect_process_snapshot() {
  local output_file=$1
  append_section_header "$output_file" "process status (relevant)"
  if command -v ps >/dev/null 2>&1; then
    ps -eo pid,user,ppid,stat,comm --no-headers 2>/dev/null \
      | awk 'BEGIN{OFS="\t"}($5 ~ /dw5934e-voice|aplay|arecord|qmi|wwan|ModemManager|mhi|mbim|MMI|voice/){print $1,$2,$3,$4,$5}' \
      >> "$output_file" 2>&1 || true
  else
    echo "ps command unavailable" >> "$output_file"
  fi
}

record_marker() {
  local session_dir=$1
  local phase=$2
  local marker_file="${session_dir}/markers.ndjson"

  printf '{"timestamp":"%s","phase":"%s"}\n' "$(now_utc)" "$phase" >> "$marker_file"
  echo "$phase" > "${session_dir}/phase.current"
}

collect_snapshot() {
  local session_dir=$1
  local phase=$2
  local snap_id
  local snapshot_file
  local snapshot_dir="${session_dir}/snapshots"

  mkdir -p "$snapshot_dir"
  snap_id=$(date -u +%Y%m%dT%H%M%SZ)-$$-$(date +%s%N)
  snapshot_file="${snapshot_dir}/snapshot_${snap_id}.txt"

  {
    echo "timestamp=$(now_utc)"
    echo "phase=${phase}"
  } > "$snapshot_file"

  capture_dir_listing "$snapshot_file" "/sys/bus/mhi/devices" "/sys/bus/mhi/devices"
  capture_mhi_uevents "$snapshot_file"
  capture_file_glob_list "$snapshot_file" "/dev/wwan* listing" "/dev/wwan*"
  capture_dir_listing "$snapshot_file" "/dev/snd" "/dev/snd"
  capture_dir_listing "$snapshot_file" "/sys/class/sound" "/sys/class/sound"
  capture_text_file "$snapshot_file" "/proc/asound/cards" "/proc/asound/cards"
  capture_text_file "$snapshot_file" "/proc/asound/pcm" "/proc/asound/pcm"
  capture_command_output "$snapshot_file" "aplay -l" aplay -l
  capture_command_output "$snapshot_file" "arecord -l" arecord -l
  capture_command_output "$snapshot_file" "lspci -vvnn -s slot" lspci -vvnn -s "${DW5934E_LSPCI_SLOT:-$DEFAULT_LSPCI_SLOT}"
  capture_wwan0_status "$snapshot_file"
  collect_process_snapshot "$snapshot_file"

  if [[ -f "${session_dir}/with_udev_events" && $(cat "${session_dir}/with_udev_events") == "1" ]]; then
    append_section_header "$snapshot_file" "udev_events_seen"
    if [[ -s "${session_dir}/udev-events.log" ]]; then
      tail -n 20 "${session_dir}/udev-events.log" >> "$snapshot_file" 2>/dev/null || true
    else
      echo "no events captured yet" >> "$snapshot_file"
    fi
  fi
}

json_escape() {
  local value=$1
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  value=${value//$'\n'/\\n}
  value=${value//$'\r'/\\r}
  value=${value//$'\t'/\\t}
  printf '%s' "$value"
}

sha256_file() {
  local path=$1
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  else
    echo "UNSUPPORTED"
  fi
}

current_phase_for_session() {
  local session_dir=$1
  local phase="pre"
  if [[ -f "${session_dir}/phase.current" ]]; then
    phase=$(cat "${session_dir}/phase.current")
  fi
  printf '%s' "$phase"
}

finalize_manifest() {
  local session_dir=$1
  local manifest_path="${session_dir}/manifest.json"
  local marker_file="${session_dir}/markers.ndjson"
  local snap_dir="${session_dir}/snapshots"
  local started_at="unknown"
  local stopped_at
  local interval="0"
  local lspci_slot="$DEFAULT_LSPCI_SLOT"
  local with_udev="0"
  local session_id="unknown"
  local -a snapshot_files
  local -i marker_first=1
  local -i snap_first=1
  local marker_line

  if [[ -f "${session_dir}/session.start" ]]; then
    started_at=$(cat "${session_dir}/session.start")
  fi
  if [[ -f "${session_dir}/session.interval" ]]; then
    interval=$(cat "${session_dir}/session.interval")
  fi
  if [[ -f "${session_dir}/session.lspci_slot" ]]; then
    lspci_slot=$(cat "${session_dir}/session.lspci_slot")
  fi
  if [[ -f "${session_dir}/with_udev_events" ]]; then
    with_udev=$(cat "${session_dir}/with_udev_events")
  fi
  if [[ -f "${session_dir}/session.id" ]]; then
    session_id=$(cat "${session_dir}/session.id")
  fi

  stopped_at=$(now_utc)

  {
    echo '{'
    echo "  \"session_id\": \"$(json_escape "$session_id")\","
    echo "  \"session_dir\": \"$(json_escape "$session_dir")\","
    echo "  \"started_at\": \"$(json_escape "$started_at")\","
    echo "  \"stopped_at\": \"$(json_escape "$stopped_at")\","
    echo "  \"interval_seconds\": ${interval},"
    echo "  \"lspci_slot\": \"$(json_escape "$lspci_slot")\","
    echo "  \"with_udev_events\": ${with_udev},"
    echo '  "markers": ['
  } > "$manifest_path"

  if [[ -f "$marker_file" ]]; then
    while IFS= read -r marker_line || [[ -n "$marker_line" ]]; do
      if (( marker_first == 0 )); then
        printf '    ,\n' >> "$manifest_path"
      fi
      marker_first=0
      if [[ -z "$marker_line" ]]; then
        printf '    null\n' >> "$manifest_path"
      else
        printf '    %s\n' "$marker_line" >> "$manifest_path"
      fi
    done < "$marker_file"
  fi
  echo '  ],' >> "$manifest_path"

  echo '  "snapshots": [' >> "$manifest_path"
  shopt -s nullglob
  snapshot_files=("${snap_dir}"/snapshot_*.txt)
  shopt -u nullglob
  local snap_file
  for snap_file in "${snapshot_files[@]}"; do
    local snap_name
    local phase
    local hash
    snap_name=$(basename "$snap_file")
    phase=$(awk -F= '/^phase=/{print $2}' "$snap_file" | head -n 1)
    hash=$(sha256_file "$snap_file")
    if (( snap_first == 0 )); then
      printf '    ,\n' >> "$manifest_path"
    fi
    snap_first=0
    printf '    {"file":"%s","phase":"%s","sha256":"%s"}\n' \
      "$(json_escape "$snap_name")" "$(json_escape "$phase")" "$(json_escape "$hash")" >> "$manifest_path"
  done

  echo '  ]' >> "$manifest_path"
  echo '}' >> "$manifest_path"

  local manifest_hash
  manifest_hash=$(sha256_file "$manifest_path")
  echo "$manifest_hash  manifest.json" > "${session_dir}/manifest.sha256"
  echo "MANIFEST_HASH=$manifest_hash" > "${session_dir}/manifest.hash"
}

daemon_loop() {
  local session_dir=""
  local interval=$DEFAULT_INTERVAL_SECONDS
  local lspci_slot="$DEFAULT_LSPCI_SLOT"
  local with_udev=0
  local run_once=0
  local udev_pid=""

  while (( "$#" > 0 )); do
    case $1 in
      --session-dir)
        session_dir=$2
        shift 2
        ;;
      --interval)
        interval=$2
        shift 2
        ;;
      --lspci-slot)
        lspci_slot=$2
        shift 2
        ;;
      --with-udev-events)
        with_udev=1
        shift
        ;;
      --once)
        run_once=1
        shift
        ;;
      *)
        fatal "unknown daemon arg: $1"
        ;;
    esac
  done

  [[ -n "$session_dir" ]] || fatal "daemon missing --session-dir"
  [[ -d "$session_dir" ]] || fatal "daemon session dir missing: $session_dir"

  DW5934E_LSPCI_SLOT=$lspci_slot
  export DW5934E_LSPCI_SLOT

  # Keep a single point for the optional udev monitor setting.
  printf '%s\n' "$with_udev" > "${session_dir}/with_udev_events"
  printf '%s\n' "$interval" > "${session_dir}/session.interval"

  local running=1
  local stop_requested=0
  trap 'stop_requested=1; running=0' SIGTERM SIGINT

  if (( with_udev == 1 )) && command -v udevadm >/dev/null 2>&1; then
    udevadm monitor --kernel --property \
      --subsystem-match=mhi --subsystem-match=wwan --subsystem-match=sound \
      > "${session_dir}/udev-events.log" 2>&1 &
    udev_pid=$!
    echo "$udev_pid" > "${session_dir}/udev-monitor.pid"
  fi

  local sample_count=0
  while (( running == 1 )); do
    local phase
    phase=$(current_phase_for_session "$session_dir")
    collect_snapshot "$session_dir" "$phase"
    ((sample_count += 1))
    if (( run_once == 1 )); then
      break
    fi
    if (( stop_requested == 1 )); then
      break
    fi
    if (( interval <= 0 )); then
      break
    fi
    sleep "$interval"
  done

  if [[ -n "$udev_pid" ]] && kill -0 "$udev_pid" >/dev/null 2>&1; then
    kill "$udev_pid" >/dev/null 2>&1 || true
    wait "$udev_pid" 2>/dev/null || true
  fi

  finalize_manifest "$session_dir"
}

cmd_start() {
  local session_dir=""
  local interval=$DEFAULT_INTERVAL_SECONDS
  local phase="pre"
  local lspci_slot="$DEFAULT_LSPCI_SLOT"
  local with_udev=0
  local once=0
  local output_root="$DEFAULT_SESSION_ROOT"

  while (( "$#" > 0 )); do
    case $1 in
      --session-dir)
        session_dir=$2
        shift 2
        ;;
      --interval)
        interval=$2
        shift 2
        ;;
      --phase)
        phase=$2
        if ! validate_phase "$phase"; then
          fatal "invalid phase: $phase"
        fi
        shift 2
        ;;
      --lspci-slot)
        lspci_slot=$2
        shift 2
        ;;
      --with-udev-events)
        with_udev=1
        shift
        ;;
      --once)
        once=1
        shift
        ;;
      --root-dir|--state-root)
        output_root=$2
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fatal "unknown start option: $1"
        ;;
    esac
  done

  [[ "$interval" =~ ^[0-9]+$ ]] || fatal "interval must be integer seconds"
  if [[ -z "$session_dir" ]]; then
    session_dir=$(generate_session_dir "$output_root")
  fi
  [[ ! -e "$session_dir" ]] || fatal "refusing existing session-dir: $session_dir"
  mkdir -p "$output_root"
  mkdir -m 0700 "$session_dir"
  mkdir -m 0700 "${session_dir}/snapshots"

  local sid
  sid=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || date +%s%N)
  printf '%s\n' "$sid" > "${session_dir}/session.id"
  printf '%s\n' "$(now_utc)" > "${session_dir}/session.start"
  printf '%s\n' "$interval" > "${session_dir}/session.interval"
  printf '%s\n' "$lspci_slot" > "${session_dir}/session.lspci_slot"
  printf '%s\n' "$with_udev" > "${session_dir}/with_udev_events"
  record_marker "$session_dir" "$phase"

  if (( once == 1 )); then
    daemon_loop --session-dir "$session_dir" --interval "$interval" --lspci-slot "$lspci_slot" --once
    echo "SESSION_DIR=${session_dir}"
    echo "MANIFEST=${session_dir}/manifest.json"
    cat "${session_dir}/manifest.hash"
    return 0
  fi

  # Background run with strict cleanup path on stop.
  local -a daemon_args=(
    "$SCRIPT_PATH"
    _daemon
    --session-dir
    "$session_dir"
    --interval
    "$interval"
    --lspci-slot
    "$lspci_slot"
  )
  if (( with_udev == 1 )); then
    daemon_args+=(--with-udev-events)
  fi
  "${daemon_args[@]}" >"${session_dir}/observer.log" 2>&1 < /dev/null &
  local pid=$!
  echo "$pid" > "${session_dir}/observer.pid"
  echo "SESSION_DIR=${session_dir}"
  echo "MANIFEST=${session_dir}/manifest.json"
  echo "MARK='pre|dial|connected|end' via: ${SCRIPT_NAME} mark --session-dir ${session_dir} --phase PHASE"
  echo "STOP via: ${SCRIPT_NAME} stop --session-dir ${session_dir} [--phase end]"
  echo "DAEMON_PID=${pid}"
}

cmd_mark() {
  local session_dir=""
  local phase=""

  while (( "$#" > 0 )); do
    case $1 in
      --session-dir)
        session_dir=$2
        shift 2
        ;;
      --phase)
        phase=$2
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fatal "unknown mark option: $1"
        ;;
    esac
  done

  [[ -n "$session_dir" ]] || fatal "mark requires --session-dir"
  [[ -d "$session_dir" ]] || fatal "mark session-dir missing: $session_dir"
  if [[ -z "$phase" ]]; then
    fatal "mark requires --phase pre|dial|connected|end"
  fi
  validate_phase "$phase" || fatal "invalid phase: $phase"
  record_marker "$session_dir" "$phase"
  echo "MARKED=${phase}"
}

cmd_status() {
  local session_dir=""

  while (( "$#" > 0 )); do
    case $1 in
      --session-dir)
        session_dir=$2
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fatal "unknown status option: $1"
        ;;
    esac
  done

  [[ -n "$session_dir" ]] || fatal "status requires --session-dir"
  echo "SESSION_DIR=${session_dir}"
  if [[ -f "${session_dir}/observer.pid" ]]; then
    local pid
    pid=$(cat "${session_dir}/observer.pid")
    if kill -0 "$pid" >/dev/null 2>&1; then
      echo "RUNNING=1"
      echo "PID=${pid}"
    else
      echo "RUNNING=0"
    fi
  else
    echo "RUNNING=0"
  fi
  if [[ -f "${session_dir}/manifest.json" ]]; then
    echo "MANIFEST_READY=1"
  else
    echo "MANIFEST_READY=0"
  fi
  if [[ -f "${session_dir}/manifest.sha256" ]]; then
    echo "MANIFEST_HASH=$(cat "${session_dir}/manifest.sha256")"
  fi
}

pid_matches_observer() {
  local pid=$1
  local session_dir=$2
  local cmdline

  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  [[ -r "/proc/${pid}/cmdline" ]] || return 1
  cmdline=$(tr '\0' '\n' < "/proc/${pid}/cmdline")
  grep -Fqx -- "$SCRIPT_PATH" <<<"$cmdline" || return 1
  grep -Fqx -- "_daemon" <<<"$cmdline" || return 1
  grep -Fqx -- "$session_dir" <<<"$cmdline" || return 1
}

cmd_stop() {
  local session_dir=""
  local phase="end"

  while (( "$#" > 0 )); do
    case $1 in
      --session-dir)
        session_dir=$2
        shift 2
        ;;
      --phase)
        phase=$2
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fatal "unknown stop option: $1"
        ;;
    esac
  done

  [[ -n "$session_dir" ]] || fatal "stop requires --session-dir"
  [[ -d "$session_dir" ]] || fatal "stop session-dir missing: $session_dir"
  validate_phase "$phase" || fatal "invalid stop phase: $phase"

  if [[ -f "${session_dir}/observer.pid" ]]; then
    local pid
    pid=$(cat "${session_dir}/observer.pid")
    if kill -0 "$pid" >/dev/null 2>&1; then
      pid_matches_observer "$pid" "$session_dir" || fatal "refusing to signal PID not owned by this observer session"
      record_marker "$session_dir" "$phase"
      kill "$pid" 2>/dev/null || true
      local waited=0
      while kill -0 "$pid" >/dev/null 2>&1; do
        if (( waited >= 20 )); then
          fatal "observer did not stop cleanly; refusing SIGKILL and concurrent manifest finalization"
        fi
        sleep 1
        waited=$((waited + 1))
      done
    fi
  fi

  # In case stop is called after a clean exit.
  if [[ -f "${session_dir}/manifest.json" ]]; then
    echo "SESSION_DIR=${session_dir}"
    echo "MANIFEST=${session_dir}/manifest.json"
    cat "${session_dir}/manifest.hash"
    return 0
  fi

  # Ensure manifest exists if daemon was not able to emit on its own.
  finalize_manifest "$session_dir"
  echo "SESSION_DIR=${session_dir}"
  echo "MANIFEST=${session_dir}/manifest.json"
  cat "${session_dir}/manifest.hash"
}

case ${1:-} in
  start)
    shift
    cmd_start "$@"
    ;;
  mark)
    shift
    cmd_mark "$@"
    ;;
  stop)
    shift
    cmd_stop "$@"
    ;;
  status)
    shift
    cmd_status "$@"
    ;;
  _daemon)
    shift
    daemon_loop "$@"
    ;;
  -h|--help|help|'')
    usage
    exit 0
    ;;
  *)
    fatal "unknown command: $1"
    ;;
esac
