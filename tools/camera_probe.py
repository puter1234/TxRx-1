"""USB 카메라가 실제로 지원하는 제어 속성(노출/게인/포커스/조리개 등)을 진단한다.

방식: 각 속성에 baseline 값을 읽고, 여러 테스트 값을 set() 한 뒤 get()으로 실제
반영됐는지 확인한다. DirectShow/드라이버가 속성을 무시하면 get() 값이 그대로다.
진단 후에는 원래 값으로 복원한다.
"""
import argparse
import sys

import cv2

# (표시 이름, cv2 상수, 테스트해볼 값 목록)
PROPS = [
    ("BRIGHTNESS", cv2.CAP_PROP_BRIGHTNESS, [0, 64, 128, 200]),
    ("CONTRAST", cv2.CAP_PROP_CONTRAST, [0, 64, 128, 200]),
    ("SATURATION", cv2.CAP_PROP_SATURATION, [0, 64, 128, 200]),
    ("SHARPNESS", cv2.CAP_PROP_SHARPNESS, [0, 64, 128, 200]),
    ("GAMMA", cv2.CAP_PROP_GAMMA, [50, 100, 200, 300]),
    ("GAIN", cv2.CAP_PROP_GAIN, [0, 30, 100, 255]),
    ("AUTO_EXPOSURE", cv2.CAP_PROP_AUTO_EXPOSURE, [0, 1, 0.25, 0.75]),
    ("EXPOSURE", cv2.CAP_PROP_EXPOSURE, [-3, -5, -7, -9]),
    ("AUTOFOCUS", cv2.CAP_PROP_AUTOFOCUS, [0, 1]),
    ("FOCUS", cv2.CAP_PROP_FOCUS, [0, 64, 128, 255]),
    ("IRIS (조리개)", cv2.CAP_PROP_IRIS, [0, 64, 128, 255]),
    ("ZOOM", cv2.CAP_PROP_ZOOM, [0, 50, 100, 200]),
    ("PAN", cv2.CAP_PROP_PAN, [-10, 0, 10]),
    ("TILT", cv2.CAP_PROP_TILT, [-10, 0, 10]),
    ("WB_TEMPERATURE", cv2.CAP_PROP_WB_TEMPERATURE, [3000, 4500, 6500]),
    ("AUTO_WB", cv2.CAP_PROP_AUTO_WB, [0, 1]),
    ("BACKLIGHT", cv2.CAP_PROP_BACKLIGHT, [0, 1]),
]

BACKENDS = {
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "any": cv2.CAP_ANY,
}


def probe(cap: cv2.VideoCapture) -> list[dict]:
    results = []
    for name, const, test_values in PROPS:
        baseline = cap.get(const)
        controllable = False
        applied_value = None

        for tv in test_values:
            cap.set(const, tv)
            cap.read()  # 일부 드라이버는 프레임을 읽어야 설정이 반영됨
            current = cap.get(const)
            if abs(current - baseline) > 1e-3:
                controllable = True
                applied_value = current
                break

        cap.set(const, baseline)  # 원복
        results.append({
            "name": name,
            "baseline": baseline,
            "controllable": controllable,
            "sample_value": applied_value,
        })
    return results


def print_report(results: list[dict]) -> None:
    print(f"{'속성':<18}{'초기값':>12}{'제어 가능':>12}{'테스트시 반영값':>16}")
    print("-" * 58)
    for r in results:
        status = "O" if r["controllable"] else "X"
        sample = f"{r['sample_value']:.2f}" if r["sample_value"] is not None else "-"
        print(f"{r['name']:<18}{r['baseline']:>12.2f}{status:>12}{sample:>16}")


def live_panel(cap: cv2.VideoCapture, results: list[dict]) -> None:
    controllable = [r for r in results if r["controllable"]]
    if not controllable:
        print("\n제어 가능한 속성이 없어 실시간 패널을 열지 않습니다.")
        return

    name_to_const = {name: const for name, const, _ in PROPS}
    window = "camera control  (q/ESC: quit)"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)

    # 속성별 대략적인 트랙바 범위 (드라이버마다 실제 범위는 다를 수 있음)
    ranges = {
        "BRIGHTNESS": (0, 255), "CONTRAST": (0, 255), "SATURATION": (0, 255),
        "SHARPNESS": (0, 255), "GAMMA": (0, 500), "GAIN": (0, 255),
        "EXPOSURE": (-13, 0), "FOCUS": (0, 255), "IRIS (조리개)": (0, 255),
        "ZOOM": (0, 300), "WB_TEMPERATURE": (2000, 8000),
    }

    for r in controllable:
        lo, hi = ranges.get(r["name"], (0, 255))
        default = int(min(max(r["baseline"], lo), hi))
        offset_default = default - lo
        cv2.createTrackbar(r["name"], window, offset_default, hi - lo, lambda _: None)

    print("\n실시간 제어 패널 실행 중. 트랙바를 움직여 조절하세요. q 또는 ESC로 종료.")
    while True:
        for r in controllable:
            lo, hi = ranges.get(r["name"], (0, 255))
            pos = cv2.getTrackbarPos(r["name"], window)
            cap.set(name_to_const[r["name"]], lo + pos)

        ok, frame = cap.read()
        if ok:
            cv2.imshow(window, frame)

        key = cv2.waitKey(30) & 0xFF
        if key in (ord("q"), 27):
            break

    cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description="USB 카메라 제어 속성 진단")
    parser.add_argument("--index", type=int, default=0, help="카메라 인덱스 (기본 0)")
    parser.add_argument("--backend", choices=BACKENDS.keys(), default="dshow", help="캡처 백엔드")
    parser.add_argument("--live", action="store_true", help="진단 후 실시간 트랙바 제어 패널 열기")
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.index, BACKENDS[args.backend])
    if not cap.isOpened():
        print(f"카메라를 열 수 없습니다 (index={args.index}, backend={args.backend})", file=sys.stderr)
        print("다른 인덱스(0~3)나 backend(dshow/msmf)를 시도해보세요.", file=sys.stderr)
        sys.exit(1)

    for _ in range(5):  # 웜업
        cap.read()

    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"카메라 index={args.index} backend={args.backend} 해상도={int(w)}x{int(h)} fps={fps:.1f}\n")

    results = probe(cap)
    print_report(results)

    if args.live:
        live_panel(cap, results)

    cap.release()


if __name__ == "__main__":
    main()
