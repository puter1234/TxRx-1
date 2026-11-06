#!/bin/sh
# One-time: adds Korean (한글) input to the J4012 desktop and the station screen.
# Run as the station's user (not with sudo), with the internet connected:
#   sh scripts/install_korean_keyboard.sh
# Then restart. 한/영 key or Shift+Space switches; it starts in 한글.
set -u
if [ "$(id -u)" = 0 ]; then echo "Run without sudo, as the station's user."; exit 1; fi
ok() { echo "OK   $1"; }
fail() { echo "FAIL $1"; }

sudo apt-get update -q && sudo apt-get install -y -q ibus ibus-hangul ibus-gtk ibus-gtk3 im-config fonts-noto-cjk \
  && ok "ibus-hangul installed" || fail "apt-get install"

# ibus as the input method for every app, Chrome included.
im-config -n ibus >/dev/null 2>&1 && ok "input method: ibus" || fail "im-config -n ibus"
# The same in every login, whichever way the desktop starts (some do not read im-config).
for f in "$HOME/.xprofile" "$HOME/.profile"; do
  grep -q "GTK_IM_MODULE=ibus" "$f" 2>/dev/null || cat >>"$f" <<'ENV'
export GTK_IM_MODULE=ibus QT_IM_MODULE=ibus XMODIFIERS=@im=ibus
ENV
done
ok "GTK_IM_MODULE / QT_IM_MODULE / XMODIFIERS set to ibus"

# Start ibus at every login even where the desktop does not start it by itself.
mkdir -p "$HOME/.config/autostart"
cat >"$HOME/.config/autostart/ibus-daemon.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=ibus
Exec=ibus-daemon -drx
X-GNOME-Autostart-enabled=true
DESKTOP
ok "ibus starts at login"

# English and 한글 in the input list, 한글 first so it is the one in use.
gsettings set org.gnome.desktop.input-sources sources "[('ibus', 'hangul'), ('xkb', 'us')]" 2>/dev/null \
  && ok "input sources: 한글, English" || fail "gsettings input-sources"
# Start typing in 한글 (ibus-hangul starts in English by default); 한/영 or Shift+Space switches.
gsettings set org.freedesktop.ibus.engine.hangul initial-input-mode 'hangul' 2>/dev/null || true
gsettings set org.freedesktop.ibus.engine.hangul switch-keys "Hangul,Shift+space" 2>/dev/null || true
gsettings set org.freedesktop.ibus.general preload-engines "['hangul', 'xkb:us::eng']" 2>/dev/null || true

echo "Restart to use it."
