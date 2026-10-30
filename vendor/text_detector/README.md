# Text detector

`ch_PP-OCRv4_det_infer.onnx` is PaddleOCR's PP-OCRv4 text detection model in the
ONNX form shipped, unchanged, in the `rapidocr_onnxruntime` 1.4.4 wheel
(https://github.com/RapidAI/RapidOCR, Apache-2.0; model from
https://github.com/PaddlePaddle/PaddleOCR, Apache-2.0).

SHA-256 `d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9`,
checked before loading. Used only when the process test's text finder is set to
the detector (`tagreader/text_detector.py`).
