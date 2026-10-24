#!/usr/bin/env bash
# Daily job (systemd user timer owcskr-daily, 09:00 KST): refresh Liquipedia, rebuild data, schedule the captures.
set -u
. "$(dirname "$0")/env.sh"
LOG="$LOG_DIR/daily.log"
echo "=== $(date '+%F %T') daily" >> "$LOG"
node collector/run-lp.mjs --active-only >> "$LOG" 2>&1
node collector/build.mjs >> "$LOG" 2>&1
"$PY" -I tools/republish_recent.py >> "$LOG" 2>&1
"$PY" -I tools/schedule_today.py --upcoming >> "$LOG" 2>&1
# PC-only site files (recorders, admin, handover notes) to the private repo owcs-kr-recorders; skips when unchanged
if [ -n "${OWCSKR_RECORDERS_DIR:-}" ] && [ -f "$OWCSKR_RECORDERS_DIR/backup.py" ]; then
  "$PY" -I "$OWCSKR_RECORDERS_DIR/backup.py" >> "$LOG" 2>&1
fi
# SOOP timestamp comments the night run missed (machine off, replay uploaded late)
if [ -n "${OWCSKR_SITE_DIR:-}" ] && [ -f "$OWCSKR_SITE_DIR/replay_comment.py" ]; then
  (cd "$OWCSKR_SITE_DIR" && "$PY" -X utf8 replay_comment.py --post >> "$LOG" 2>&1)
fi
