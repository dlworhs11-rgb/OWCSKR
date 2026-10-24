#!/usr/bin/env bash
# Runs the capture for one broadcast day. Started by the systemd user units owcskr-live-YYYY-MM-DD (schedule_today.py),
# which restart it after a crash (Restart=on-failure).
# args: HOURS DATE [URL]   (URL only for tests; default = live embed of owesports)
# The first start of a day fixes the end time (now + HOURS) in data/live/<DATE>/until.txt; a restart reuses it, so
# restarting never extends the day. A start after that time only finishes a day whose summary never went out
# (a crash near the end), then exits. A day with data/live/<DATE>/summary.txt is finished: a start exits at once.
# Exit: 0 ok / day finished or over / already running, 1 capture failed (systemd restarts it), 2 bad arguments or the
# capture's self-check failed, 4 capture ended but its final OCR / publish failed, 78 bad .env (env.sh) (2, 4 and 78
# are not restarted: RestartPreventExitStatus=2 4 78; a unit that fails for good alerts through OnFailure=).
# Every exit 1, 2 and 4 alerts here first (bad arguments too): tools/notify.py --unit-failed skips those codes.
set -u
. "$(dirname "$0")/env.sh"
# bad_args MESSAGE: exit 2 (a restart would not help) with an alert, since OnFailure= stays quiet for exit 2
bad_args() {
  echo "run_live.sh: $1" >&2
  notify "OWCSKR 캡처 시작 실패" "run_live.sh: $1 - 캡처를 시작하지 않음 (재시작 안 함)"
  exit 2
}
if [ $# -lt 2 ]; then bad_args "usage: run_live.sh HOURS DATE [URL], got $# argument(s): $*"; fi
HOURS="$1"; DAY="$2"; URL="${3:-}"
if ! [[ "$DAY" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then bad_args "DATE must be YYYY-MM-DD, got '$DAY'"; fi
LOG="$LOG_DIR/task.log"
DAYDIR="$LOG_DIR/$DAY"
mkdir -p "$DAYDIR"
log() { echo "$(date '+%F %T') run_live $DAY: $*" >> "$LOG"; }

# one capture per day: a second start (timer + a hand re-run, two daily runs) leaves the first one alone.
# Children get '9>&-' so a leftover recorder or Xvfb cannot keep holding the lock.
exec 9>"$DAYDIR/live.lock"
if command -v flock >/dev/null 2>&1; then
  if ! flock -n 9; then log "already running - not started twice"; exit 0; fi
else
  log "flock not installed - no lock"
fi
# a restart or a reboot after the summary went out must not capture the finished day again
if [ -f "$DAYDIR/summary.txt" ]; then log "day already finished (summary sent) - nothing to do"; exit 0; fi

UNTIL="$("$PY" -I tools/platform_util.py live-until "$HOURS" "$DAY" 2>>"$LOG")"; rc=$?
if [ "$rc" = 3 ]; then
  # a crashed run leaves the summary to its successor; past the end time that is this start: live_capture.py with an
  # end in the past only does the final OCR / publish / summary
  if [ -d "$DAYDIR/frames" ]; then
    log "day over (until $UNTIL), no summary yet - final OCR / publish / summary only"
    "$PY" -I tools/live_capture.py --until "$UNTIL" --date "$DAY" >> "$LOG" 2>&1 9>&-
    log "final pass exit $?"
  else
    log "day over (until $UNTIL) - nothing to do"
  fi
  exit 0
fi
if [ "$rc" != 0 ] || [ -z "$UNTIL" ]; then
  log "could not work out the end time (live-until exit $rc)"
  notify "OWCSKR 캡처 시작 실패 $DAY" "run_live.sh: 종료 시각을 못 정함 (platform_util live-until exit $rc). $LOG 확인"
  exit 2
fi
log "start (hours $HOURS, until $UNTIL)"
hc_ping "${OWCSKR_HC_LIVE:+$OWCSKR_HC_LIVE/start}"

# alerts of a crash loop (a restart every minute) at most every 30 minutes
alert() {
  local stamp="$DAYDIR/last_alert"
  if [ -n "$(find "$stamp" -mmin -30 2>/dev/null)" ]; then log "alert suppressed (one sent < 30 min ago)"; return 0; fi
  touch "$stamp"
  notify "$1" "$2"
}

FAILS=""
# the site recorders (score / bans / first comps / push) start with the capture, so no match day is missed
WOUT="$(bash tools/start_watchers.sh 9>&- 2>&1)"; wrc=$?
printf '%s\n' "$WOUT" >> "$LOG"
if [ "$wrc" != 0 ]; then FAILS+="start_watchers (exit $wrc):"$'\n'"$(printf '%s\n' "$WOUT" | tail -n 15)"$'\n'; fi

# OBS needs an X display: on a headless server a virtual one. Xvfb is started here, not through xvfb-run: that sh
# script has no TERM trap, so on 'systemctl stop' it died at once and handed us 143 while python was still publishing.
XPID=""
start_xvfb() {
  local n i
  for n in 99 98 97 96 95 94 93 92 91 90; do
    if [ -e "/tmp/.X$n-lock" ] || [ -e "/tmp/.X11-unix/X$n" ]; then continue; fi
    Xvfb ":$n" -screen 0 1920x1080x24 -nolisten tcp >> "$DAYDIR/xvfb.log" 2>&1 9>&- &
    XPID=$!
    for i in 1 2 3 4 5 6 7 8 9 10; do
      if [ -e "/tmp/.X11-unix/X$n" ]; then export DISPLAY=":$n"; return 0; fi
      kill -0 "$XPID" 2>/dev/null || break
      sleep 1
    done
    kill "$XPID" 2>/dev/null; wait "$XPID" 2>/dev/null; XPID=""
  done
  return 1
}
# OWCSKR_FRAME_SOURCE=hls: live_capture.py reads the SOOP stream with yt-dlp + ffmpeg, no OBS, so no display either
SOURCE="$(printf '%s' "${OWCSKR_FRAME_SOURCE:-obs}" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')"
if [ "$SOURCE" = hls ]; then
  log "frame source hls - no Xvfb"
elif [ -z "${DISPLAY:-}" ] && command -v Xvfb >/dev/null 2>&1; then
  if start_xvfb; then log "Xvfb on $DISPLAY"; else log "Xvfb did not start (see $DAYDIR/xvfb.log) - no display"; fi
fi
ARGS=(--until "$UNTIL" --date "$DAY")
if [ -n "$URL" ]; then ARGS+=(--url "$URL"); fi
# systemctl stop / RuntimeMaxSec / shutdown send SIGTERM to the whole unit: live_capture.py then does its last OCR and
# publish. python is our direct child, and with this trap bash waits for it (instead of dying at once) and still
# sends the result ping below.
STOPPED=""
trap 'STOPPED=1' TERM INT HUP
"$PY" -I tools/live_capture.py "${ARGS[@]}" >> "$LOG" 2>&1 9>&-
crc=$?
trap - TERM INT HUP
if [ -n "$XPID" ]; then kill "$XPID" 2>/dev/null; wait "$XPID" 2>/dev/null; fi
log "live_capture exit $crc${STOPPED:+ (stopped by a signal)}"
if [ "$crc" != 0 ]; then
  why="live_capture.py exit $crc"
  if [ "$crc" = 2 ]; then why="$why (시작 점검 실패 - 재시작 안 함)"; fi
  if [ "$crc" = 4 ]; then why="$why (캡처는 끝났고 마지막 판독·발행 실패 - 재시작 안 함)"; fi
  FAILS+="$why:"$'\n'"$(tail -n 20 "$LOG")"$'\n'
fi

if [ -n "$FAILS" ]; then
  alert "OWCSKR 캡처 문제 $DAY" "$FAILS"
  hc_ping "${OWCSKR_HC_LIVE:+$OWCSKR_HC_LIVE/fail}" "$FAILS"
else
  hc_ping "${OWCSKR_HC_LIVE:-}"
fi

# broadcast over: SOOP timestamp comment as soon as the replay is up (checks every 5 min, up to 6 h; detached so
# this job can end). Only after the capture ended (0, or 4: ended, publish failed): a crashed capture is restarted,
# and the daily job's 'replay_comment.py --post' catches any day this misses. replay_comment.py lives with the site
# files. OWCSKR_PUBLISH=0 (shadow run): no comment, the machine that publishes posts it.
if [ "$crc" = 0 ] || [ "$crc" = 4 ]; then
  site_dir_state; sd=$?
  if ! publish_on; then
    log "publish off (OWCSKR_PUBLISH=0) - replay comment not posted"
  elif [ "$sd" = 0 ] && [ -f "$OWCSKR_SITE_DIR/replay_comment.py" ]; then
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
