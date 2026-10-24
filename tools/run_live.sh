#!/usr/bin/env bash
# Runs the capture for one broadcast day. Started by the systemd user timers owcskr-live-YYYY-MM-DD (schedule_today.py).
# args: HOURS DATE [URL]   (URL only for tests; default = live embed of owesports)
set -u
. "$(dirname "$0")/env.sh"
if [ $# -lt 2 ]; then echo "usage: $0 HOURS DATE [URL]" >&2; exit 2; fi
# the site recorders (score / bans / first comps / push) start with the capture, so no match day is missed
bash tools/start_watchers.sh >> "$LOG_DIR/task.log" 2>&1
# OBS needs an X display: on a headless server it runs inside a virtual one
WRAP=()
if [ -z "${DISPLAY:-}" ] && command -v xvfb-run >/dev/null 2>&1; then WRAP=(xvfb-run -a -s "-screen 0 1920x1080x24"); fi
ARGS=(--hours "$1" --date "$2")
if [ -n "${3:-}" ]; then ARGS+=(--url "$3"); fi
"${WRAP[@]}" "$PY" -I tools/live_capture.py "${ARGS[@]}" >> "$LOG_DIR/task.log" 2>&1
# broadcast over: SOOP timestamp comment as soon as the replay is up (checks every 5 min, up to 6 h; detached so
# this job can end). replay_comment.py lives with the site files.
if [ -n "${OWCSKR_SITE_DIR:-}" ] && [ -f "$OWCSKR_SITE_DIR/replay_comment.py" ]; then
  detach "replay-comment-$2" "$OWCSKR_SITE_DIR" "$LOG_DIR/replay_comment.log" "$PY" -X utf8 replay_comment.py --wait "$2"
else
  echo "$(date '+%F %T') replay_comment.py not found (OWCSKR_SITE_DIR='${OWCSKR_SITE_DIR:-}') - skipped" >> "$LOG_DIR/task.log"
fi
