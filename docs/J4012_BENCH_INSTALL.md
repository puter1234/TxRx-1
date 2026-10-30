# J4012 장비 시험 설치

사용자가 확인한 환경: R36, REVISION 4.0, GCID 37537400, aarch64, Python 3.10.12. Jetson Linux 36.4.0 기반이다. 초기 설치 중 인터넷 연결이 가능하다고 확인했다.

## 포함 범위

`txrx-j4012-bench-20260918.zip` 하나에 최신 실행 코드, 빌드된 화면, 기존 PARSeq 모델, 개별 장비 시험용 ARM64 Python 패키지가 들어 있다. 앞서 제공한 transfer ZIP 대신 이 파일을 새 폴더에 푼다.

카메라, 센서, LED, 모터와 RFID 개별 시험을 위한 설치다. OCR 실행은 같은 가상환경에서 `python3 scripts/install_ocr_jetson.py`를 추가 실행한다. 이 설치 단계에서만 인터넷을 사용하며, 실제 장치 호환은 J4012에서 설치와 연결 시험을 진행하면서 확인해야 한다.

기존 OpenCV와 같은 4.11.0 버전의 화면 창을 띄우지 않는 배포판을 별도 가상환경에 설치한다. 영상은 앱의 웹 화면에 표시한다. 기존 OCR 알고리즘과 모델을 변경하지 않는다. GPU AI 환경은 설치된 CUDA와 cuDNN을 확인한 뒤 별도로 맞춘다.

## 1. Ubuntu 기본 도구 설치

J4012 터미널에서 실행한다. 운영체제 전체 업그레이드나 재플래시는 하지 않는다.

```bash
sudo apt update
sudo apt install -y python3.10-venv v4l-utils usbutils unzip
```

## 2. ZIP 복사와 압축 해제

ZIP과 `.zip.sha256` 파일을 USB 저장장치 등으로 J4012 다운로드 폴더에 복사한다. 아래 예시는 `~/Downloads`이며 실제 폴더 이름에 맞게 바꾼다. 기존 폴더가 있으면 다른 새 폴더 이름을 사용한다.

```bash
cd ~/Downloads
sha256sum -c txrx-j4012-bench-20260918.zip.sha256
unzip txrx-j4012-bench-20260918.zip -d ~/TxRx-1-bench
cd ~/TxRx-1-bench
python3 scripts/install_bench.py
```

설치 스크립트는 Linux ARM64와 Python 3.10을 확인하고 압축 파일 목록의 SHA256을 검증한다. `.venv-bench`에 포함된 패키지만 해시를 확인하여 설치한다. 인터넷 다운로드, 모델 실행, GPIO 출력과 카메라 열기는 하지 않는다. 설치 완료 문구는 소프트웨어 의존성 확인 결과이며 실물 시험 결과가 아니다.

## 3. 장치 접근 권한 설정

일반 사용자 터미널에서 다음 한 줄만 sudo로 실행한다. 앱 서버와 Python 패키지 설치는 sudo로 실행하지 않는다.

```bash
sudo python3 scripts/setup_jetson_access.py
```

이 스크립트는 현재 사용자를 video, dialout, gpio 그룹에 추가하고 `/dev/gpiochip0`에 해당 그룹의 접근 권한을 부여한다. GPIO 입력과 출력을 요청하지 않는다. 실제 장치가 다른 gpiochip에 있으면 임의로 권한 범위나 핀 번호를 늘리지 말고 해당 BSP와 배선을 확인한다.

권한을 적용하려면 Ubuntu에서 로그아웃한 뒤 다시 로그인한다.

## 4. 실행

```bash
cd ~/TxRx-1-bench
python3 scripts/run_bench.py
```

화면은 다른 터미널에서 `./open-screen.sh`로 연다. Google Chrome을 그래픽 가속 없이 열어 `http://127.0.0.1:8000/`에 접속한다. J4012의 Chrome은 그래픽 가속을 켜면 화면을 다시 그리지 않아 누른 버튼이 보이지 않는다. Windows 브라우저의 같은 주소는 Windows 서버를 가리킨다. 서버 터미널은 열어 둔다.

