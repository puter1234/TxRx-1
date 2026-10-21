# Barcode pipeline runtime

Inference sources, deployment settings and ONNX weights copied without changes
from https://github.com/puter1234/barcode-pipeline at
`100a3025192e7ea06a1eefcf32c2b7d7b16ba9a9`.

`manifest.json` records each bundled file's SHA-256. The station verifies this
bundle before loading either model. Runtime inference does not download files.
Training data, training scripts and PT weights are not needed for this adapter.

The station integration is in `tagreader/model_pipeline.py`. It retains the
8000 x 6000 camera frame, creates a 4000 x 3000 detection image from that same
frame, then samples OCR crops from the retained 48MP frame. Upstream text
localization is experimental. Both text orientations are passed to PARSeq;
production brand rules still decide whether a recognized code is acceptable.
