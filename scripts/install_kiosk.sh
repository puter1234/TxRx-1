#!/bin/sh
# One-time setup on the J4012: the station opens full screen on its first screen after
# every restart, and a desktop icon opens it too. Run as the user who works the station
# (not with sudo), from the project folder:
#   sh scripts/install_kiosk.sh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$(id -u)" = 0 ]; then echo "Run without sudo, as the station's user."; exit 1; fi
chmod +x "$ROOT/scripts/kiosk.sh"
entry() {
  cat <<DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=TxRx 계수
Exec=/bin/sh "$ROOT/scripts/kiosk.sh"
Icon=applications-system
Terminal=false
Categories=Utility;
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
DESKTOP
}
ok() { echo "OK   $1"; }
fail() { echo "FAIL $1"; }

mkdir -p "$HOME/.config/autostart" && entry >"$HOME/.config/autostart/txrx-kiosk.desktop" \
  && ok "autostart: $HOME/.config/autostart/txrx-kiosk.desktop" || fail "autostart entry"

# Also in the app list (search "TxRx"), which works even when desktop icons are turned off.
mkdir -p "$HOME/.local/share/applications" && entry >"$HOME/.local/share/applications/txrx-kiosk.desktop" \
  && ok "app list: TxRx 계수" || fail "app list entry"

DESK="$(xdg-user-dir DESKTOP 2>/dev/null)"
[ -n "$DESK" ] || DESK="$HOME/Desktop"
mkdir -p "$DESK"
if entry >"$DESK/txrx-kiosk.desktop" && chmod +x "$DESK/txrx-kiosk.desktop"; then
  # GNOME runs a desktop launcher only once it is marked trusted ("Allow Launching").
  if gio set "$DESK/txrx-kiosk.desktop" metadata::trusted true 2>/dev/null; then
    ok "desktop icon: $DESK/txrx-kiosk.desktop"
  else
    ok "desktop icon: $DESK/txrx-kiosk.desktop (right-click it, then 'Allow Launching')"
  fi
else
  fail "desktop icon in $DESK"
fi

# The screen must not blank or lock over the station.
gsettings set org.gnome.desktop.session idle-delay 0 2>/dev/null \
  && gsettings set org.gnome.desktop.screensaver lock-enabled false 2>/dev/null \
  && ok "screen stays on and unlocked" || fail "screen blank/lock settings (gsettings)"

# Log this user in without a password after a restart, so the autostart runs.
CONF=""
for f in /etc/gdm3/custom.conf /etc/gdm3/daemon.conf; do [ -f "$f" ] && CONF="$f" && break; done
if [ -n "$CONF" ]; then
  if sudo sed -i -e '/^\[daemon\]/,/^\[/{/^#\?\s*AutomaticLoginEnable/d;/^#\?\s*AutomaticLogin\s*=/d}' \
      -e "s/^\[daemon\]/[daemon]\nAutomaticLoginEnable=true\nAutomaticLogin=$(id -un)/" "$CONF" \
      && grep -q "^AutomaticLogin=$(id -un)" "$CONF"; then
    ok "automatic login for $(id -un) ($CONF)"
  else
    fail "automatic login ($CONF)"
  fi
else
  fail "automatic login: no GDM config found (this desktop may not use GDM)"
fi
echo "Restart to check. Alt+F4 closes the full-screen window. Log: $ROOT/runtime/kiosk.log"
