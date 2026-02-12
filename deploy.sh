#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SERVER_HOST="${SERVER_HOST:-192.168.8.233}"
SERVER_USER="${SERVER_USER:-jacob}"
REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR:-/home/jacob/automation}"
LOCAL_PROJECT_DIR="${LOCAL_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

APP_HOST="${APP_HOST:-0.0.0.0}"
APP_PORT="${APP_PORT:-8000}"
APP_MODULE="${APP_MODULE:-app:app}"
SERVICE_NAME="${SERVICE_NAME:-automation.service}"
SERVICE_RUN_AS_USER="${SERVICE_RUN_AS_USER:-$SERVER_USER}"
AUTO_INSTALL_SYSTEMD_SERVICE="${AUTO_INSTALL_SYSTEMD_SERVICE:-1}"
ALLOW_SYSTEMD_USER="${ALLOW_SYSTEMD_USER:-0}"

FORCE_DEPS_SYNC="${FORCE_DEPS_SYNC:-0}"
DEPLOY_RSYNC_COMPRESS="${DEPLOY_RSYNC_COMPRESS:-0}"
HEALTH_RETRIES="${HEALTH_RETRIES:-20}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-0.5}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-2}"

REMOTE_PATH='PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$HOME/.local/bin"'

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

DRY_RUN=0
RUNTIME_MODE="unknown"
UV_PATH=""
DEPS_FINGERPRINT=""
SSH_TARGET=""
CONTROL_PATH=""
SSH_MUX_OPEN=0
declare -a HASH_CMD=()
declare -a SSH_BASE_OPTS=()
declare -a RSYNC_PROGRESS_FLAGS=()

log_info() { echo -e "${YELLOW}$*${NC}"; }
log_ok() { echo -e "${GREEN}$*${NC}"; }
log_err() { echo -e "${RED}$*${NC}" >&2; }

usage() {
  cat <<'EOF'
Usage: ./deploy.sh [--dry-run]

Environment overrides:
  SERVER_HOST              Remote host (default: 192.168.8.233)
  SERVER_USER              Remote user (default: jacob)
  REMOTE_PROJECT_DIR       Remote project path (default: /home/jacob/automation)
  APP_HOST                 App host for fallback runtime (default: 0.0.0.0)
  APP_PORT                 App port for fallback runtime (default: 8000)
  APP_MODULE               Uvicorn app module (default: app:app)
  SERVICE_NAME             systemd service unit (default: automation.service)
  SERVICE_RUN_AS_USER      User account for installed systemd service (default: SERVER_USER)
  AUTO_INSTALL_SYSTEMD_SERVICE 1 auto-installs missing system service (default: 1)
  ALLOW_SYSTEMD_USER       1 allows use of systemd --user service (default: 0)
  FORCE_DEPS_SYNC          1 forces uv sync regardless of lock/hash (default: 0)
  DEPLOY_RSYNC_COMPRESS    1 enables rsync -z compression (default: 0)
  HEALTH_RETRIES           Health check retries (default: 20)
  HEALTH_INTERVAL          Sleep between health retries in seconds (default: 0.5)
  HEALTH_TIMEOUT           Per-request health timeout in seconds (default: 2)
EOF
}

