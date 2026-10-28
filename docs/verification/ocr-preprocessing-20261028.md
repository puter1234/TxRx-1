# OCR source preprocessing and detected barcode display

## Change

The YOLO26 path previously preprocessed the detector inputs but passed raw color source crops to PARSeq. It now extracts the green channel and applies the same fixed 3.5 gain to the full 8000 x 6000 camera source before the recovered text quadrilaterals are cropped and rotated. Preparation keeps one full-resolution channel; only the small OCR crops become three-channel images. Camera originals, saved evidence, and barcode value decoding retain their original pixels. Both automatic production OCR and the bench model tests use this path. The other locator algorithms and manually defined OCR regions are unchanged.

The OCR crop previews are the actual prepared inputs passed to PARSeq. The preprocessing tab also offers the prepared full-resolution source. Detector inference and image acquisition are not repeated when changing display views.

Detection results now show the barcode count, numbered outlines, selection buttons and an enlarged crop for the selected barcode. Model barcode crops use the same green gain and are displayed along their long edge. A detected tag without a barcode explicitly shows zero barcodes. The barcode-only and raw download paths are unchanged.

Chromium also reproduced an outline visibility defect: after the image decoded, the SVG geometry was present in the correct position but was not visible over the image. Giving the overlay an explicit stacking order restored it. Browser checks used the actual component and a retained image, switched between two detections, and confirmed visible green outline pixels at desktop and narrow widths.

## Validation

- Backend checks cover full-resolution alternating-pixel detail, original preservation, gain before affine interpolation, both text orientations, exact OCR crop previews, retained-frame display on both bench routes, invalid region selection, and conveyor behavior. All 63 checks not marked slow passed.
- The broader initial run had 63 passes, 9 skips, and one missing-file failure in the existing slow barcode-only test. Its private `images/KakaoTalk_20260807_200206873.jpg` fixture is absent. Ten slow tests were excluded from the final available-fixture run; their hardware/private-data requirements were not fabricated.
- All 64 frontend tests passed. TypeScript and production build passed.
- Real bundled ONNX models and public PARSeq weights read `E62002ATW42BLK0050` from the repository sample in two runs. The original 4000 x 3000 sample was upsampled only to exercise the 8000 x 6000 input contract. These are not real 48MP camera captures or Jetson benchmarks. Full-source preparation took 35 and 58 ms, with total processing around 1.02 and 1.05 seconds on this cloud CPU during checks.
- This change does not establish the cause of the separate camera disconnections or indefinite OCR execution on the user's device.
