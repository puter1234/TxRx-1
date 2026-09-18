# 실물 연결 및 인수 시험

현재 상태는 NOT_VERIFIED다. Windows의 모의 I/O 시험 통과는 J4012·접촉기·모터의 실제 동작 보장이 아니다. 현장 수치가 빈 상태에서 `mode`만 HARDWARE로 바꿔도 운전을 허용하지 않는다.

2026년 9월 18일 추가 요구에 따라 모터, LED, 센서와 카메라를 모두 초기 시험에 포함한다. 이동 중 촬영 요구도 접수했으며 구현 변경은 보류했다. 아래 정지 영상 시험은 현재 코드에 대한 기준이다. 후속 공정 변경 시 해당 기준도 개정한다. 상세 범위는 [J4012_B0478_BRINGUP.md](J4012_B0478_BRINGUP.md)를 따른다.

## 인수인계 v1.1 하드웨어 기준

| 항목 | 기준과 확인 방법 |
|---|---|
| 제어기 | reComputer Industrial J4012, 실제 BSP/L4T/JetPack, USB V4L2와 GStreamer, GPIO 접근 권한 확인 |
| 모터 | 1대, US-52 공장 하네스 유지. 제조사 명판·보호 정격 대조 |
| DI1/DI2 | J2 GPIO line offset 105/144. 검사/배출 역할과 감지 논리는 실측 지정 |
| DI3 | offset 106, KM2 피드백 raw 0 활성. 명령 상태와 별도로 표시 |
| DO1/DO2 | offset 51/52, K1 모터/K2 조명. 실제 ON/OFF raw 극성 미확정 |
| 운전 허가 | 원 배선에 소프트웨어 관측이 충분한지 확인. 추가 입력은 설계 승인 필요. DI4를 임의 배정하지 않음 |
| RFID | USB-TTL YRM1006, 115200 8N1. 실제 3.3V 신호/전원/공통 기준점 확인. EN 고정 구성에는 자동 EN reset 없음 |
| 전원 | PS1 24V/16A 및 12V/5V DC/DC, K0 SAFE24/RUN24. 외부 전압·모터 전류는 측정 센서 없으면 미확인 |
| 카메라 | 2026년 9월 18일 사용자 확인: Arducam B0478 USB UVC. 기존 IMX219 CSI 구현과 연결 방식이 다르며 USB 지원은 미구현. 실제 해상도, FPS, 노출과 초점은 J4012_B0478_BRINGUP.md에 따라 시험 |

`config/station.json`은 엔지니어가 서비스 정지 상태에서 편집하고 릴리스/현장 기록에 해시를 보관한다. HMI는 운전 중 실물 핀 배치를 바꾸지 못한다. 설정의 `signed_by`, `evidence_reference`는 실제 시험 책임자와 기록 경로를 입력해야 한다.

## 기존 제품 검출 라이브러리 연결 계약

검출 라이브러리의 실제 함수 호출만 얇은 Python 모듈로 감싼다. `commissioning.detector_module`과 해당 파일의 SHA256을 지정한다. 모듈은 로컬에서만 모든 자산을 읽어야 한다.

```python
def detect_products(frame_bgr):
    # 사용자 제공 라이브러리에 전달하고 실제 결과를 변환한다.
    # 감지 없음 -> [], 복수 제품 -> 두 개 이상. 임의로 한 개라고 반환하면 안 된다.
    return [{"present": True, "bbox": [x, y, width, height]}]
```

상기 코드는 반환 형식 설명이며 실행 가능한 검출기나 승인 예제가 아니다. 함수가 list를 반환하고 정확히 하나의 `present=True` 제품이어야 검사한다. 어댑터 해시는 연결 파일을 식별한다. 라이브러리 모델/추가 파일도 현장 릴리스 manifest에 별도로 포함해 고정한다.

## RFID 프로토콜 검증

문서에서 고정한 inventory 0x27 및 tag notice 0x22를 사용한다. 나머지 BB/7E 프레임, checksum, PC/EPC 길이, region GET/SET 0x08/0x07, power 0xB6/0xB7, stop 0x28은 현재 구현의 **장비 대조가 필요한 프로토콜 가정**이다. 제공 리더의 정식 명령서와 실제 응답 캡처로 대조하고 필요한 어댑터 수정 후 `rfid_protocol_verified`를 승인한다. 모의 프레임 테스트를 실기 검증으로 간주하지 않는다.

