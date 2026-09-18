# TXRX 정지 검사 스테이션

한 컴퓨터에서 화면, OCR, RFID, 선택형 바코드 검사와 기록을 처리한다. 운영 시 외부 서버, 모델 다운로드, CDN이 필요하지 않다. 현재 장비는 조립 중이며 기본 실행은 사진 시험 모드다.

## 실행

```powershell
.\run-station.ps1
```

화면은 사용자가 http://127.0.0.1:8000 에 접속한다. 서버가 브라우저를 자동으로 열지 않는다. 원래 메인 화면에서 단순 계수 또는 조건 계수를 선택한다. 환경 설정을 열 때만 비밀번호를 입력하며 계정 생성이나 역할 선택은 없다. 이미 설정한 비밀번호는 유지된다.

설치된 Python은 .venv, .venv-offline-verified 순서로 찾는다. 다른 환경은 -PythonPath로 지정한다. 같은 운영 데이터로 서버 두 개를 실행하지 않는다. 다른 포트는 -Port 8017과 같이 지정한다.

## 사용하는 순서

1. 환경 설정의 브랜드 관리에서 기준표와 옵션을 등록한다. 기존 헤지스 표본을 제공했고 다른 브랜드는 제공받은 JSON 기준표를 가져온다.
2. 조건 계수에서 브랜드와 검사 항목, 수량, 옵션별 목표값을 차례로 선택한다. 목표값은 큰 버튼 중 하나를 누른다. 색상 코드는 환경 설정의 브랜드 관리에서 실제 색상을 지정할 수 있다. 바코드는 기본 미선택이다.
3. 검사 화면에서 시작한다. 사진 시험은 사진으로 시험 버튼을 열어 실제 사진과 읽은 RFID 값을 넣는다. 제품 번호는 자동으로 유지한다.
4. 미판독이나 불일치가 있으면 정지한다. 제품을 확인한 뒤 조치 확인에서 사유를 남긴다. 오류 해제만으로 재출발하지 않는다.
5. 합격 후 다음 제품으로 넘어간다. 수량 보정은 수동이며 사유를 기록한다. 작업 기록에서 이전 조건, 개별 검사 사진과 판독 결과를 확인한다.

단순 계수도 제품 하나를 한 번만 센다. 실물 모드에서는 단순 계수 역시 제품 검출, 정지 피드백과 현장 운전 확인을 우회하지 않는다. 설정의 통과 사진 저장을 끄면 이후 작업에서 합격 사진은 검사 후 남기지 않으며 실패 사진과 판독 기록은 보존한다.

## 구현과 검증 범위

화면은 사용자 원본의 메인, 메뉴, 3단계 설정과 작업 화면 구조를 복구하고 실제 서버에 연결했다. 필요한 설명은 오른쪽 i 도움말에 배치했다. 계정 관리 화면은 사용하지 않는다.

React 18, React Router 6, Zustand 5, TypeScript, Vite 6, Tailwind와 로컬 Pretendard를 사용한다. 서버는 FastAPI, 단일 Uvicorn 프로세스와 SQLite다. 검증된 PARSeq, OpenCV, zxing-cpp와 기존 태그 추출 코드를 유지한다.

고정 OCR 영역으로 옵션을 읽는 추가 경로는 사용자 합의가 끝나지 않았다. 기존 바코드 주변의 인쇄 번호 추출과 품번, 색상, 사이즈 자동 판독은 같은 기능이 아니다. 영역 설정은 세부 설정에 보관하며 최종 생산 방식으로 확정하지 않는다.

브라우저나 스크린샷을 통한 직접 검토는 사용자 지시 전까지 하지 않는다. 기능 시험과 실물 승인 결과를 구분한다. 실제 장비, 정지 회로, 검출 라이브러리 연결과 현장 실측이 끝나기 전에는 생산 운전 준비 완료로 표시하지 않는다.

## 소스와 자료

| 경로 | 용도 |
|---|---|
| ocr/frontend/src/screens, components, lib | 현재 사용하는 원본 기반 화면과 서버 연결 |
| ocr/frontend/src/station | 공유 API, 브랜드 설정, 장비 상세 정보와 회귀 시험 |
| reference/legacy_frontend | 수정하지 않은 원본 화면 비교 기준 |
| station | 운영 서버, 판정, 저장과 장비 어댑터 |
| ocr/core.py, tagreader, pipeline.py | 기존 인식 코드 |
| models/parseq | 로컬 모델과 소스 해시 목록 |
| runtime | 로컬 DB, 사진과 백업 |
| config/station.json | 실측 설정과 장비 운전 승인 |

[복구 대조표와 검증 루프](docs/RESTORATION_CHECKLIST.md), [최신 검증 보고](docs/IMPLEMENTATION_STATUS.md), [운영 절차](docs/OPERATIONS.md), [실물 인수 시험](docs/HARDWARE_ACCEPTANCE.md)을 함께 확인한다.

```powershell
.\.venv-offline-verified\Scripts\python.exe -X utf8 -m pytest tests tests_station -q -k 'not test_within_time_budget'
npm --prefix ocr/frontend test
npm --prefix ocr/frontend run build
.\.venv-offline-verified\Scripts\python.exe -X utf8 scripts/smoke_local.py
.\.venv-offline-verified\Scripts\python.exe -X utf8 scripts/doctor.py
```

기존 400ms 속도 제한 시험은 별도 성능 항목이다. 기능 통과가 처리량 보장을 의미하지 않는다. Windows 배포 묶음에는 로컬 Python 설치용 wheelhouse를 포함한다. J4012 ARM64와 JetPack 설치물은 실물 환경 확인 후 별도로 고정해야 한다.

Git origin은 https://github.com/puter1234/TxRx-1.git 이다. 고객 원본 JSON, 사진, 가중치, 운영 DB와 배포 ZIP은 Git에서 제외한다. 원본 G: 디렉터리는 변경하지 않는다.
