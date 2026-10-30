#!/bin/sh
# Opens the station screen in Google Chrome on the J4012. With GPU drawing on,
# Chrome there stops redrawing the page: taps still land, the screen stays put.
set -eu
exec google-chrome --user-data-dir="$HOME/.txrx-chrome" --disable-gpu "http://127.0.0.1:${TXRX_PORT:-8000}/"