parse_args() {
  while (($#)); do
    case "$1" in
      --dry-run)
        DRY_RUN=1
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        log_err "Unknown argument: $1"
        usage
        exit 1
        ;;
    esac
    shift
  done
}

preflight_local() {
  log_info "Running local preflight checks..."
  command -v ssh >/dev/null 2>&1 || { log_err "Missing required command: ssh"; exit 1; }
  command -v rsync >/dev/null 2>&1 || { log_err "Missing required command: rsync"; exit 1; }

  if rsync --help 2>&1 | grep -q -- '--info'; then
    RSYNC_PROGRESS_FLAGS=(--info=stats2,progress2)
  elif rsync --help 2>&1 | grep -q -- '--progress'; then
    RSYNC_PROGRESS_FLAGS=(--progress)
  else
    RSYNC_PROGRESS_FLAGS=()
  fi

  if command -v sha256sum >/dev/null 2>&1; then
    HASH_CMD=(sha256sum)
  elif command -v shasum >/dev/null 2>&1; then
    HASH_CMD=(shasum -a 256)
  else
    log_err "Missing hash tool: sha256sum or shasum is required"
    exit 1
  fi

  [[ -f "$LOCAL_PROJECT_DIR/pyproject.toml" ]] || {
    log_err "Missing $LOCAL_PROJECT_DIR/pyproject.toml"
    exit 1
  }
  [[ -f "$LOCAL_PROJECT_DIR/uv.lock" ]] || {
    log_err "Missing $LOCAL_PROJECT_DIR/uv.lock"
    exit 1
  }
}

setup_ssh() {
  SSH_TARGET="${SERVER_USER}@${SERVER_HOST}"
  CONTROL_PATH="${TMPDIR:-/tmp}/automation-deploy-${USER:-user}-$$.sock"
  SSH_BASE_OPTS=(
    -o BatchMode=yes
    -o ControlMaster=auto
    -o "ControlPath=$CONTROL_PATH"
    -o ControlPersist=600
    -o ServerAliveInterval=30
    -o ServerAliveCountMax=3
  )
}

open_ssh_mux() {
  if [[ "$DRY_RUN" == "1" ]]; then
    log_info "[dry-run] Skipping SSH control master open"
    return
  fi
  log_info "Opening SSH control connection..."
  ssh "${SSH_BASE_OPTS[@]}" -fN "$SSH_TARGET"
  SSH_MUX_OPEN=1
}

close_ssh_mux() {
  if [[ "$DRY_RUN" == "1" ]]; then
    return
  fi
  if [[ "$SSH_MUX_OPEN" == "1" ]]; then
    ssh "${SSH_BASE_OPTS[@]}" -O exit "$SSH_TARGET" >/dev/null 2>&1 || true
  fi
  rm -f "$CONTROL_PATH" >/dev/null 2>&1 || true
}

cleanup() {
  close_ssh_mux
}

remote_run() {
  local script="$1"
  if [[ "$DRY_RUN" == "1" ]]; then
    log_info "[dry-run] Remote script:"
    printf '%s\n' "$script"
    return 0
  fi
  ssh "${SSH_BASE_OPTS[@]}" -T "$SSH_TARGET" "$REMOTE_PATH bash -se" <<<"$script"
}

remote_capture() {
  local script="$1"
  if [[ "$DRY_RUN" == "1" ]]; then
    log_info "[dry-run] Remote capture script:"
    printf '%s\n' "$script"
    printf '__dry_run__\n'
    return 0
  fi
  ssh "${SSH_BASE_OPTS[@]}" -T "$SSH_TARGET" "$REMOTE_PATH bash -se" <<<"$script"
}

compute_deps_fingerprint() {
  DEPS_FINGERPRINT="$(
    cat "$LOCAL_PROJECT_DIR/pyproject.toml" "$LOCAL_PROJECT_DIR/uv.lock" \
      | "${HASH_CMD[@]}" \
      | awk '{print $1}'
  )"
}

ensure_remote_dir() {
  local remote_project_dir_q
  remote_project_dir_q=$(printf '%q' "$REMOTE_PROJECT_DIR")
  remote_run "
set -Eeuo pipefail
REMOTE_PROJECT_DIR=$remote_project_dir_q
mkdir -p \"\$REMOTE_PROJECT_DIR\"
"
}

sync_code() {
  log_info "Syncing code to remote..."
  local rsync_ssh_cmd="ssh"
  local opt
  for opt in "${SSH_BASE_OPTS[@]}"; do
    rsync_ssh_cmd+=" $(printf '%q' "$opt")"
  done

  local -a cmd=(
    rsync
    -a
    --delete
    --exclude=.git
    --exclude=.venv
    --exclude=__pycache__
    --exclude='*.pyc'
    --exclude=uvicorn.log
    --exclude=uvicorn.log.1
    --exclude=app.pid
    --exclude=.deploy/
  )
  cmd+=("${RSYNC_PROGRESS_FLAGS[@]}")
  if [[ "$DEPLOY_RSYNC_COMPRESS" == "1" ]]; then
    cmd+=(-z)
  fi
  cmd+=(-e "$rsync_ssh_cmd")
  cmd+=("$LOCAL_PROJECT_DIR/" "$SSH_TARGET:$REMOTE_PROJECT_DIR/")

  if [[ "$DRY_RUN" == "1" ]]; then
    log_info "[dry-run] rsync command:"
    printf '%q ' "${cmd[@]}"
    printf '\n'
    return 0
  fi

  "${cmd[@]}"
  log_ok "Code sync completed."
}

