#!/usr/bin/env bash
# Runs the capture for one broadcast day. Started by the systemd user units owcskr-live-YYYY-MM-DD (schedule_today.py),
# which restart it after a crash (Restart=on-failure).
# args: HOURS DATE [URL]   (URL only for tests; default = live embed of owesports)
# The first start of a day fixes the end time (now + HOURS) in data/live/<DATE>/until.txt; a restart reuses it, so
# restarting never extends the day, and a start after that time exits at once.
# Exit: 0 ok / day already over / already running, 1 capture failed (systemd restarts it), 2 bad arguments or the
# capture's self-check failed (not restarted: RestartPreventExitStatus=2).
set -u
. "$(dirname "$0")/env.sh"
if [ $# -lt 2 ]; then echo "usage: $0 HOURS DATE [URL]" >&2; exit 2; fi
HOURS="$1"; DAY="$2"; URL="${3:-}"
if ! [[ "$DAY" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then echo "run_live.sh: DATE must be YYYY-MM-DD, got '$DAY'" >&2; exit 2; fi
LOG="$LOG_DIR/task.log"
mkdir -p "$LOG_DIR/$DAY"
log() { echo "$(date '+%F %T') run_live $DAY: $*" >> "$LOG"; }

# one capture per day: a second start (timer + a hand re-run, two daily runs) leaves the first one alone.
# Children get '9>&-' so a leftover recorder or Xvfb cannot keep holding the lock.
exec 9>"$LOG_DIR/$DAY/live.lock"
if command -v flock >/dev/null 2>&1; then
  if ! flock -n 9; then log "already running - not started twice"; exit 0; fi
else
  log "flock not installed - no lock"
fi

UNTIL="$("$PY" -I tools/platform_util.py live-until "$HOURS" "$DAY" 2>>"$LOG")"; rc=$?
if [ "$rc" = 3 ]; then log "day over (until $UNTIL) - nothing to do"; exit 0; fi
if [ "$rc" != 0 ] || [ -z "$UNTIL" ]; then
  log "could not work out the end time (live-until exit $rc)"
  notify "OWCSKR 캡처 시작 실패 $DAY" "run_live.sh: 종료 시각을 못 정함 (platform_util live-until exit $rc). $LOG 확인"
  exit 2
fi
log "start (hours $HOURS, until $UNTIL)"
hc_ping "${OWCSKR_HC_LIVE:+$OWCSKR_HC_LIVE/start}"

# alerts of a crash loop (a restart every minute) at most every 30 minutes
alert() {
  local stamp="$LOG_DIR/$DAY/last_alert"
  if [ -n "$(find "$stamp" -mmin -30 2>/dev/null)" ]; then log "alert suppressed (one sent < 30 min ago)"; return 0; fi
  touch "$stamp"
  notify "$1" "$2"
}

FAILS=""
# the site recorders (score / bans / first comps / push) start with the capture, so no match day is missed
WOUT="$(bash tools/start_watchers.sh 9>&- 2>&1)"; wrc=$?
printf '%s\n' "$WOUT" >> "$LOG"
if [ "$wrc" != 0 ]; then FAILS+="start_watchers (exit $wrc):"$'\n'"$(printf '%s\n' "$WOUT" | tail -n 15)"$'\n'; fi

# OBS needs an X display: on a headless server it runs inside a virtual one
WRAP=()
if [ -z "${DISPLAY:-}" ] && command -v xvfb-run >/dev/null 2>&1; then WRAP=(xvfb-run -a -s "-screen 0 1920x1080x24"); fi
ARGS=(--until "$UNTIL" --date "$DAY")
if [ -n "$URL" ]; then ARGS+=(--url "$URL"); fi
# systemctl stop / RuntimeMaxSec / shutdown send SIGTERM to the whole unit: live_capture.py then does its last OCR and
# publish. With this trap bash waits for it (instead of dying at once) and still sends the result ping below.
STOPPED=""
trap 'STOPPED=1' TERM INT HUP
${WRAP[@]+"${WRAP[@]}"} "$PY" -I tools/live_capture.py "${ARGS[@]}" >> "$LOG" 2>&1 9>&-
crc=$?
trap - TERM INT HUP
log "live_capture exit $crc${STOPPED:+ (stopped by a signal)}"
if [ "$crc" != 0 ]; then
  why="live_capture.py exit $crc"
  if [ "$crc" = 2 ]; then why="$why (시작 점검 실패 - 재시작 안 함)"; fi
  FAILS+="$why:"$'\n'"$(tail -n 20 "$LOG")"$'\n'
fi

if [ -n "$FAILS" ]; then
  alert "OWCSKR 캡처 문제 $DAY" "$FAILS"
  hc_ping "${OWCSKR_HC_LIVE:+$OWCSKR_HC_LIVE/fail}" "$FAILS"
else
  hc_ping "${OWCSKR_HC_LIVE:-}"
fi

# broadcast over: SOOP timestamp comment as soon as the replay is up (checks every 5 min, up to 6 h; detached so
# this job can end). Only after a clean end: a crashed capture is restarted, and the daily job's
# 'replay_comment.py --post' catches any day this misses. replay_comment.py lives with the site files.
if [ "$crc" = 0 ]; then
  site_dir_state; sd=$?
  if [ "$sd" = 0 ] && [ -f "$OWCSKR_SITE_DIR/replay_comment.py" ]; then
    detach --once "replay-comment-$DAY" "$OWCSKR_SITE_DIR" "$LOG_DIR/replay_comment.log" \
      "$PY" -X utf8 replay_comment.py --wait "$DAY" 9>&- || log "replay_comment.py could not be started"
  elif [ "$sd" = 2 ]; then
    log "OWCSKR_SITE_DIR='$OWCSKR_SITE_DIR' does not exist - replay comment not posted"
    # alert only: a nonzero exit here would make systemd restart a capture that ended fine
    notify "OWCSKR 설정 오류" "OWCSKR_SITE_DIR='$OWCSKR_SITE_DIR' 폴더가 없음: 다시보기 댓글을 못 올림 ($DAY)"
  else
    log "replay_comment.py not on this machine (OWCSKR_SITE_DIR='${OWCSKR_SITE_DIR:-}') - skipped"
  fi
fi
exit "$crc"
