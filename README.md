# TXRX 정지 검사 스테이션 · 0.3.0

컴퓨터 한 대에서 화면, OCR/RFID/선택형 바코드 판정, 장비 제어, 검사 기록을 처리한다. 외부 서버·CDN·모델 다운로드 없이 실행한다. 현장 장비가 아직 조립 중이므로 기본 설정은 **REPLAY(사진 검증, 실물 출력 없음)** 이다. 브라우저 자동 실행 기능은 없다.

## 실행

현재 PC에서는 프로젝트 폴더에서 다음 명령을 실행한다. 서버만 실행하며 화면은 사용자가 직접 `http://127.0.0.1:8000`에 접속한다.

```powershell
.\run-station.ps1
```

최초 접속 시 `admin` 계정의 비밀번호를 직접 설정한다. 공용 기본 비밀번호는 없다. 사용자 관리에서 작업자·엔지니어 계정을 추가할 수 있다. 8000번 포트가 사용 중이면 `-Port 8017`처럼 다른 포트를 지정한다. 동시에 같은 운영 데이터로 두 서버를 실행하지 않는다.

배포 ZIP을 새 폴더에 풀어 설치하는 경우 Windows x64 Python 3.11이 로컬에 있어야 한다. 포함된 wheelhouse만 사용하며 설치 중 인터넷을 요청하지 않는다.

```powershell
.\install-offline.ps1
.\run-station.ps1
```

`run-station.ps1`은 `.venv`, 다음으로 이 PC에서 검증한 `.venv-offline-verified`를 찾는다. 다른 환경은 `-PythonPath`로 지정한다. Windows 패키지를 Jetson에 설치하면 안 된다. Jetson의 L4T/JetPack, CUDA, GStreamer OpenCV와 ARM64 패키지 조합은 실물 확인 후 별도로 고정한다.

## 운전과 판정

1. 설정에서 메이커와 품번·색상·사이즈·사용자 정의 옵션을 추가한다. 헤지스 표본 기준은 로컬 초기 데이터로 준비했다. 다른 메이커는 EPC/바코드 기준표 JSON을 가져온다.
2. OCR을 사용하면 옵션별 정지 이미지 영역과 회전각을 지정한다. 생산용 최소 문자 신뢰도는 실측해서 정한다. 영역을 임의로 채우지 않는다.
3. 검사 운전에서 각 옵션의 목표값을 하나씩 선택하고 검사 채널을 선택한다. **바코드는 기본 미선택**이다. 실물 운전은 OCR과 RFID를 모두 요구하며, 사진 검증에서는 채널을 개별 시험할 수 있다.
4. 사진 검증은 제품 ID, 이미지, 관측 EPC를 입력한다. 실물 모드는 센서·제품 검출기·정지 피드백을 사용하며 수동 이미지 주입이 금지된다.
5. 선택한 모든 채널에서 모든 목표를 읽고 일치해야 합격한다. 미판독·불일치·복수 RFID 등은 HOLD이며 자동으로 재출발하지 않는다.
6. 제품 하나는 한 번만 계수한다. 재검사는 같은 제품 ID의 새 시도로 기록한다. 합격 후 배출 확인이 있어야 다음 제품으로 넘어간다. 수량 보정은 엔지니어/관리자가 사유를 남겨 수동 처리한다.

작업 중 기준표는 변경할 수 없다. 작업은 시작 당시 기준표·버전·해시를 보존한다. 화면 정지는 소프트웨어 요청이며 실제 비상정지 회로를 대신하지 않는다.

## 실제 기술 스택

| 영역 | 적용 |
|---|---|
| 화면 | React 18, TypeScript, Vite 6, Tailwind, 로컬 Pretendard |
| 서버/상태 | Python 3.11, FastAPI, Uvicorn 단일 worker, 인증된 WebSocket |
| 인식 | 기존 PARSeq + PyTorch, OpenCV, zxing-cpp 유지. 로컬 소스·가중치 해시 검증 |
| 판정 | 옵션별 정확 일치, CRC8/6-bit 헤지스 해독, 다른 메이커 명시적 기준표 |
| 기록 | SQLite WAL/FULL, 제품 중복 방지, 명령 멱등성, 증거 PNG/원본, 감사 이력 |
| 실물 연결 | libgpiod 2.x J2, USB-TTL YRM 계열 UART, CSI GStreamer, 기존 제품 검출기 어댑터 |
| 검증 | pytest, 실제 기존 사진 회귀, jsdom/Vitest. 브라우저 시각 검사는 미실시 |

문서에서 제안한 YOLO/Paddle/DeepStream 기반 인식으로 교체하지 않았다. 바코드가 없는 검사에는 고정 촬영 영역을 PARSeq에 입력하는 경로를 추가했다. 기존 태그 추출·문자 인식 회귀 경로는 보존했다. 단일 PC 서비스 내부에서 I/O 소유권을 하나로 유지한다.

## 파일과 운영 자료

- `station/`: 운영 서버, 판정, SQLite, 장비 어댑터
- `ocr/frontend/src/station/`: 현재 사용하는 운전/설정/장비/이력/계정 화면
- `ocr/core.py`, `tagreader/`, `pipeline.py`: 기존 검증 인식 코드
- `reference/legacy_frontend/`, `reference/legacy_hmi_backend.py`: 사용하지 않는 이전 목업 보관
- `models/parseq/`: 로컬 모델과 소스 및 해시 목록. Git 제외, 배포 ZIP 포함
- `runtime/`: DB·증거·백업. Git 제외
- `config/station.json`: 실측값과 현장 승인. 기본값은 미확정/실물 운전 차단
- [운영·복구 절차](docs/OPERATIONS.md)
- [장비 연결·인수 시험](docs/HARDWARE_ACCEPTANCE.md)
- [사용자 확정 사항과 적용 범위](docs/DECISIONS_2026-09-17.md)
- [구현·검증 보고](docs/IMPLEMENTATION_STATUS.md)

## 개발 검증

```powershell
.\.venv-offline-verified\Scripts\python.exe -X utf8 -m pytest tests tests_station -q
npm --prefix ocr/frontend run build
npm --prefix ocr/frontend test
.\.venv-offline-verified\Scripts\python.exe -X utf8 scripts/doctor.py
```

소스에서 프론트엔드를 다시 빌드하려면 Node/npm과 잠금 파일에 해당하는 개발 패키지가 필요하다. 운영 배포에는 빌드 결과가 포함되므로 Node/npm이 필요하지 않다. 원본 고객 표본·촬영 사진·모델·운영 데이터는 원격 Git에 올리지 않는다. `origin`은 요청한 `puter1234/TxRx-1`이며 원격 push는 수행하지 않았다.
