"""Software correction applied to OCR crops after camera capture."""

import cv2
import numpy as np
from PIL import Image
from pydantic import Field

from .schema import Model


class OCRCorrection(Model):
    gain: float = Field(default=1.0, ge=0.5, le=8.0)
    offset: float = Field(default=0.0, ge=-64.0, le=128.0)
    gamma: float = Field(default=1.0, ge=0.25, le=2.0)
    contrast: float = Field(default=1.0, ge=0.5, le=3.0)
    clahe: bool = False


def correct(image: Image.Image, settings: OCRCorrection) -> Image.Image:
    if settings == OCRCorrection():
        return image
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    if settings.gain != 1 or settings.offset != 0 or settings.contrast != 1:
        values = rgb.astype(np.float32) * settings.gain + settings.offset
        values = (values - 127.5) * settings.contrast + 127.5
        rgb = np.clip(values, 0, 255).astype(np.uint8)
    if settings.gamma != 1:
        lut = np.clip(
            (np.arange(256, dtype=np.float32) / 255) ** settings.gamma * 255,
            0, 255,
        ).astype(np.uint8)
        rgb = cv2.LUT(rgb, lut)
    if settings.clahe:
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        lab[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(
            lab[:, :, 0]
        )
        rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    return Image.fromarray(rgb)
