# Sourced by the tools/*.sh scripts (Linux server): repo root, .env settings, python, log folder, helpers.
# .env (repo root, never committed; see .env.example) holds OWCSKR_SITE_DIR, OWCSKR_DISCORD_WEBHOOK, GH_TOKEN, ...
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# .env is read as plain KEY=VALUE lines, never run as shell code: the same file is the EnvironmentFile= of the
# systemd units, and the two must read the same values (tools/platform_util.py parse_env_lines has the same rules).
# A bad file stops the calling script: a half-read .env makes jobs skip things silently.
load_env() {
  local f="$1" line key val n=0 i
  local re_kv='^([A-Za-z_][A-Za-z0-9_]*)=(.*)$' re_dq='^"([^"]*)"$' re_sq="^'([^']*)'\$"
  local keys=() vals=()   # exported only when the whole file is good
  [ -f "$f" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    n=$((n + 1))
    if [[ "$line" == *$'\r'* ]]; then
      echo "env.sh: $f line $n: CRLF line ending - save it with LF (dos2unix .env)" >&2; return 1
    fi
    [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
    if ! [[ "$line" =~ $re_kv ]]; then
      echo "env.sh: $f line $n: not KEY=VALUE (no spaces around =, no 'export')" >&2; return 1
    fi
    key="${BASH_REMATCH[1]}"; val="${BASH_REMATCH[2]}"
    val="${val#"${val%%[![:blank:]]*}"}"; val="${val%"${val##*[![:blank:]]}"}"
    case "$val" in *\\*) echo "env.sh: $f line $n: $key: backslashes are not supported" >&2; return 1 ;; esac
    if [[ "$val" =~ $re_dq ]] || [[ "$val" =~ $re_sq ]]; then val="${BASH_REMATCH[1]}"
    elif [[ "$val" == [\"\']* ]]; then echo "env.sh: $f line $n: $key: unbalanced quote" >&2; return 1
    fi
    keys+=("$key"); vals+=("$val")
  done < "$f"
  for ((i = 0; i < ${#keys[@]}; i++)); do export "${keys[i]}=${vals[i]}"; done
}
load_env "$ROOT/.env" || exit 1

if [ -n "${OWCSKR_PYTHON:-}" ]; then PY="$OWCSKR_PYTHON"
elif [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"
else PY=python3; fi
LOG_DIR="$ROOT/data/live"
mkdir -p "$LOG_DIR"
cd "$ROOT" || exit 1

# notify TITLE BODY: alert a person (Discord webhook / log); never fails the caller
notify() { "$PY" -I "$ROOT/tools/notify.py" "$1" "$2" || true; }

# hc_ping URL [BODY]: healthchecks.io-style ping; an empty URL is skipped and a failed ping never fails the job
hc_ping() {
  [ -n "${1:-}" ] || return 0
  command -v curl >/dev/null 2>&1 || { echo "hc_ping: curl not installed" >&2; return 0; }
  if [ -n "${2:-}" ]; then curl -fsS -m 10 --retry 3 -o /dev/null --data-raw "${2:0:10000}" "$1" || echo "hc_ping: $1 failed" >&2
  else curl -fsS -m 10 --retry 3 -o /dev/null "$1" || echo "hc_ping: $1 failed" >&2; fi
  return 0
}

# site_dir_state: 0 = OWCSKR_SITE_DIR is a folder, 1 = not set (recorders not on this machine), 2 = set but missing
site_dir_state() {
  [ -n "${OWCSKR_SITE_DIR:-}" ] || return 1
  [ -d "$OWCSKR_SITE_DIR" ] || return 2
  return 0
}

have_systemd() { command -v systemd-run >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; }

# unit_busy UNIT: the user unit is running or about to (also between two automatic restarts)
unit_busy() {
  case "$(systemctl --user show -p ActiveState --value "$1" 2>/dev/null)" in
    active|activating|deactivating|reloading) return 0 ;;
  esac
  return 1
}

# capture_running: some day's capture is on (then the daily job must not pull new code under it)
capture_running() {
  if have_systemd; then
    [ -n "$(systemctl --user list-units --state=active,activating --plain --no-legend 'owcskr-live-*.service' 2>/dev/null)" ]
  else
    pgrep -f 'tools/live_capture.py' >/dev/null 2>&1
  fi
}

# detach [--once] NAME WORKDIR LOGFILE CMD...: run CMD in the background so it outlives the calling job.
# Under systemd a plain '&' child is killed with the job's cgroup, so it gets its own transient unit, with the .env
# values (a systemd-run unit gets the user manager's environment, not ours) and restarts after a crash (--once: no
# restart, for one-shot jobs that must not run twice). Returns systemd-run's exit code.
detach() {
  local restart=1
  if [ "$1" = "--once" ]; then restart=0; shift; fi
  local name="$1" dir="$2" log="$3"; shift 3
  if have_systemd; then
    local props=(-p "EnvironmentFile=-$ROOT/.env" -p "StandardOutput=append:$log" -p "StandardError=append:$log")
    if [ "$restart" = 1 ]; then props+=(-p Restart=on-failure -p RestartSec=30 -p StartLimitIntervalSec=0); fi
    systemctl --user reset-failed "owcskr-$name.service" >/dev/null 2>&1
    systemd-run --user --quiet --unit "owcskr-$name" --working-directory "$dir" "${props[@]}" "$@"
  else
    (cd "$dir" && setsid nohup "$@" >> "$log" 2>&1 < /dev/null &)
  fi
}
