#!/bin/sh
# Starts the station (if it is not running yet) and opens its first screen full screen.
# Run at login by the autostart entry and by the desktop icon (scripts/install_kiosk.sh).
# Everything it does is written to runtime/kiosk.log.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${TXRX_PORT:-8000}"
URL="http://127.0.0.1:$PORT"
cd "$ROOT"
mkdir -p runtime
exec >>runtime/kiosk.log 2>&1
echo "== $(date) kiosk start (user $(id -un), display ${DISPLAY:-none})"
up() { python3 -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=2)" "$URL/api/status" >/dev/null 2>&1; }
if ! up; then
  echo "station not running; starting scripts/run_bench.py"
  nohup python3 scripts/run_bench.py >>runtime/station.log 2>&1 &
  # Model loading and a first GPU package swap can take a while.
  i=0
  while ! up && [ "$i" -lt 300 ]; do sleep 1; i=$((i + 1)); done
  up && echo "station up after ${i}s" || echo "station still not answering after ${i}s; see runtime/station.log"
fi
BROWSER=""
for b in google-chrome google-chrome-stable chromium-browser chromium; do
  if command -v "$b" >/dev/null 2>&1; then BROWSER="$b"; break; fi
done
if [ -z "$BROWSER" ]; then echo "no Chrome found"; exit 1; fi
PROFILE="$HOME/.txrx-chrome"
# A Chrome already open on this profile would only add a normal window and ignore --kiosk.
pkill -f -- "--user-data-dir=$PROFILE" 2>/dev/null && sleep 2
# After a power cut Chrome would offer to restore the old tabs instead of the first screen.
sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/; s/"exited_cleanly":false/"exited_cleanly":true/' \
  "$PROFILE/Default/Preferences" 2>/dev/null || true
echo "opening $URL/ with $BROWSER"
# GPU drawing off: with it on, Chrome on the J4012 stops redrawing the page.
exec "$BROWSER" --user-data-dir="$PROFILE" --disable-gpu --kiosk --start-fullscreen --no-first-run \
  --noerrdialogs --disable-session-crashed-bubble --disable-infobars --password-store=basic "$URL/"