초기화는 region 0x06 SET 후 GET 일치, 출력 2000 SET 후 GET 일치를 요구한다. 해당 수치의 리더 단위와 실제 출력도 리더 명령서로 대조한다. RFID는 정지 상태의 제한 시간창에서 EPC별 횟수·max/median RSSI·first/last 시간을 기록한다. 복수 EPC를 가장 강한 한 개로 임의 선택하지 않고 HOLD한다. 지원 지역·출력 사용 조건은 현장 장비 설정 담당자가 확인한다.

## 실측 후 채울 설정

`settle_ms`, `inspection_timeout_ms`, `feedback_timeout_ms`, `release_timeout_ms`, `product_sensor`, `departure_sensor`, `sensor_clear_ms`, `sensor_active_raw`, `do_on_raw`, `permit_line`, `permit_active_raw`, B0478 장치 식별자와 실제 크기/FPS 및 노출/초점, RFID window, 검출 모듈/해시, 메이커 OCR 영역/신뢰도. USB 카메라 설정 지원을 먼저 구현해야 하며 현재 CSI 설정값만 바꿔 운전하지 않는다.

고정 소프트웨어 보호 시간은 화면 heartbeat 3초, 명령 TTL 3초, I/O lease 기본 500ms다. 이는 실측된 기계 정지시간이 아니다. 타이머 동작과 false trip 여부도 현장 시험에 포함한다. 카메라 시간은 host 수신 시각이며 센서 노출 시각은 현재 제공되지 않는다.

## 단계별 승인 기록

1. 무전원: PE 분기, US-52 하네스, 24/12/5V 회로, 접촉기·과부하·퓨즈 정격, J2 핀 방향, 3.3V TTL 확인.
2. 모터 동력 분리: DO 초기 OFF/서비스 종료 OFF, raw 극성, DI 감지, KM2 ON/OFF 피드백, 별도 운전 허가 접점 실측.
3. 정지 회로: E-STOP 최소 10회, STOP, 과부하, 인터록 상실. K0/KM1/KM2 drop 및 자동 재기동 0회 확인.
4. 고장 주입: 프로세스 강제 종료, OS 정지, 전원 차단/복구, J2/센서 단선, 카메라/USB 분리, RFID timeout/오염 프레임, DB 쓰기 실패/디스크 부족. 소프트웨어와 독립된 하드웨어 OFF 확인.
5. 정지 영상: 이미 위치한 제품에서 START 시 이동 없이 검사, KM2 OFF 후 안정화, 새 프레임, 무제품/복수 제품, 재검사 동일 제품 계수 1회, 배출 순서·센서 해제 확인.
6. 업무 정확도: 실제 제품 최소 1,000건, 정상/불일치/누락/복수태그/반사/흐림/회전/부분가림. 제품·로트·날짜가 분리된 표본으로 False Pass/False Reject/HOLD 비율과 takt 승인.
7. 최소 8시간 연속 운전, 가능하면 72시간. 메모리·파일 핸들·GPU/전원/온도·USB 재연결·WAL/디스크·지연 분포 점검. 서비스 재시작 시 자동 운전 없음 확인.
8. 월간 복원 훈련: DB+증거+설정+모델 해시 확인, 다른 새 디렉터리에 복원, 계수·기준 버전·이미지 조회 대조.

각 시험에 날짜, 빌드 해시, 설정 해시, 측정 도구, 조건, 기대/관측값, 통과 여부, 담당자, 증거 위치를 기록한다. 일반 릴레이/소프트웨어 구성만으로 SIL/PL 또는 산업 안전 인증을 주장하지 않는다. 미승인 체크값을 true로 바꾸어 우회하지 않는다.

구현 참고: [Seeed J40/J30 하드웨어 인터페이스](https://wiki.seeedstudio.com/reComputer_Industrial_J40_J30_Hardware_Interfaces_Usage/), [libgpiod request API](https://libgpiod.readthedocs.io/en/v2.3/python_line_request.html), [pySerial API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html). 실제 핀과 구성의 기준 문서는 제공된 v1.1이다.
