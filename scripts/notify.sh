#!/usr/bin/env bash
# Show a Windows notification from WSL:  scripts/notify.sh "TITLE" "TEXT"
# Does nothing (exit 0) where powershell.exe is not available.
set -uo pipefail
command -v powershell.exe >/dev/null || { echo "notify: no powershell.exe" >&2; exit 0; }
ps1=$(wslpath -w "$(dirname "$(readlink -f "$0")")/notify-windows.ps1")
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$ps1" -Title "$1" -Text "$2"