detect_uv_path() {
  if [[ "$DRY_RUN" == "1" ]]; then
    UV_PATH="uv"
    log_info "[dry-run] UV_PATH=$UV_PATH"
    return 0
  fi
  log_info "Detecting remote uv binary..."
  UV_PATH="$(
    remote_capture '
set -Eeuo pipefail
if command -v uv >/dev/null 2>&1; then
  command -v uv
  exit 0
fi
for candidate in "$HOME/.local/bin/uv" "/usr/local/bin/uv" "/usr/bin/uv"; do
  if [ -x "$candidate" ]; then
    echo "$candidate"
    exit 0
  fi
done
echo "uv not found on remote host" >&2
exit 1
'
  )"
  if [[ -z "$UV_PATH" ]]; then
    log_err "Failed to detect remote uv binary."
    exit 1
  fi
  log_ok "Using remote uv: $UV_PATH"
}

sync_dependencies_if_needed() {
  log_info "Checking dependency fingerprint..."
  compute_deps_fingerprint
  log_info "Local deps fingerprint: $DEPS_FINGERPRINT"

  local remote_project_dir_q uv_path_q deps_fp_q force_deps_sync_q
  remote_project_dir_q=$(printf '%q' "$REMOTE_PROJECT_DIR")
  uv_path_q=$(printf '%q' "$UV_PATH")
  deps_fp_q=$(printf '%q' "$DEPS_FINGERPRINT")
  force_deps_sync_q=$(printf '%q' "$FORCE_DEPS_SYNC")

  local output
  output="$(
    remote_capture "
set -Eeuo pipefail
REMOTE_PROJECT_DIR=$remote_project_dir_q
UV_PATH=$uv_path_q
DEPS_FINGERPRINT=$deps_fp_q
FORCE_DEPS_SYNC=$force_deps_sync_q
DEPLOY_META_DIR=\"\$REMOTE_PROJECT_DIR/.deploy\"
DEPS_FP_FILE=\"\$DEPLOY_META_DIR/deps.fingerprint\"
mkdir -p \"\$DEPLOY_META_DIR\"
REMOTE_FINGERPRINT=\"\"
if [ -f \"\$DEPS_FP_FILE\" ]; then
  REMOTE_FINGERPRINT=\$(cat \"\$DEPS_FP_FILE\")
fi
if [ \"\$FORCE_DEPS_SYNC\" = \"1\" ] || [ \"\$REMOTE_FINGERPRINT\" != \"\$DEPS_FINGERPRINT\" ]; then
  cd \"\$REMOTE_PROJECT_DIR\"
  \"\$UV_PATH\" sync --frozen
  printf '%s' \"\$DEPS_FINGERPRINT\" > \"\$DEPS_FP_FILE\"
  echo '__DEPS_STATUS__:ran'
else
  echo '__DEPS_STATUS__:skipped'
fi
"
  )"
  printf '%s\n' "$output" | sed '/^__DEPS_STATUS__:/d'

  local deps_status
  deps_status=$(printf '%s\n' "$output" | awk -F: '/^__DEPS_STATUS__:/ {print $2}' | tail -n 1)
  case "$deps_status" in
    ran)
      log_ok "Dependencies synced (fingerprint changed or forced)."
      ;;
    skipped)
      log_ok "Dependencies unchanged. Skipped uv sync."
      ;;
    __dry_run__)
      log_info "[dry-run] Dependency sync decision deferred to runtime."
      ;;
    *)
      log_err "Unexpected dependency sync status: ${deps_status:-<empty>}"
      exit 1
      ;;
  esac
}

