#!/bin/sh
# One-time setup on the J4012: the station opens full screen on its first screen after
# every restart, and a desktop icon opens it too. Run as the user who works the station:
#   sh scripts/install_kiosk.sh
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
chmod +x "$ROOT/scripts/kiosk.sh"
entry() {
  cat <<DESKTOP
[Desktop Entry]
Type=Application
Name=TxRx 계수
Exec=$ROOT/scripts/kiosk.sh
Icon=applications-system
Terminal=false
X-GNOME-Autostart-enabled=true
DESKTOP
}
mkdir -p "$HOME/.config/autostart"
entry >"$HOME/.config/autostart/txrx-kiosk.desktop"
DESK="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
mkdir -p "$DESK"
entry >"$DESK/txrx-kiosk.desktop"
chmod +x "$DESK/txrx-kiosk.desktop"
gio set "$DESK/txrx-kiosk.desktop" metadata::trusted true 2>/dev/null || true
# The screen must not blank or lock over the station.
gsettings set org.gnome.desktop.session idle-delay 0 2>/dev/null || true
gsettings set org.gnome.desktop.screensaver lock-enabled false 2>/dev/null || true
# Log this user in without a password after a restart, so the autostart runs.
if [ -f /etc/gdm3/custom.conf ]; then
  sudo sed -i -e '/^\[daemon\]/,/^\[/{/^#\?\s*AutomaticLoginEnable/d;/^#\?\s*AutomaticLogin\s*=/d}' \
    -e "s/^\[daemon\]/[daemon]\nAutomaticLoginEnable=true\nAutomaticLogin=$(id -un)/" /etc/gdm3/custom.conf
fi
echo "Done. Restart to check; Alt+F4 closes the full-screen window."
