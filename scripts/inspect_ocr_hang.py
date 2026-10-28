"""Read the running station's stacks without restarting or changing its settings."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    targets = []
    for proc in psutil.process_iter(['pid', 'cmdline', 'cwd']):
        try:
            args = proc.info['cmdline'] or []
            if proc.info['pid'] == os.getpid() or proc.info['cwd'] != str(ROOT):
                continue
            if 'uvicorn' in args and 'station.app:create_app' in args:
                targets.append(proc.info['pid'])
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    if len(targets) != 1:
        raise SystemExit(f'실행 중인 서버를 하나로 특정하지 못했습니다. 발견된 PID: {targets}')
    tool_dir = Path(tempfile.mkdtemp(prefix='txrx-stack-tool-'))
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--target', str(tool_dir),
                    '--disable-pip-version-check', 'py-spy==0.4.1'], check=True)
    tool = tool_dir / 'bin/py-spy'
    # Native unwinding is not supported by py-spy on Jetson ARM64.
    # Python stacks still identify the model call or lock that is waiting.
    command = [str(tool), 'dump', '--pid', str(targets[0])]
    if os.geteuid() != 0:
        command.insert(0, 'sudo')
    output = ROOT / 'runtime' / ('ocr-hang-' + time.strftime('%Y%m%d-%H%M%S') + '.txt')
    output.parent.mkdir(exist_ok=True)
    with output.open('w') as report:
        for attempt in range(3):
            report.write(f'\nCapture {attempt + 1}, PID {targets[0]}\n')
            report.flush()
            result = subprocess.run(command, stdout=report, stderr=subprocess.STDOUT)
            if result.returncode:
                raise SystemExit(f'실행 위치 수집 실패. 상세 내용: {output}')
            if attempt < 2:
                time.sleep(1)
    print(f'실행 위치 기록: {output}')
    print(output.read_text())


if __name__ == '__main__':
    main()
