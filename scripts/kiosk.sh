#!/bin/sh
# Starts the station (if it is not running yet) and opens its first screen full screen.
# Run at login by the autostart entry and by the desktop icon (scripts/install_kiosk.sh).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${TXRX_PORT:-8000}"
URL="http://127.0.0.1:$PORT"
cd "$ROOT"
up() { python3 -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=2)" "$URL/api/status" >/dev/null 2>&1; }
if ! up; then
  mkdir -p runtime
  nohup python3 scripts/run_bench.py >>runtime/station.log 2>&1 &
  # Model loading and a first GPU package swap can take a while.
  i=0
  while ! up && [ "$i" -lt 300 ]; do sleep 1; i=$((i + 1)); done
fi
PROFILE="$HOME/.txrx-chrome"
# After a power cut Chrome would offer to restore the old tabs instead of the first screen.
sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/; s/"exited_cleanly":false/"exited_cleanly":true/' \
  "$PROFILE/Default/Preferences" 2>/dev/null || true
# GPU drawing off: with it on, Chrome on the J4012 stops redrawing the page.
exec google-chrome --user-data-dir="$PROFILE" --disable-gpu --kiosk --no-first-run \
  --noerrdialogs --disable-session-crashed-bubble --disable-infobars --password-store=basic "$URL/"
