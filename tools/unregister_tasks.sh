#!/usr/bin/env bash
# Removes every OWCSKR systemd user timer (daily job + each match day's capture, checks, site dispatch) and the unit
# files register_tasks.sh wrote (owcskr-daily.*, owcskr-alert@.service), and forgets failed OWCSKR units.
# A capture or recorder that is running right now is LEFT RUNNING by default (stopping a capture mid-broadcast loses
# the rest of the day): the script lists them with the command to stop them. --stop-running stops them too.
# usage: bash tools/unregister_tasks.sh [--stop-running]
set -u
STOP_RUNNING=0
case "${1:-}" in
  --stop-running) STOP_RUNNING=1 ;;
  "") ;;
  *) echo "usage: $0 [--stop-running]" >&2; exit 2 ;;
esac
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

# owcskr_units [list-units options] PATTERN: unit names only. The name is the first word with a letter in it: past a
# status mark ('●', '*') that some systemd versions print before a failed unit even with --plain, whatever its bytes.
owcskr_units() {
  systemctl --user list-units --all --plain --no-legend --full "$@" 2>/dev/null |
    awk '{ for (i = 1; i <= NF; i++) if ($i ~ /[A-Za-z]/) { if ($i ~ /^owcskr-/) print $i; next } }'
}

systemctl --user disable --now owcskr-daily.timer 2>/dev/null
for t in $(owcskr_units 'owcskr-*.timer'); do
  systemctl --user stop "$t"
done

# services still running: captures (owcskr-live-<date>), recorders (owcskr-<name>), a replay comment wait, the daily job
running="$(owcskr_units --state=active,activating,deactivating,reloading 'owcskr-*.service' | grep -v '^owcskr-alert@')"
if [ -n "$running" ]; then
  if [ "$STOP_RUNNING" = 1 ]; then
    echo "Stopping the running OWCSKR units:"; printf '  %s\n' $running
    # shellcheck disable=SC2086  # one unit name per word
    systemctl --user stop $running
  else
    echo "Left running (a capture stopped now loses the rest of the day):"; printf '  %s\n' $running
    echo "Stop them with: systemctl --user stop <unit>   (or: bash $0 --stop-running)"
  fi
fi

systemctl --user reset-failed 'owcskr-*' 2>/dev/null
rm -f "$UNIT_DIR/owcskr-daily.service" "$UNIT_DIR/owcskr-daily.timer" "$UNIT_DIR/owcskr-alert@.service"
systemctl --user daemon-reload
echo 'All OWCSKR scheduled jobs removed.'