처음 환경 설정에 들어가면 사용할 비밀번호를 설정한다. 기존 PC와 같은 값을 쓰려면 `123456`으로 지정한다. Windows의 운영 DB와 비밀번호 및 화면에서 변경한 설정은 이 묶음에 포함하지 않았다.

장비 설정은 `runtime/station-local.json`이며 mode는 HARDWARE다. 예전 설치로 REPLAY가 남아 있으면 `scripts/run_bench.py`가 처음 한 번 HARDWARE로 바꾸고, 실행할 때 사용 중인 mode를 출력한다. 서버가 켜질 때 J2 입출력을 열고, 옷 계수 같은 작업이 실제 모터와 DI1, DI2로 돈다. 이 보드의 문서상 배선(RUN24 상시 연결, 출력 1에서 켜짐, 접촉기 응답 3초)을 기본으로 쓰며, 설정 파일에 값을 적으면 그 값이 우선한다. 장비 시험 화면도 같은 입출력을 빌려 실제 출력을 조작한다. 사진으로만 시험하려면 이 파일의 mode를 REPLAY로 바꾸고 서버를 다시 켠다. 그 뒤로는 다시 바뀌지 않는다.

## 5. 첫 시험

1. 카메라를 USB 3 호스트 포트에 연결한다. 환경 설정의 시험 화면에서 화질 탭을 열고 카메라를 고르면 바로 켜진다. 처음에는 실제 지원 목록의 1920×1080 해상도를 사용한다.
2. 영상이 들어오면 촬영 거리에서 초점과 노출을 맞춘다. 바꾸는 즉시 저장된다. 사진 찍기로 원본 사진을 촬영한다.
3. 화면 상단의 센서 1과 센서 2가 감지와 없음으로 바뀌는지 센서를 가리고 치우며 확인한다. 입력은 화면을 열면 자동으로 연결되며 이 단계에서는 출력 설정이 필요 없다.
4. 배선과 출력 극성, 물리 정지 회로, 운전 허가와 접촉기 피드백을 확인한 다음 LED와 모터를 시험한다. 모터 동력을 분리한 릴레이 시험부터 시작한다. 실제 가동은 0.5초부터 시작한다.
5. RFID 탭에서 태그 읽기를 누른다. 리더 포트는 자동으로 찾으며 USB 직렬 장치가 여러 개일 때만 고른다.

출력 시험의 확인 항목에 임의값을 넣지 않는다. LED는 켜기와 끄기이며 모터 속도는 기존 US-52에서 조절한다. 자세한 시험 순서는 [이관 및 장치 시험 안내](J4012_TRANSFER.md)의 5번부터 따른다.

시험을 끝내면 시험 전체 정지를 누르고 실제 출력을 확인한 뒤 서버 터미널에서 Ctrl+C로 종료한다.

## 문제 발생 시

실패한 명령의 마지막 오류 문구를 그대로 기록한다. 설치 실패를 이유로 시스템 Python이나 JetPack을 임의로 바꾸지 않는다. 포트 접근 거부면 로그아웃과 재로그인 여부를 먼저 확인한다. GPIO 번호, 극성과 허가 조건 오류는 실제 배선 및 BSP 확인이 필요한 항목이다.

이 묶음은 ARM64 패키지 목록과 의존성을 확인한 상태다. 실제 J4012에서 설치, 카메라 영상, GPIO와 RFID는 아직 시험하지 않았다. 이번 개별 장비 시험은 최종 생산 운전 승인이나 보류된 이동 중 촬영 구현을 대신하지 않는다.

## AI 설치를 위해 추가로 확인할 내용

장비 시험 서버를 먼저 띄운 뒤 다음 결과로 실제 설치된 GPU 패키지를 확인한다. L4T 버전만으로 CUDA와 cuDNN 설치 완료를 판단하지 않는다.

```bash
dpkg-query -W 'cuda-cudart-*' 'libcudnn*' 'libcusparselt*'
```

해당 패키지가 없다는 메시지도 그대로 남긴다. 기존 requirements.txt의 일반 CUDA 설치 예시는 Jetson용 설치 명령으로 사용하지 않는다.

[NVIDIA Jetson Linux 36.4](https://developer.nvidia.com/embedded/jetson-linux-r3640)

[NVIDIA Jetson PyTorch 설치 안내](https://docs.nvidia.com/deeplearning/frameworks/install-pytorch-jetson-platform/index.html)
