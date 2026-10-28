# Camera preview and OCR investigation, 2026-10-28

## Confirmed defects addressed

- CameraView waited 500 ms after every HTTP response; the separate OCR preview waited 700 ms. Preview throughput therefore remained below 2 FPS regardless of camera FPS. Both now use the negotiated camera FPS, accounting for request duration, with one request in flight and a bounded request timeout.
- Each preview request copied the entire camera frame under its shared-memory lock. At 8000 x 6000 BGR this was 144,000,000 bytes. Capture now publishes an additional 1280 x 960 preview buffer, and preview reads copy 3,686,400 bytes. Inspection still reads the full original with the same sequence and receipt timestamp.
- An OpenCV exception during a single read bypassed the existing false-return retry and terminated capture. Both cases now use the existing bounded retry window. Sustained missing frames still report disconnection.
- Bench mode lacked recovery after a capture process exited or stopped publishing. It now retries the current profile after 2 seconds of loss, including fixed controls. Identity of the stream is checked under the camera lock so a manual disconnect or a subsequent profile change invalidates the retry. Recovery does not restart outputs. Production retains its existing recovery controller.
- Bench.stop invoked OCR cleanup listeners before output OFF. OFF and restart cooldown now precede listeners; a listener exception cannot skip OFF.

## Unresolved

The initiating cause of the user's repeated camera interruptions has not been identified. Retry and recovery changes do not establish that cause. Loss logs now include USB node presence/link information, process exit code, failed read count, capture stage and stage duration.

The user's indefinite OCR wait has not been reproduced or diagnosed. Incorrectly timed stack photographs supplied earlier were excluded from the investigation. No claim is made that a timeout or UI change fixes model execution. Actual OCR operations now record stages and automatically capture Python stacks after 10 seconds, including when native code holds the GIL. Records are under runtime/diagnostics/ocr-*.log. scripts/inspect_ocr_hang.py prints a captured stalled-operation record when available instead of sampling an unrelated later idle state.

## Validation

- 114 backend tests passed: UVC failure/exception recovery, preview/original pixel separation, camera commissioning, current-profile recovery, manual disconnect, conveyor OCR, bench output stop/cooldown, Windows adapter, model coordinates, and stalled-operation diagnostics.
- 55 existing frontend tests passed. Four additional preview checks passed: 3/30/60 FPS pacing and retry of a request that never completes.
- Frontend TypeScript check and production build passed.
- A subprocess test deliberately held the GIL with ctypes.PyDLL. The CPython watchdog recorded the executing function and stage without py-spy, sudo, or ARM64 native unwinding.
- Public PARSeq weights parseq-bb5792a6.pt, public PARSeq source, bundled ONNX models, and the barcode-pipeline repository's camera-test-dfacfbe1-5b1e-47b6-9288-b72aa5bce37d.png were run through Vision.test_auto. That 4000 x 3000 fixture was upsampled solely to exercise the 8000 x 6000 input contract; it is not an actual 48MP capture. Two runs after the changes completed in 774 ms and 678 ms on x86 CPU and read E62002ATW42BLK0050. This does not validate the user's Jetson CUDA execution or current camera image.
- On this cloud CPU, median copy time over ten copies was 20.979 ms for the original and 0.197 ms for the preview. These are memory-copy timings, not measured camera or browser FPS on the user's equipment.

No Jetson, USB camera, GPIO output, relay, or motor was available in the cloud environment.
