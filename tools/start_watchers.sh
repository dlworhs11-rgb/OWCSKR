#!/usr/bin/env bash
# Match-day live recorders for the site (series score + POTM, map name / bans / first comps, push to GitHub).
# Started by run_live.sh so they run every match day without a hand start. Each one is skipped when already running.
# They live in OWCSKR_SITE_DIR (not in this repo). Each gets its own systemd unit owcskr-<name> that restarts it
# after a crash (env.sh detach).
# Exit: 0 = all running (or OWCSKR_SITE_DIR not set: no recorders on this machine), 1 = OWCSKR_SITE_DIR set but
# missing, or a recorder could not be started.
set -u
. "$(dirname "$0")/env.sh"
site_dir_state; sd=$?
if [ "$sd" = 1 ]; then
  echo "$(date '+%F %T') start_watchers: OWCSKR_SITE_DIR not set - no recorders on this machine"
  exit 0
fi
if [ "$sd" = 2 ]; then
  echo "$(date '+%F %T') start_watchers: OWCSKR_SITE_DIR='$OWCSKR_SITE_DIR' does not exist - no recorders started" >&2
  exit 1
fi
SITE="$OWCSKR_SITE_DIR"
failed=0
for s in 'score_watch.py' 'pick_watch.py' 'caster_watch.py' 'live_relay.py' 'admin_server.py' \
         'build_owcs_data.py --watch --push' 'match_watch.py --shadow'; do
  script="${s%% *}"; name="${script%.py}"
  if pgrep -f -- "$s" >/dev/null 2>&1; then continue; fi
  # between two automatic restarts there is no process, but the unit still holds the name
  if have_systemd && unit_busy "owcskr-$name.service"; then continue; fi
  if [ ! -f "$SITE/$script" ]; then echo "start_watchers: $script not in $SITE - skipped"; continue; fi
  # shellcheck disable=SC2086  # $s holds the script and its flags
  if detach "$name" "$SITE" "$LOG_DIR/$name.log" "$PY" -u $s; then
    echo "started $s"
  else
    echo "start_watchers: could not start $s" >&2
    failed=1
  fi
done
exit "$failed"
