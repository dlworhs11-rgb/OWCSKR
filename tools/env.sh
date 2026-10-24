# Sourced by the tools/*.sh scripts (Linux server): repo root, .env settings, python, log folder.
# .env (repo root, never committed; see .env.example) holds OWCSKR_SITE_DIR, OWCSKR_DISCORD_WEBHOOK, GH_TOKEN, ...
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi
if [ -n "${OWCSKR_PYTHON:-}" ]; then PY="$OWCSKR_PYTHON"
elif [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"
else PY=python3; fi
LOG_DIR="$ROOT/data/live"
mkdir -p "$LOG_DIR"
cd "$ROOT" || exit 1

# detach NAME WORKDIR LOGFILE CMD...: run CMD in the background so it outlives the calling job.
# Under systemd a plain '&' child is killed with the job's cgroup, so it gets its own transient unit.
detach() {
  local name="$1" dir="$2" log="$3"; shift 3
  if command -v systemd-run >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    systemctl --user reset-failed "owcskr-$name.service" >/dev/null 2>&1
    systemd-run --user --quiet --unit "owcskr-$name" --working-directory "$dir" \
      -p "StandardOutput=append:$log" -p "StandardError=append:$log" "$@"
  else
    (cd "$dir" && setsid nohup "$@" >> "$log" 2>&1 < /dev/null &)
  fi
}
