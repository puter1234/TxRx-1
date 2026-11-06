"""TXRX offline inspection station."""
import os

# Ultralytics reads this once, at its first import (the tag/barcode runners import it
# before the wappen counter does). It must never pip-install packages on the device.
os.environ.setdefault("YOLO_AUTOINSTALL", "false")

__version__ = "0.3.0"
