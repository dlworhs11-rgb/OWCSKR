#!/usr/bin/env bash
# Removes every OWCSKR systemd user timer (daily job + scheduled captures).
set -u
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
systemctl --user disable --now owcskr-daily.timer 2>/dev/null
for t in $(systemctl --user list-units --all --plain --no-legend 'owcskr-*.timer' | awk '{print $1}'); do
  systemctl --user stop "$t"
done
rm -f "$UNIT_DIR/owcskr-daily.service" "$UNIT_DIR/owcskr-daily.timer"
systemctl --user daemon-reload
echo 'All OWCSKR scheduled jobs removed.'
