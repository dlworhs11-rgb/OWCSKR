#!/usr/bin/env bash
# Registers the daily OWCSKR job as a systemd user timer (09:00 KST) and runs it once now.
# The job refreshes Liquipedia and schedules each match day's capture (owcskr-live-<date> timers).
set -eu
. "$(dirname "$0")/env.sh"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/owcskr-daily.service" <<EOF
[Unit]
Description=OWCSKR daily job (Liquipedia refresh, build, schedule the captures)

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=/bin/bash $ROOT/tools/run_daily.sh
TimeoutStartSec=1h
EOF
cat > "$UNIT_DIR/owcskr-daily.timer" <<EOF
[Unit]
Description=OWCSKR daily job at 09:00 KST

[Timer]
OnCalendar=*-*-* 09:00:00 Asia/Seoul
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now owcskr-daily.timer
# user timers only fire while the user has a session unless lingering is on
if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
  loginctl enable-linger "$USER" || echo "run once with sudo: sudo loginctl enable-linger $USER"
fi
echo 'Registered: owcskr-daily.timer (every day 09:00 KST)'
echo 'Running it once now...'
systemctl --user start --no-block owcskr-daily.service
