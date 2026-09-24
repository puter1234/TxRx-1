#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PARSeq 로드/전처리/인식 공용 모듈.

CLI(run_ocr.py)와 웹(app.py)이 같은 코드를 쓰도록 여기 모아둔다.
"""

from __future__ import annotations

import threading
import time
import sys
import math
from pathlib import Path

import torch
from PIL import Image, ImageOps

HUB_REPO = "baudm/parseq"
MODEL_NAMES = ["parseq"]


def resolve_device(prefer: str = "auto") -> torch.device:
    if prefer != "auto":
        return torch.device(prefer)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_model(name: str, device: torch.device):
    """검증된 기존 PARSeq를 로컬 소스/가중치에서만 로드한다. 원격 조회 없음."""
    if name != 'parseq':
        raise RuntimeError('운영 기준선은 기존 PARSeq 모델입니다.')
    from station.vision import verify_model
    directory = Path(__file__).resolve().parents[1] / 'models/parseq'
    verify_model(directory)
    sys.path.insert(0, str(directory / 'source'))
    from strhub.models.utils import create_model
    model = create_model('parseq', pretrained=False)
    weights = torch.load(directory / 'parseq-bb5792a6.pt', map_location='cpu', weights_only=True)
    model.model.load_state_dict(weights, strict=True)
    return model.eval().to(device)


def build_transform(img_size):
    """PARSeq 공식 전처리를 그대로 사용한다 (spec.md 3.3).

    strhub 임포트가 실패하는 환경(lmdb 미설치 등)에서는 동일한 변환을 직접 구성한다.
    공식 구현도 augment=False일 때는 resize(bicubic) -> to_tensor -> normalize(0.5, 0.5)
    세 단계가 전부라 결과는 같다.
    """
    try:
        from strhub.data.module import SceneTextDataModule

        return SceneTextDataModule.get_transform(img_size)
    except Exception as exc:
        print(f"  [i] strhub 전처리 임포트 실패({exc.__class__.__name__}) - 동등한 fallback 사용")
        from torchvision import transforms as T

        return T.Compose(
            [
                T.Resize(img_size, T.InterpolationMode.BICUBIC),
                T.ToTensor(),
                T.Normalize(0.5, 0.5),
            ]
        )


@torch.inference_mode()
def infer(model, tensor):
    """이미지 텐서 1장 -> (문자열, 문자별 confidence 텐서)."""
    logits = model(tensor)
    probs = logits.softmax(-1)
    labels, confidences = model.tokenizer.decode(probs)
    return labels[0], confidences[0]


def to_rgb(image: Image.Image) -> Image.Image:
    """알파 채널은 흰 배경에 합성하고, 폰 사진의 EXIF 회전은 펴준다.

    알파를 그냥 convert("RGB")하면 투명 영역이 검게 깔려서 인식이 망가진다.
    """
    image = ImageOps.exif_transpose(image)
    has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
    if has_alpha:
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.split()[-1])
        return canvas
    return image.convert("RGB")


class Recognizer:
    """모델 + 전처리를 묶어 한 번만 로드해두고 재사용한다."""

    def __init__(self, model_name: str = "parseq", device: str = "auto"):
        self.model_name = model_name
        self.device = resolve_device(device)
        self.gpu_name = torch.cuda.get_device_name(self.device) if self.device.type == "cuda" else ""
        self.model = load_model(model_name, self.device)
        self.img_size = tuple(self.model.hparams.img_size)
        self.transform = build_transform(self.model.hparams.img_size)
        # 웹에서 요청이 겹칠 때 추론이 서로 끼어들지 않도록 직렬화한다.
        self._lock = threading.Lock()

    def read(self, image: Image.Image) -> dict:
        tensor = self.transform(to_rgb(image)).unsqueeze(0).to(self.device)
        with self._lock:
            start = time.perf_counter()
            label, per_char = infer(self.model, tensor)
            if self.device.type == "cuda":
                torch.cuda.synchronize()
            # One device-to-host transfer instead of a GPU sync per character.
            probabilities = per_char.detach().cpu().tolist()
            elapsed = (time.perf_counter() - start) * 1000.0

        return {
            "text": label,
            "confidence": math.prod(probabilities) if probabilities else 0.0,
            "min_char": min(probabilities) if probabilities else 0.0,
            "chars": [
                {"ch": ch, "p": float(p)} for ch, p in zip(list(label) + ["<eos>"], probabilities)
            ],
            "ms": elapsed,
        }


def versions() -> dict:
    """환경 진단용. 웹 /api/info와 setup 자체점검이 같이 쓴다."""
    import torchvision

    info = {
        "torch": torch.__version__,
        "torchvision": torchvision.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_build": torch.version.cuda or "(CPU 빌드)",
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
    }
    try:
        import timm

        info["timm"] = timm.__version__
    except Exception:
        info["timm"] = "(없음)"
    return info
