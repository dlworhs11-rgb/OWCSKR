#!/usr/bin/env bash
# Daily job (systemd user timer owcskr-daily: 09:00 KST and 3 min after each boot): update the code, find new
# Liquipedia pages, refresh Liquipedia, rebuild data, schedule the captures, check that the site is fresh.
# Every step runs even when an earlier one failed; the failures are sent as one alert at the end.
# Exit 1 when a step failed (warnings alone - some Liquipedia pages, git pull/push, the freshness check - only alert).
# Healthcheck ping: $OWCSKR_HC_DAILY on success, $OWCSKR_HC_DAILY/fail on failure.
set -u
. "$(dirname "$0")/env.sh"
LOG="$LOG_DIR/daily.log"
echo "=== $(date '+%F %T') daily" >> "$LOG"
log() { echo "$(date '+%F %T') daily: $*" >> "$LOG"; }
OUT="$(mktemp)"; trap 'rm -f "$OUT"' EXIT
FAILED=""; WARNED=""; REPORT=""

# record LEVEL WHAT DETAILS
record() {
  if [ "$1" = fail ]; then FAILED+="${FAILED:+, }$2"; else WARNED+="${WARNED:+, }$2"; fi
  REPORT+="[$1] $2"$'\n'"$3"$'\n\n'
}

# step LEVEL NAME CMD...: run CMD, output to the log. A nonzero exit counts as LEVEL: fail, warn, or lp (the
# collector's codes: 2 = some pages failed, old copies kept -> warn; 3 = Node too old and anything else -> fail).
step() {
  local level="$1" name="$2" rc; shift 2
  "$@" > "$OUT" 2>&1; rc=$?
  cat "$OUT" >> "$LOG"
  [ "$rc" = 0 ] && return 0
  if [ "$level" = lp ]; then if [ "$rc" = 2 ]; then level=warn; else level=fail; fi; fi
  record "$level" "$name (exit $rc)" "$(tail -n 15 "$OUT")"
  return "$rc"
}

# push the discovery commit; publish_day.py commits to the same branch through the API, so rebase once if needed
push_commit() {
  git push -q && return 0
  if git pull -q --rebase && git push -q; then return 0; fi
  git rebase --abort >/dev/null 2>&1
  return 1
}

# 1. new code first, but never under a running capture (its python would differ from the files on disk)
if [ -z "${OWCSKR_DAILY_PULLED:-}" ]; then
  if capture_running; then log "capture running - git pull skipped"
  elif [ -n "$(git status --porcelain --untracked-files=no 2>&1)" ]; then log "local changes in the work tree - git pull skipped"
  else
    before="$(git rev-parse HEAD 2>/dev/null)"
    if step warn "git pull --ff-only" git pull --ff-only && [ "$(git rev-parse HEAD 2>/dev/null)" != "$before" ]; then
      log "updated $before -> $(git rev-parse --short HEAD); restarting with the new code"
      rm -f "$OUT"   # exec skips the EXIT trap
      OWCSKR_DAILY_PULLED=1 exec bash "$ROOT/tools/run_daily.sh"
    fi
  fi
fi

# 2. new stages and events on Liquipedia -> data/competitions.json, data/active.json
LISTS=(data/competitions.json data/active.json)
step lp "run-lp --discover" node collector/run-lp.mjs --discover
if ! git diff --quiet -- "${LISTS[@]}" 2>/dev/null; then
  if [ "${OWCSKR_AUTOCOMMIT:-0}" = 1 ]; then
    if step warn "git commit (discover)" git commit -q -m "data: discovered competitions $(date +%F)" -- "${LISTS[@]}" \
       && [ "${OWCSKR_AUTOPUSH:-0}" = 1 ]; then
      step warn "git push (discover)" push_commit
    fi
  else
    log "competitions.json / active.json changed - not committed (OWCSKR_AUTOCOMMIT is not 1)"
  fi
fi

# 3. data
step lp "run-lp --active-only" node collector/run-lp.mjs --active-only
step fail "build.mjs" node collector/build.mjs
step fail "republish_recent.py" "$PY" -I tools/republish_recent.py
step fail "schedule_today.py --upcoming" "$PY" -I tools/schedule_today.py --upcoming

# 4. PC-only site files (recorders, admin, handover notes) to the private repo owcs-kr-recorders; skips when unchanged
if [ -n "${OWCSKR_RECORDERS_DIR:-}" ]; then
  if [ -f "$OWCSKR_RECORDERS_DIR/backup.py" ]; then step fail "recorders backup.py" "$PY" -I "$OWCSKR_RECORDERS_DIR/backup.py"
  else record fail "recorders backup" "OWCSKR_RECORDERS_DIR='$OWCSKR_RECORDERS_DIR' has no backup.py"; fi
fi

# 5. SOOP timestamp comments the night run missed (machine off, replay uploaded late)
site_dir_state; sd=$?
if [ "$sd" = 2 ]; then
  record fail "OWCSKR_SITE_DIR" "OWCSKR_SITE_DIR='$OWCSKR_SITE_DIR' does not exist (recorders and replay comments cannot run)"
elif [ "$sd" = 0 ] && [ -f "$OWCSKR_SITE_DIR/replay_comment.py" ]; then
  step fail "replay_comment.py --post" bash -c 'cd "$1" && exec "$2" -X utf8 replay_comment.py --post' _ "$OWCSKR_SITE_DIR" "$PY"
fi

# 6. is the deployed site still being rebuilt? (alerts here, in the summary below)
step warn "site freshness (healthcheck.py)" "$PY" -I tools/healthcheck.py --quiet

if [ -n "$FAILED$WARNED" ]; then
  title="OWCSKR 일일 작업"; [ -n "$FAILED" ] && title+=" 실패: $FAILED" || title+=" 경고: $WARNED"
  log "problems: ${FAILED:-none failed}${WARNED:+ / warnings: $WARNED}"
  notify "$title" "$REPORT(log: $LOG)"
fi
if [ -n "$FAILED" ]; then
  hc_ping "${OWCSKR_HC_DAILY:+$OWCSKR_HC_DAILY/fail}" "$REPORT"
  exit 1
fi
hc_ping "${OWCSKR_HC_DAILY:-}" "$REPORT"
log "done${WARNED:+ (warnings: $WARNED)}"
exit 0
