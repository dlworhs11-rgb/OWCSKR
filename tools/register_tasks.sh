#!/usr/bin/env bash
# Registers the daily OWCSKR job as a systemd user timer (09:00 KST, and 3 minutes after every boot so a reboot
# re-creates that day's capture timers, which live only in memory) and runs it once now.
# The job refreshes Liquipedia and schedules each match day's capture (owcskr-live-<date> timers).
# Also installs owcskr-alert@.service: the daily, capture and recorder units name it in OnFailure=, so a unit that
# fails for good (crash loop past its start limit, killed, timed out) alerts (tools/notify.py --unit-failed).
# Run it again after an update that changes the unit files written here.
# Run it in a shell where you logged in as this user directly (ssh user@server): 'sudo -u' / 'su' shells have no
# user bus and systemctl --user fails with "Failed to connect to bus".
set -eu
. "$(dirname "$0")/env.sh"
if ! systemctl --user show-environment >/dev/null 2>&1; then
  echo "systemctl --user cannot reach the user manager (no user bus)." >&2
  echo "Log in as $USER directly (ssh $USER@<server>), not via sudo -u / su; on minimal images: sudo apt install dbus-user-session, then log in again." >&2
  exit 1
fi
# the timer's environment has no nvm / login-shell PATH: node must be a system install (docs/linux-server.md)
NODE="$(command -v node || true)"
if [ -z "$NODE" ]; then echo "warning: node not found - the daily job needs Node 18+ (NodeSource 20.x)" >&2
else
  case "$NODE" in "$HOME"/*) echo "warning: node is $NODE (nvm?): the systemd timer will not find it - install Node system-wide" >&2 ;; esac
  major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
  if [ "$major" -lt 18 ]; then echo "warning: node $(node --version 2>/dev/null) is too old: the collector needs 18+" >&2; fi
fi
mkdir -p "$UNIT_DIR"
# owcskr-alert@<unit>.service: the alert when a capture, recorder or daily unit fails for good (OnFailure=)
ensure_alert_unit
R="${ROOT//%/%%}"      # a literal % in a unit file is written %%
cat > "$UNIT_DIR/owcskr-daily.service" <<EOF
[Unit]
Description=OWCSKR daily job (Liquipedia refresh, build, schedule the captures)
# a run that never reached its own alert (killed, timed out, bad .env) still alerts; exit 1 (a step failed) the job
# alerted itself, and tools/notify.py --unit-failed skips it
OnFailure=owcskr-alert@%n.service

[Service]
Type=oneshot
WorkingDirectory=$R
ExecStart=/bin/bash "$R/tools/run_daily.sh"
TimeoutStartSec=1h
EOF
cat > "$UNIT_DIR/owcskr-daily.timer" <<EOF
[Unit]
Description=OWCSKR daily job at 09:00 KST and after each boot

[Timer]
OnCalendar=*-*-* 09:00:00 Asia/Seoul
# no Persistent=true: a boot after a missed 09:00 would run it at once, before the network is up, and again at 3 min
OnStartupSec=3min

[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable owcskr-daily.timer
# restart (not just start): an already active timer would keep its old trigger list
systemctl --user restart owcskr-daily.timer
# user timers only fire while the user has a session unless lingering is on
if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
  loginctl enable-linger "$USER" || echo "run once with sudo: sudo loginctl enable-linger $USER"
fi
echo 'Registered: owcskr-daily.timer (every day 09:00 KST and 3 min after each boot)'
echo 'Running it once now...'
systemctl --user start --no-block owcskr-daily.service
