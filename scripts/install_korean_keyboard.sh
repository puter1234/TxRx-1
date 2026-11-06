#!/bin/sh
# One-time: adds Korean (한글) input to the J4012 desktop and the station screen.
# Run as the station's user (not with sudo), with the internet connected:
#   sh scripts/install_korean_keyboard.sh
# It takes effect after the next restart. Switch 한/영 with the 한/영 key, Shift+Space
# or Super+Space.
set -u
if [ "$(id -u)" = 0 ]; then echo "Run without sudo, as the station's user."; exit 1; fi
ok() { echo "OK   $1"; }
fail() { echo "FAIL $1"; }

sudo apt-get update -q && sudo apt-get install -y -q ibus ibus-hangul fonts-noto-cjk \
  && ok "ibus-hangul installed" || fail "apt-get install ibus ibus-hangul fonts-noto-cjk"

# ibus as the input method for every app, Chrome included.
im-config -n ibus >/dev/null 2>&1 && ok "input method: ibus" || fail "im-config -n ibus"

# English and 한글 in the input list.
gsettings set org.gnome.desktop.input-sources sources "[('xkb', 'us'), ('ibus', 'hangul')]" 2>/dev/null \
  && ok "input sources: English, 한글" || fail "gsettings input-sources"

# The 한/영 key and Shift+Space switch inside 한글 input.
gsettings set org.freedesktop.ibus.engine.hangul switch-keys "Hangul,Shift+space" 2>/dev/null || true

echo "Restart to use it."