restart_service_or_fallback() {
  log_info "Restarting application (systemd-first with fallback)..."

  local remote_project_dir_q uv_path_q app_host_q app_port_q app_module_q service_name_q allow_systemd_user_q service_run_as_user_q auto_install_systemd_service_q
  remote_project_dir_q=$(printf '%q' "$REMOTE_PROJECT_DIR")
  uv_path_q=$(printf '%q' "$UV_PATH")
  app_host_q=$(printf '%q' "$APP_HOST")
  app_port_q=$(printf '%q' "$APP_PORT")
  app_module_q=$(printf '%q' "$APP_MODULE")
  service_name_q=$(printf '%q' "$SERVICE_NAME")
  service_run_as_user_q=$(printf '%q' "$SERVICE_RUN_AS_USER")
  auto_install_systemd_service_q=$(printf '%q' "$AUTO_INSTALL_SYSTEMD_SERVICE")
  allow_systemd_user_q=$(printf '%q' "$ALLOW_SYSTEMD_USER")

  local output
  output="$(
    remote_capture "
set -Eeuo pipefail
REMOTE_PROJECT_DIR=$remote_project_dir_q
UV_PATH=$uv_path_q
APP_HOST=$app_host_q
APP_PORT=$app_port_q
APP_MODULE=$app_module_q
SERVICE_NAME=$service_name_q
SERVICE_RUN_AS_USER=$service_run_as_user_q
AUTO_INSTALL_SYSTEMD_SERVICE=$auto_install_systemd_service_q
ALLOW_SYSTEMD_USER=$allow_systemd_user_q
STRICT_PATTERN=\"uv run uvicorn \$APP_MODULE --host \$APP_HOST --port \$APP_PORT\"
APP_PATTERN=\"uvicorn \$APP_MODULE --host \$APP_HOST --port \$APP_PORT\"

check_port_listening() {
  if command -v ss >/dev/null 2>&1; then
    ss -ltn | awk 'NR>1 {print \$4}' | grep -Eq \"[:.]\${APP_PORT}\$\"
    return \$?
  fi
  if command -v netstat >/dev/null 2>&1; then
    netstat -ltn 2>/dev/null | awk 'NR>2 {print \$4}' | grep -Eq \"[:.]\${APP_PORT}\$\"
    return \$?
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:\"\$APP_PORT\" -sTCP:LISTEN >/dev/null 2>&1
    return \$?
  fi
  return 1
}

kill_matching() {
  local pattern=\"\$1\"
  local signal=\"\${2:-TERM}\"
  local pids
  pids=\$(pgrep -f \"\$pattern\" || true)
  if [ -n \"\$pids\" ]; then
    while IFS= read -r pid; do
      [ -n \"\$pid\" ] && kill -s \"\$signal\" \"\$pid\" 2>/dev/null || true
    done <<< \"\$pids\"
  fi
}

systemctl_system() {
  if systemctl \"\$@\"; then
    return 0
  fi
  if [ \"\$(id -u)\" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
    sudo -n systemctl \"\$@\"
    return \$?
  fi
  return 1
}

install_system_service() {
  local unit_path tmp_unit
  unit_path=\"/etc/systemd/system/\$SERVICE_NAME\"
  tmp_unit=\$(mktemp)
  cat > \"\$tmp_unit\" <<UNIT
[Unit]
Description=Automation FastAPI Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=\$REMOTE_PROJECT_DIR
ExecStart=/usr/bin/env \$UV_PATH run uvicorn \$APP_MODULE --host \$APP_HOST --port \$APP_PORT
User=\$SERVICE_RUN_AS_USER
Restart=on-failure
Environment=PYTHONUNBUFFERED=1
StandardOutput=append:\$REMOTE_PROJECT_DIR/uvicorn.log
StandardError=append:\$REMOTE_PROJECT_DIR/uvicorn.log

[Install]
WantedBy=multi-user.target
UNIT

  if [ \"\$(id -u)\" -eq 0 ]; then
    install -m 0644 \"\$tmp_unit\" \"\$unit_path\"
    systemctl daemon-reload
    systemctl enable \"\$SERVICE_NAME\"
  elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo -n install -m 0644 \"\$tmp_unit\" \"\$unit_path\"
    sudo -n systemctl daemon-reload
    sudo -n systemctl enable \"\$SERVICE_NAME\"
  else
    rm -f \"\$tmp_unit\"
    echo \"Service \$SERVICE_NAME is missing and cannot be auto-installed (passwordless sudo required).\" >&2
    return 1
  fi

  rm -f \"\$tmp_unit\"
  return 0
}

if command -v systemctl >/dev/null 2>&1; then
  if [ \"\$ALLOW_SYSTEMD_USER\" != \"1\" ] && systemctl --user cat \"\$SERVICE_NAME\" >/dev/null 2>&1; then
    echo \"Disabling user service \$SERVICE_NAME because ALLOW_SYSTEMD_USER=0.\" >&2
    systemctl --user disable --now \"\$SERVICE_NAME\" >/dev/null 2>&1 || true
  fi

  if ! systemctl_system cat \"\$SERVICE_NAME\" >/dev/null 2>&1; then
    if [ \"\$AUTO_INSTALL_SYSTEMD_SERVICE\" = \"1\" ]; then
      echo \"System service \$SERVICE_NAME not found. Attempting auto-install...\" >&2
      if install_system_service; then
        echo \"Installed system service \$SERVICE_NAME\" >&2
      else
        echo \"Auto-install failed; falling back to non-systemd startup path.\" >&2
      fi
    else
      echo \"System service \$SERVICE_NAME not found and auto-install is disabled.\" >&2
    fi
  fi

  if systemctl_system cat \"\$SERVICE_NAME\" >/dev/null 2>&1; then
    if systemctl_system restart \"\$SERVICE_NAME\"; then
      systemctl_system is-active --quiet \"\$SERVICE_NAME\"
      echo '__RUNTIME_MODE__:systemd-system'
      exit 0
    fi
    echo \"systemd restart failed for \$SERVICE_NAME; falling back to nohup\" >&2
  fi

  if [ \"\$ALLOW_SYSTEMD_USER\" = \"1\" ] && systemctl --user cat \"\$SERVICE_NAME\" >/dev/null 2>&1; then
    if command -v loginctl >/dev/null 2>&1; then
      linger=\$(loginctl show-user \"\$USER\" -p Linger --value 2>/dev/null || echo unknown)
      if [ \"\$linger\" != \"yes\" ]; then
        echo \"User service \$SERVICE_NAME detected but linger is '\$linger'; skipping --user mode to avoid post-SSH shutdown.\" >&2
      else
        systemctl --user restart \"\$SERVICE_NAME\"
        systemctl --user is-active --quiet \"\$SERVICE_NAME\"
        echo '__RUNTIME_MODE__:systemd-user'
        exit 0
      fi
    else
      echo \"loginctl not available; skipping --user systemd mode for safety.\" >&2
    fi
  fi
fi

cd \"\$REMOTE_PROJECT_DIR\"
if [ -f app.pid ]; then
  PID=\$(cat app.pid || true)
  if [ -n \"\$PID\" ] && kill -0 \"\$PID\" 2>/dev/null; then
    kill \"\$PID\"
    for i in \$(seq 1 20); do
      kill -0 \"\$PID\" 2>/dev/null || break
      sleep 0.25
    done
    kill -9 \"\$PID\" 2>/dev/null || true
  fi
  rm -f app.pid
fi

kill_matching \"\$STRICT_PATTERN\" TERM
kill_matching \"\$APP_PATTERN\" TERM

for i in \$(seq 1 40); do
  if ! check_port_listening; then
    break
  fi
  sleep 0.25
done

if check_port_listening; then
  kill_matching \"\$STRICT_PATTERN\" KILL
  kill_matching \"\$APP_PATTERN\" KILL
  sleep 1
fi

if check_port_listening; then
  echo \"Port \$APP_PORT is still in use after shutdown attempts\" >&2
  exit 1
fi

[ -f uvicorn.log ] && mv -f uvicorn.log uvicorn.log.1 || true
if [ -x \"\$REMOTE_PROJECT_DIR/.venv/bin/uvicorn\" ]; then
  nohup \"\$REMOTE_PROJECT_DIR/.venv/bin/uvicorn\" \"\$APP_MODULE\" --host \"\$APP_HOST\" --port \"\$APP_PORT\" \
    > uvicorn.log 2>&1 < /dev/null &
else
  nohup \"\$UV_PATH\" run uvicorn \"\$APP_MODULE\" --host \"\$APP_HOST\" --port \"\$APP_PORT\" \
    > uvicorn.log 2>&1 < /dev/null &
fi
NEW_PID=\$!
echo \$NEW_PID > app.pid

for i in \$(seq 1 40); do
  if ! kill -0 \"\$NEW_PID\" 2>/dev/null; then
    echo \"New process exited before becoming ready (pid=\$NEW_PID)\" >&2
    tail -n 60 uvicorn.log 2>/dev/null || true
    exit 1
  fi
  if check_port_listening; then
    echo '__RUNTIME_MODE__:fallback'
    exit 0
  fi
  sleep 0.25
done
echo 'Fallback runtime did not start listening in time' >&2
tail -n 60 uvicorn.log 2>/dev/null || true
exit 1
"
  )"
  printf '%s\n' "$output" | sed '/^__RUNTIME_MODE__:/d'

  RUNTIME_MODE=$(printf '%s\n' "$output" | awk -F: '/^__RUNTIME_MODE__:/ {print $2}' | tail -n 1)
  case "$RUNTIME_MODE" in
    systemd-user|systemd-system|fallback)
      log_ok "Runtime mode: $RUNTIME_MODE"
      ;;
    __dry_run__)
      RUNTIME_MODE="dry-run"
      log_info "[dry-run] Runtime mode deferred to execution time."
      ;;
    *)
      log_err "Unexpected runtime mode result: ${RUNTIME_MODE:-<empty>}"
      exit 1
      ;;
  esac
}

print_remote_diagnostics() {
  local service_name_q remote_project_dir_q runtime_mode_q
  service_name_q=$(printf '%q' "$SERVICE_NAME")
  remote_project_dir_q=$(printf '%q' "$REMOTE_PROJECT_DIR")
  runtime_mode_q=$(printf '%q' "$RUNTIME_MODE")

  remote_run "
set +e
SERVICE_NAME=$service_name_q
REMOTE_PROJECT_DIR=$remote_project_dir_q
RUNTIME_MODE=$runtime_mode_q

echo '--- Remote diagnostics ---'
if [ \"\$RUNTIME_MODE\" = 'systemd-user' ]; then
  systemctl --user status \"\$SERVICE_NAME\" --no-pager || true
  journalctl --user -u \"\$SERVICE_NAME\" -n 60 --no-pager || true
elif [ \"\$RUNTIME_MODE\" = 'systemd-system' ]; then
  systemctl status \"\$SERVICE_NAME\" --no-pager || true
  journalctl -u \"\$SERVICE_NAME\" -n 60 --no-pager || true
else
  tail -n 80 \"\$REMOTE_PROJECT_DIR/uvicorn.log\" 2>/dev/null || true
  [ -f \"\$REMOTE_PROJECT_DIR/app.pid\" ] && echo \"app.pid=\$(cat \"\$REMOTE_PROJECT_DIR/app.pid\")\" || true
fi
echo '--- End diagnostics ---'
"
}

verify_health() {
  if [[ "$DRY_RUN" == "1" ]]; then
    log_info "[dry-run] Skipping actual remote health verification."
    return 0
  fi
  log_info "Running health check..."
  local app_port_q retries_q interval_q timeout_q runtime_mode_q service_name_q
  app_port_q=$(printf '%q' "$APP_PORT")
  retries_q=$(printf '%q' "$HEALTH_RETRIES")
  interval_q=$(printf '%q' "$HEALTH_INTERVAL")
  timeout_q=$(printf '%q' "$HEALTH_TIMEOUT")
  runtime_mode_q=$(printf '%q' "$RUNTIME_MODE")
  service_name_q=$(printf '%q' "$SERVICE_NAME")

  if ! remote_run "
set -Eeuo pipefail
APP_PORT=$app_port_q
HEALTH_RETRIES=$retries_q
HEALTH_INTERVAL=$interval_q
HEALTH_TIMEOUT=$timeout_q
RUNTIME_MODE=$runtime_mode_q
SERVICE_NAME=$service_name_q

if [ \"\$RUNTIME_MODE\" = 'systemd-user' ]; then
  systemctl --user is-active --quiet \"\$SERVICE_NAME\"
elif [ \"\$RUNTIME_MODE\" = 'systemd-system' ]; then
  systemctl is-active --quiet \"\$SERVICE_NAME\"
fi

for i in \$(seq 1 \"\$HEALTH_RETRIES\"); do
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS --max-time \"\$HEALTH_TIMEOUT\" \"http://localhost:\$APP_PORT/health\" >/dev/null; then
      exit 0
    fi
  else
    echo 'curl is required on remote host for health checks' >&2
    exit 1
  fi
  sleep \"\$HEALTH_INTERVAL\"
done
echo 'Health check failed' >&2
exit 1
"; then
    log_err "Remote health verification failed."
    print_remote_diagnostics
    exit 1
  fi
  log_ok "Health check passed."
}

verify_fallback_survives_disconnect() {
  if [[ "$DRY_RUN" == "1" ]]; then
    log_info "[dry-run] Skipping fallback disconnect-survival check."
    return 0
  fi
  if [[ "$RUNTIME_MODE" != "fallback" ]]; then
    return 0
  fi

  log_info "Verifying fallback runtime survives SSH disconnect..."
  close_ssh_mux
  SSH_MUX_OPEN=0
  sleep 1
  open_ssh_mux

  local app_port_q remote_project_dir_q
  app_port_q=$(printf '%q' "$APP_PORT")
  remote_project_dir_q=$(printf '%q' "$REMOTE_PROJECT_DIR")

  if ! remote_run "
set -Eeuo pipefail
APP_PORT=$app_port_q
REMOTE_PROJECT_DIR=$remote_project_dir_q
PID=\$(cat \"\$REMOTE_PROJECT_DIR/app.pid\" 2>/dev/null || true)
[ -n \"\$PID\" ] && kill -0 \"\$PID\"
curl -fsS --max-time 3 \"http://localhost:\$APP_PORT/health\" >/dev/null
"; then
    log_err "Fallback process did not survive SSH disconnect."
    print_remote_diagnostics
    log_err "Install/enable a system service ($SERVICE_NAME) or fix host policy that kills session processes on logout."
    exit 1
  fi

  log_ok "Fallback runtime survived SSH disconnect."
}

main() {
  parse_args "$@"
  preflight_local
  setup_ssh
  trap cleanup EXIT INT TERM

  log_info "Starting deployment to $SSH_TARGET"
  open_ssh_mux
  ensure_remote_dir
  sync_code
  detect_uv_path
  sync_dependencies_if_needed
  restart_service_or_fallback
  verify_health
  verify_fallback_survives_disconnect

  log_ok "Deployment completed successfully."
  echo -e "${YELLOW}Useful commands:${NC}"
  if [[ "$RUNTIME_MODE" == "systemd-user" ]]; then
    echo -e "  Logs:   ssh $SSH_TARGET 'journalctl --user -u $SERVICE_NAME -f'"
    echo -e "  Status: ssh $SSH_TARGET 'systemctl --user status $SERVICE_NAME'"
  elif [[ "$RUNTIME_MODE" == "systemd-system" ]]; then
    echo -e "  Logs:   ssh $SSH_TARGET 'journalctl -u $SERVICE_NAME -f'"
    echo -e "  Status: ssh $SSH_TARGET 'systemctl status $SERVICE_NAME'"
  else
    echo -e "  Logs:   ssh $SSH_TARGET 'tail -f $REMOTE_PROJECT_DIR/uvicorn.log'"
    echo -e "  Stop:   ssh $SSH_TARGET 'cd $REMOTE_PROJECT_DIR && [ -f app.pid ] && kill \$(cat app.pid)'"
  fi
}

main "$@"
