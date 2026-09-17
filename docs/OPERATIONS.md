# 로컬 운영·복구

## 권한

최초 계정은 admin이며 사용자가 비밀번호를 만든다. 비밀번호는 scrypt hash/salt로 저장한다. 세션은 12시간이며 재시작하면 다시 로그인한다. 로그인 실패는 시간 제한을 적용한다.

| 역할 | 허용 |
|---|---|
| 작업자 | 작업 생성·시작·정지·조회·합격 배출·작업 종료 |
| 엔지니어 | 작업자 기능 + fault reset·불합격 제거 확인·수량 보정·OCR 영역/임계값 변경 |
| 관리자 | 엔지니어 기능 + 메이커 master·사용자 관리·DB 백업 |

모든 운전 명령은 request ID로 중복 실행을 막는다. 요청 응답을 잃으면 `/api/commands/{id}`에서 처리 여부를 조회한다. 상태 버전이 바뀌거나 실물 운전 명령이 3초 이상 지연되면 재요청을 요구한다. 정지 요청은 상태 버전 검사 전에 출력을 먼저 OFF한다. fault reset은 모터를 켜지 않는다.

## 현장 시작과 종료

1. 전원·정지 회로와 장비 상태를 확인한다. J4012 자동 서비스 설치는 현장 승인 이후 수행한다.
2. `run-station.ps1` 또는 `python -m station`을 실행한다. loopback 단일 worker를 유지한다. reload/multiple workers는 사용하지 않는다.
3. 로그인 후 장비 정보·blockers 확인, 목표 작업 생성, 물리 START와 화면 운전 준비를 순서에 맞춰 조작한다.
4. HOLD/FAULT 시 제품과 장비를 확인한다. 제거했다면 제거 확인, 재검사라면 오류 해제 후 같은 제품을 사용한다. 수량 보정은 별도 사유로 기록한다.
5. 작업을 종료하고 서버를 정상 종료한다. 정상 종료와 전원 복구 모두 자동 운전을 하지 않는다.

화면 연결이 끊기면 마지막 수집 시각과 OFFLINE을 표시한다. 실물 이송·검사 중 heartbeat가 사라지면 FAULT/OFF한다. 브라우저 백그라운드 절전 등으로 heartbeat가 중단될 수 있으므로 현장 운전 화면의 절전 조건도 시험한다. 앱을 자동으로 인터넷에 공개하거나 방화벽을 개방하지 않는다.

## 데이터와 백업

운영 데이터 기본 경로는 프로젝트의 `runtime/`; `TXRX_DATA`로 지정할 수 있다. 설정은 `TXRX_CONFIG`로 지정한다. 검사별 PNG와 업로드 원본, 입력/증거 SHA256, 기준표 snapshot/hash, 사용자·시간·시도·판독·실패 이유·계수·수동 보정을 남긴다. 사진 검증은 REPLAY, 실물은 HARDWARE로 구분된다.

매일 정지/대기 중 SQLite online backup과 integrity_check를 수행한다. 장비 정보 화면의 DB 백업도 같은 방식이다. **이 버튼과 자동 백업은 DB만 포함**한다. 전체 증거 복구에는 아래 archive를 사용하고 config와 릴리스 ZIP을 함께 보관한다.

```powershell
# 서버를 정상 종료한 후 실행. 대상 ZIP/복원 디렉터리는 새 경로여야 한다.
.\.venv\Scripts\python.exe scripts/archive_data.py backup runtime D:/backup/txrx-20260917.zip
.\.venv\Scripts\python.exe scripts/archive_data.py restore D:/backup/txrx-20260917.zip D:/txrx-restored
```

복원은 기존 데이터를 덮어쓰지 않는다. 새 디렉터리의 DB/증거 해시·무결성 검사를 통과한 후 `TXRX_DATA`를 새 위치로 지정한다. 복원된 진행 작업은 재시작 시 ABORTED로 전환하며 수동 검토 후 새 작업을 만든다. 매주 로컬 외장 저장장치에 복사하고 월 1회 복원 훈련한다. 외부 서버는 필요 없다. 보존 기간을 승인하기 전에는 이미지를 자동 삭제하지 않는다. 여유 용량 10% 미만 또는 설정된 최소 용량 미만이면 새 검사를 차단한다.

## 배포와 업데이트

`scripts/build_release.py --wheelhouse wheelhouse`는 현재 소스·모델·frontend dist·설정·Python wheel을 해시 manifest와 ZIP으로 묶는다. 개인용 헤지스 초기 기준표가 ZIP에 포함될 수 있으므로 이 배포물을 공개 저장소에 올리지 않는다. 실행 기록·비밀번호·원본 사진 폴더는 배포 ZIP에 포함하지 않는다.

```powershell
.\.venv\Scripts\python.exe scripts/verify_release.py
.\.venv\Scripts\python.exe scripts/doctor.py
```

manifest는 손상·버전 혼합을 검출하는 해시 목록이며 디지털 서명은 아니다. 신뢰하는 로컬 배포물만 사용한다. 새 릴리스는 다른 폴더/NVMe에서 인식 회귀·고장 시험 후 전환한다. 이전 ZIP과 운영 백업을 보존한다. JetPack/BSP/CUDA 조합은 개별 pip 갱신으로 교체하지 않는다. J4012에서 MAXN SUPER는 활성화하지 않는다.

Jetson 서비스 예제는 `deploy/txrx-station.service`다. 무로그인 txrx 계정, 필요한 그룹만 부여하고 sudo 권한을 주지 않는다. GPIO 그룹/udev 이름은 현장 실제 구성으로 검증한다. 서비스 예제는 자동 설치하지 않았다. systemd journal의 공간/보존 설정은 현장 보존 정책에 맞춰 제한한다. TPM/Secure Boot/디스크 암호화는 복구 키 보관과 함께 별도 승인한다.

## 사용자 검토 순서

브라우저 직접 검토는 사용자 지시 전까지 수행하지 않았다. 사용자가 검토할 때 로그인, 목표 옵션 추가/삭제, 목표 선택, 정상/미판독/불일치, HOLD 복구, 같은 제품 재검사, 수동 보정, 권한별 제한, 이력/증거, DB 백업 순으로 확인하면 된다. 실물 모드는 현장 인수 시험 전 활성화하지 않는다.
