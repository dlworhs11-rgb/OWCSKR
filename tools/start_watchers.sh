#!/usr/bin/env bash
# Match-day live recorders for the site (series score + POTM, map name / bans / first comps, push to GitHub).
# Started by run_live.sh so they run every match day without a hand start. Each one is skipped when already running.
# They live in OWCSKR_SITE_DIR (not in this repo).
set -u
. "$(dirname "$0")/env.sh"
SITE="${OWCSKR_SITE_DIR:-}"
if [ -z "$SITE" ] || [ ! -d "$SITE" ]; then
  echo "$(date '+%F %T') start_watchers: OWCSKR_SITE_DIR not set or missing ('$SITE') - no recorders started"
  exit 0
fi
for s in 'score_watch.py' 'pick_watch.py' 'caster_watch.py' 'live_relay.py' 'admin_server.py' \
         'build_owcs_data.py --watch --push' 'match_watch.py --shadow'; do
  script="${s%% *}"; name="${script%.py}"
  if pgrep -f -- "$s" >/dev/null 2>&1; then continue; fi
  if [ ! -f "$SITE/$script" ]; then echo "start_watchers: $script not in $SITE - skipped"; continue; fi
  # shellcheck disable=SC2086  # $s holds the script and its flags
  detach "$name" "$SITE" "$LOG_DIR/$name.log" "$PY" -u $s
  echo "started $s"
done
