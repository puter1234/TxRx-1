# LED 단독 시험

장비 점검에서 LED 끄기를 먼저 누른다. 입력 연결이 없으면 입력을 연결하고 DO2만 출력으로 확보해 OFF를 전송한다. DO1은 확보하거나 변경하지 않는다. 10초 후 LED 켜기로 지정 시간 동안 점등한다. LED 끄기는 즉시 실행된다.

REV 1.1 문서 13쪽과 15쪽의 배선은 GPIO 52 -> J2 핀11 DO2 -> K2 A2, K2 NO -> LED다. Seeed J40 공식 DO 사용법은 GPIO 1을 부하 ON으로 안내한다. 따라서 /dev/gpiochip0, DO=[51,52] 기본 배선에서만 미설정 LED 극성을 ON=1, OFF=0으로 해석한다. 명시적으로 설정한 do_on_raw가 있으면 그 설정을 우선한다. 사용자 배선이 문서와 다르면 이 기본값을 그대로 적용하면 안 된다.

근거: https://wiki.seeedstudio.com/reComputer_Industrial_J40_J30_Hardware_Interfaces_Usage/#usage-for-do

LED 단독 시험은 모터 운전 허가 및 모터 시운전 설정을 요구하지 않는다. 연결 오류, DI3 접촉기 켜짐, 생산 작업 중, 다른 출력 시험 중에는 켜기를 차단한다. 모터 시험의 기존 시운전 조건은 유지한다.

전송 성공은 실제 소등 계측이 아니다. GPIO OFF 전송 후에도 LED가 켜져 있으면 K2 보조 표시와 문서의 COM/NO 접점 배선을 확인한다. 접속 종료 후 GPIO가 해제된 상태의 전기적 기본값은 소프트웨어가 보장하지 않는다.
