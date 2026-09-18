"""Grant the desktop user device access. Does not request GPIO lines or outputs."""

import os
import platform
import pwd
import subprocess
from pathlib import Path


def main():
    if platform.system() != "Linux" or platform.machine() != "aarch64":
        raise SystemExit("Run this on the J4012.")
    user = os.environ.get("SUDO_USER", "")
    if os.geteuid() != 0 or not user or pwd.getpwnam(user).pw_uid == 0:
        raise SystemExit("Run from your normal user: sudo python3 scripts/setup_jetson_access.py")
    rule = Path("/etc/udev/rules.d/99-txrx-gpio.rules")
    contents = 'SUBSYSTEM=="gpio", KERNEL=="gpiochip0", GROUP="gpio", MODE="0660"\n'
    if rule.exists() and rule.read_text(encoding="utf-8") != contents:
        raise SystemExit("An existing TXRX GPIO rule differs. Review it before changing permissions.")
    subprocess.run(["groupadd", "-f", "gpio"], check=True)
    subprocess.run(["usermod", "-aG", "video,dialout,gpio", user], check=True)
    rule.write_text(contents, encoding="utf-8")
    rule.chmod(0o644)
    subprocess.run(["udevadm", "control", "--reload-rules"], check=True)
    subprocess.run(["udevadm", "trigger", "--action=change", "--subsystem-match=gpio"], check=True)
    print("Log out and log in again to activate video, serial and gpiochip0 permissions.")
    print("No GPIO lines or outputs were opened. Confirm the actual GPIO mapping before output tests.")


if __name__ == "__main__":
    main()
