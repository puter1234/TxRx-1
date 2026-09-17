# 이전 프로토타입 설명 — 현재 실행 방법은 상위 README 참고

현재 운영 진입점은 프로젝트 루트의 `run-station.ps1`과 `station` 패키지다. 아래 내용은 이전 목업의 기록이다. 활성 프론트엔드는 `frontend/src/station/`, 이전 모의 화면/백엔드는 `reference/`로 분리했다. 더 이상 모의 통과 이벤트를 생산 기록으로 사용하지 않는다.

의류 컨베이어 자동 계수/검사 HMI. 완전 오프라인 동작을 전제로 하며,
현재는 하드웨어 없이 백엔드 시뮬레이터가 통과 이벤트를 생성한다.

## 구조

- frontend/  React 18 + TypeScript + Vite + Tailwind (Pretendard 로컬 번들)
- backend/   FastAPI — REST + WebSocket + MJPEG 모의 스트림 + 정적 파일 서빙
- backend/data/  브랜드·설정·날짜별 계수 결과(results/YYYY-MM-DD)·작업 로그(logs)

## 실행 (개발)

터미널 1 — 백엔드:

    cd backend
    python main.py            # http://localhost:8000

터미널 2 — 프론트 (핫리로드):

    cd frontend
    npm install
    npm run dev               # http://localhost:5173 (API는 8000으로 프록시)

## 실행 (통합)

    cd frontend && npm run build
    cd ../backend && python main.py
    # 브라우저에서 http://localhost:8000 접속

## 기본값

- 환경 설정 비밀번호: 0000
- 계수 결과: backend/data/results/YYYY-MM-DD/ (job JSON + 통과 사진)
- 작업 로그: backend/data/logs/YYYY-MM-DD.log
