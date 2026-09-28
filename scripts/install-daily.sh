#!/usr/bin/env bash
# Install the daily learning cycle as a macOS LaunchAgent.
#
# This is what makes the system improve without being asked to. It runs on
# THIS machine rather than in CI because answering questions needs a local
# model, and a hosted runner has no Ollama.
#
#   ./scripts/install-daily.sh           # install and start
#   ./scripts/install-daily.sh uninstall
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.vyuha.daily"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [[ "${1:-install}" == "uninstall" ]]; then
  launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed ${LABEL}."
  exit 0
fi

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${ROOT}/.venv/bin/python</string>
    <string>${ROOT}/scripts/daily_learn.py</string>
    <string>--all</string>
  </array>
  <key>WorkingDirectory</key><string>${ROOT}</string>
  <!-- 09:20 IST, just after the NSE opens. Adjust if your clock is elsewhere. -->
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>20</integer></dict>
  <!-- If the Mac was asleep at the scheduled time, run once on wake rather
       than skipping the day entirely. A missed day is a missed batch of
       questions, and the loop is already slow to accumulate evidence. -->
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>/tmp/vyuha-daily.log</string>
  <key>StandardErrorPath</key><string>/tmp/vyuha-daily.err</string>
</dict></plist>
PLIST_EOF

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed ${LABEL}: runs daily at 09:20."
echo "  logs:    /tmp/vyuha-daily.log"
echo "  run now: launchctl kickstart gui/$(id -u)/${LABEL}"
echo "  remove:  ./scripts/install-daily.sh uninstall"
