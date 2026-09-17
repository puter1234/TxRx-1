# -*- coding: utf-8 -*-
"""TXRX 자동 계수 시스템 — 프로토타입 백엔드.

FastAPI 하나가 REST API + WebSocket + MJPEG 스트림 + 빌드된 프론트 정적 파일을 모두 서빙한다.
하드웨어(카메라·광센서·RFID·컨베이어)가 아직 없으므로 시뮬레이터가 통과 이벤트를 생성한다.
완전 오프라인 동작: 외부 요청 없음, 모든 데이터는 backend/data 아래 날짜별 폴더에 저장.
"""
import asyncio
import io
import json
import random
import string
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
DATA = BASE / "data"
RESULTS = DATA / "results"   # 날짜별 계수 결과 (job json + 통과 사진)
LOGDIR = DATA / "logs"       # 날짜별 작업 로그
for d in (DATA, RESULTS, LOGDIR):
    d.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = DATA / "config.json"
BRANDS_FILE = DATA / "brands.json"

DEFAULT_CONFIG = {"password": "0000", "save_photos": True, "threshold": 55}
SEED_BRANDS = [
    {"id": "titleist", "name": "타이틀리스트", "caps": {"rfid": False, "ocr": True, "barcode_tag": True, "barcode_poly": False}},
    {"id": "beanpole", "name": "빈폴", "caps": {"rfid": False, "ocr": True, "barcode_tag": True, "barcode_poly": True}},
    {"id": "hazzys", "name": "헤지스", "caps": {"rfid": True, "ocr": True, "barcode_tag": True, "barcode_poly": True}},
    {"id": "briefing", "name": "브리핑", "caps": {"rfid": False, "ocr": True, "barcode_tag": True, "barcode_poly": False}},
    {"id": "taylormade", "name": "테일러메이드", "caps": {"rfid": False, "ocr": True, "barcode_tag": True, "barcode_poly": True}},
    {"id": "boss", "name": "BOSS", "caps": {"rfid": True, "ocr": True, "barcode_tag": True, "barcode_poly": False}},
    {"id": "pxg", "name": "PXG", "caps": {"rfid": False, "ocr": True, "barcode_tag": True, "barcode_poly": False}},
]


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
    return json.loads(json.dumps(default))


config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
brands = load_json(BRANDS_FILE, SEED_BRANDS)


def save_config():
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def save_brands():
    BRANDS_FILE.write_text(json.dumps(brands, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- 상태
state = {
    "devices": {"camera": "ok", "sensor": "ok", "rfid": "ok", "conveyor": "idle"},
    "pipeline": {"infeed": "idle", "sensor": "idle", "camera": "idle", "rfid": "idle", "conveyor": "idle", "outfeed": "idle"},
    "session": {
        "mode": None, "status": "idle", "count": 0,
        "startedAt": None, "lastPassAt": None, "config": None, "mismatch": None,
    },
}
clients = set()
recent_logs = []
sim_task = None
last_job = None  # 목표 도달 시 자동 저장된 작업 (종료 시 안내용)

app = FastAPI(title="TXRX 자동 계수 시스템")


def now_ts():
    return datetime.now().strftime("%H:%M:%S")


def public_state():
    return {
        **state,
        "settings": {
            "save_photos": config["save_photos"],
            "threshold": config["threshold"],
            "data_dir": str(DATA),
        },
    }


async def broadcast(msg: dict):
    text = json.dumps(msg, ensure_ascii=False)
    dead = []
    for ws in list(clients):
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


async def push_state():
    await broadcast({"type": "state", "state": public_state()})


async def log(text: str, kind: str = "info"):
    item = {"ts": now_ts(), "text": text, "kind": kind}
    recent_logs.append(item)
    del recent_logs[:-200]
    day = datetime.now().strftime("%Y-%m-%d")
    with open(LOGDIR / (day + ".log"), "a", encoding="utf-8") as f:
        f.write("[" + item["ts"] + "] [" + kind.upper() + "] " + text + "\n")
    await broadcast({"type": "log", "item": item})


# ---------------------------------------------------------------- 프레임 렌더링 (모의 카메라)
_font_cache = {}


def get_font(size: int):
    if size not in _font_cache:
        try:
            _font_cache[size] = ImageFont.truetype("malgun.ttf", size)
        except Exception:
            _font_cache[size] = ImageFont.load_default()
    return _font_cache[size]


def render_frame(w: int = 640, h: int = 360) -> Image.Image:
    t = time.time()
    img = Image.new("RGB", (w, h), (23, 29, 43))
    d = ImageDraw.Draw(img)

    running = state["session"]["status"] == "running" or state["pipeline"]["conveyor"] == "active"

    # 벨트
    belt_top, belt_bottom = h - 130, h - 44
    d.rectangle([0, belt_top, w, belt_bottom], fill=(52, 61, 82))
    offset = int(t * 90) % 48 if running else 0
    for x in range(-48 + offset, w + 48, 48):
        d.line([(x, belt_bottom - 4), (x + 26, belt_top + 4)], fill=(70, 80, 104), width=3)

    # 의류 (가동 중일 때 이동)
    if running:
        sx = int(t * 110) % (w + 220) - 110
        sy = belt_top - 34
        d.rounded_rectangle([sx, sy, sx + 130, sy + 96], radius=10, fill=(34, 67, 122))
        d.rounded_rectangle([sx + 34, sy + 12, sx + 96, sy + 40], radius=5, fill=(240, 242, 246))
        d.rectangle([sx - 10, sy - 10, sx + 140, sy + 106], outline=(47, 107, 255), width=3)
        label_font = get_font(15)
        d.text((sx - 8, sy - 32), "의류", font=label_font, fill=(120, 165, 255))

    # 계수 임계선
    tx = int(w * config["threshold"] / 100)
    for y in range(0, h, 16):
        d.line([(tx, y), (tx, y + 8)], fill=(232, 162, 0), width=3)

    # 상단 정보 바
    d.rectangle([0, 0, w, 34], fill=(12, 16, 26))
    font = get_font(16)
    status_map = {
        "idle": "대기", "running": "계수 중", "paused": "일시정지",
        "mismatch": "조건 불일치 정지", "emergency": "긴급 정지", "done": "완료",
    }
    status = status_map.get(state["session"]["status"], "대기")
    d.text((10, 8), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), font=font, fill=(235, 238, 245))
    d.text((210, 8), "상태: " + status, font=font, fill=(235, 238, 245))
    d.text((w - 130, 8), "계수 " + str(state["session"]["count"]) + "벌", font=font, fill=(120, 165, 255))
    return img


def save_photo(count: int):
    try:
        day = datetime.now().strftime("%Y-%m-%d")
        pdir = RESULTS / day / "photos"
        pdir.mkdir(parents=True, exist_ok=True)
        name = datetime.now().strftime("%H%M%S") + "_" + str(count) + ".jpg"
        render_frame().save(pdir / name, format="JPEG", quality=80)
    except Exception:
        pass


def save_job():
    global last_job
    sess = state["session"]
    if sess["count"] <= 0 or sess.get("savedAt"):
        return None
    day = datetime.now().strftime("%Y-%m-%d")
    tm = datetime.now().strftime("%H%M%S")
    ddir = RESULTS / day
    ddir.mkdir(parents=True, exist_ok=True)
    job = {
        "id": day + "_" + tm,
        "date": day,
        "time": datetime.now().strftime("%H:%M:%S"),
        "mode": sess["mode"],
        "count": sess["count"],
        "config": sess["config"],
        "dir": str(ddir),
    }
    (ddir / ("job_" + tm + ".json")).write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    sess["savedAt"] = tm
    last_job = job
    return job


# ---------------------------------------------------------------- 시뮬레이터
def mutate(value: str) -> str:
    """판독 오류 모의: 마지막 글자를 다른 문자로 치환."""
    if not value:
        return "?"
    pool = string.digits if value[-1].isdigit() else string.ascii_uppercase
    repl = random.choice([c for c in pool if c != value[-1]])
    return value[:-1] + repl


async def simulate_pass():
    sess = state["session"]
    cfg = sess["config"] or {}
    pipe = state["pipeline"]

    pipe["sensor"] = "active"
    await log("의류 감지 → 판독 시작")
    await push_state()
    await asyncio.sleep(0.35)
    pipe["sensor"] = "ok"

    mismatch = None
    if sess["mode"] == "condition":
        checks = cfg.get("checks") or {}
        item = cfg.get("item") or {}
        pipe["camera"] = "active"
        await push_state()

        if checks.get("ocr"):
            await asyncio.sleep(0.3)
            sku = item.get("sku") or ""
            if sku and random.random() < 0.10:
                mismatch = {"field": "품번(OCR)", "expected": sku, "actual": mutate(sku)}
            else:
                await log("OCR 인식 완료 · 품번 " + (sku or "-") + " 일치", "ok")

        if not mismatch and (checks.get("barcode_tag") or checks.get("barcode_poly")):
            await asyncio.sleep(0.25)
            spots = []
            if checks.get("barcode_tag"):
                spots.append("가격택")
            if checks.get("barcode_poly"):
                spots.append("폴리백")
            await log(" · ".join(spots) + " 바코드 일치", "ok")

        pipe["camera"] = "ok"

        if not mismatch and checks.get("rfid"):
            pipe["rfid"] = "active"
            await push_state()
            await asyncio.sleep(0.25)
            tag = "04:" + ":".join(format(random.randint(0, 255), "02X") for _ in range(3))
            await log("RFID 태그 확인 · " + tag, "ok")
            pipe["rfid"] = "ok"

    if mismatch:
        sess["status"] = "mismatch"
        sess["mismatch"] = mismatch
        state["devices"]["conveyor"] = "fault"
        pipe["conveyor"] = "fault"
        pipe["camera"] = "fault"
        await log(
            "조건 불일치! " + mismatch["field"] + " 기대값 " + mismatch["expected"]
            + " → 판독값 " + mismatch["actual"] + " · 컨베이어 정지",
            "error",
        )
    else:
        sess["count"] += 1
        sess["lastPassAt"] = now_ts()
        await log("계수 +1 → 현재 " + str(sess["count"]) + "벌", "ok")
        if config["save_photos"]:
            save_photo(sess["count"])
        target = cfg.get("target")
        if target and sess["count"] >= int(target):
            sess["status"] = "done"
            state["devices"]["conveyor"] = "idle"
            for k in ("sensor", "camera", "rfid", "conveyor", "outfeed"):
                pipe[k] = "ok"
            await log("목표 수량 " + str(target) + "벌 도달 · 컨베이어 정지", "warn")
            save_job()
    await push_state()


async def sim_loop():
    while True:
        status = state["session"]["status"]
        if status == "running":
            await asyncio.sleep(random.uniform(1.6, 3.0))
            if state["session"]["status"] == "running":
                await simulate_pass()
        elif status in ("paused", "mismatch", "emergency"):
            await asyncio.sleep(0.3)
        else:  # idle, done
            break


def ensure_sim():
    global sim_task
    if sim_task is None or sim_task.done():
        sim_task = asyncio.get_event_loop().create_task(sim_loop())


# ---------------------------------------------------------------- API: 상태/세션
@app.get("/api/state")
async def get_state():
    return public_state()


@app.post("/api/session/start")
async def session_start(req: Request):
    body = await req.json()
    sess = state["session"]
    sess.update({
        "mode": body.get("mode", "simple"),
        "status": "running",
        "count": 0,
        "startedAt": datetime.now().isoformat(),
        "lastPassAt": None,
        "config": body,
        "mismatch": None,
    })
    sess.pop("savedAt", None)
    state["devices"]["conveyor"] = "busy"
    pipe = state["pipeline"]
    for k in pipe:
        pipe[k] = "idle"
    pipe["conveyor"] = "active"
    pipe["infeed"] = "ok"
    if sess["mode"] == "simple":
        await log("단순 계수 시작")
    else:
        item = body.get("item") or {}
        await log("조건 검사 시작 · " + str(body.get("brandName", "")) + " " + str(item.get("sku", "")))
    await push_state()
    ensure_sim()
    return {"ok": True}


@app.post("/api/session/pause")
async def session_pause():
    sess = state["session"]
    if sess["status"] == "running":
        sess["status"] = "paused"
        state["devices"]["conveyor"] = "idle"
        state["pipeline"]["conveyor"] = "idle"
        await log("일시정지", "warn")
        await push_state()
    return {"ok": True}


@app.post("/api/session/resume")
async def session_resume():
    sess = state["session"]
    if sess["status"] in ("paused", "mismatch"):
        if sess["status"] == "mismatch":
            await log("불일치 제품 제외 후 재개", "warn")
        sess["status"] = "running"
        sess["mismatch"] = None
        state["devices"]["conveyor"] = "busy"
        pipe = state["pipeline"]
        pipe["conveyor"] = "active"
        if pipe["camera"] == "fault":
            pipe["camera"] = "idle"
        await log("계수 재개")
        await push_state()
        ensure_sim()
    return {"ok": True}


@app.post("/api/session/stop")
async def session_stop():
    sess = state["session"]
    job = save_job()
    if job is None and sess.get("savedAt") and last_job is not None:
        job = last_job  # 목표 도달 시 이미 저장된 작업
    total = sess["count"]
    sess.update({
        "mode": None, "status": "idle", "count": 0,
        "startedAt": None, "lastPassAt": None, "config": None, "mismatch": None,
    })
    sess.pop("savedAt", None)
    state["devices"]["conveyor"] = "idle"
    pipe = state["pipeline"]
    for k in pipe:
        pipe[k] = "idle"
    if job:
        await log("작업 종료 · 총 " + str(total) + "벌 · 저장: " + job["dir"], "warn")
    else:
        await log("작업 종료 (계수 수량 없음)", "warn")
    await push_state()
    return {"ok": True, "job": job}


@app.post("/api/session/emergency")
async def session_emergency():
    sess = state["session"]
    if sess["mode"] is not None:
        sess["status"] = "emergency"
        state["devices"]["conveyor"] = "fault"
        state["pipeline"]["conveyor"] = "fault"
        await log("긴급 정지! 전 구간 정지", "error")
        await push_state()
    return {"ok": True}


@app.post("/api/session/emergency-release")
async def session_emergency_release():
    sess = state["session"]
    if sess["status"] == "emergency":
        sess["status"] = "paused"
        state["devices"]["conveyor"] = "idle"
        state["pipeline"]["conveyor"] = "idle"
        await log("긴급 정지 해제 · 일시정지 상태로 전환", "warn")
        await push_state()
    return {"ok": True}


@app.post("/api/session/adjust")
async def session_adjust(req: Request):
    body = await req.json()
    delta = int(body.get("delta", 0))
    sess = state["session"]
    if sess["mode"] is not None:
        sess["count"] = max(0, sess["count"] + delta)
        await log("수동 조정 " + ("+" if delta > 0 else "") + str(delta) + " → 현재 " + str(sess["count"]) + "벌", "warn")
        await push_state()
    return {"ok": True}


@app.post("/api/session/reset-count")
async def session_reset_count():
    sess = state["session"]
    if sess["mode"] is not None:
        sess["count"] = 0
        await log("수량 초기화", "warn")
        await push_state()
    return {"ok": True}


@app.post("/api/session/config")
async def session_config(req: Request):
    body = await req.json()
    sess = state["session"]
    if sess["config"] is not None:
        if "checks" in body:
            sess["config"]["checks"] = body["checks"]
        if "item" in body:
            sess["config"]["item"] = body["item"]
        await log("검사 조건 변경됨", "warn")
        await push_state()
    return {"ok": True}


# ---------------------------------------------------------------- API: 브랜드
@app.get("/api/brands")
async def get_brands():
    return brands


@app.post("/api/brands")
async def add_brand(req: Request):
    body = await req.json()
    brand = {
        "id": "b" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6)),
        "name": body.get("name", ""),
        "caps": body.get("caps", {"rfid": False, "ocr": False, "barcode_tag": False, "barcode_poly": False}),
    }
    brands.append(brand)
    save_brands()
    await log("브랜드 추가: " + brand["name"])
    await broadcast({"type": "brands", "brands": brands})
    return brand


@app.put("/api/brands/{bid}")
async def update_brand(bid: str, req: Request):
    body = await req.json()
    for b in brands:
        if b["id"] == bid:
            b["name"] = body.get("name", b["name"])
            b["caps"] = body.get("caps", b["caps"])
            save_brands()
            await log("브랜드 수정: " + b["name"])
            await broadcast({"type": "brands", "brands": brands})
            return b
    return JSONResponse({"detail": "not found"}, status_code=404)


@app.delete("/api/brands/{bid}")
async def delete_brand(bid: str):
    global brands
    target = next((b for b in brands if b["id"] == bid), None)
    if target is None:
        return JSONResponse({"detail": "not found"}, status_code=404)
    brands = [b for b in brands if b["id"] != bid]
    save_brands()
    await log("브랜드 삭제: " + target["name"], "warn")
    await broadcast({"type": "brands", "brands": brands})
    return {"ok": True}


# ---------------------------------------------------------------- API: 작업 기록/로그
@app.get("/api/jobs")
async def get_jobs():
    out = []
    if RESULTS.exists():
        for daydir in sorted(RESULTS.iterdir(), reverse=True):
            if not daydir.is_dir():
                continue
            for f in sorted(daydir.glob("job_*.json"), reverse=True):
                try:
                    out.append(json.loads(f.read_text(encoding="utf-8")))
                except Exception:
                    pass
    return out[:100]


@app.get("/api/logs")
async def get_logs(date: str = ""):
    day = date or datetime.now().strftime("%Y-%m-%d")
    f = LOGDIR / (day + ".log")
    if not f.exists():
        return {"lines": []}
    lines = f.read_text(encoding="utf-8").splitlines()
    return {"lines": lines[-500:]}


# ---------------------------------------------------------------- API: 로그인/설정
@app.post("/api/login")
async def login(req: Request):
    body = await req.json()
    ok = str(body.get("password", "")) == str(config["password"])
    if not ok:
        await log("환경 설정 로그인 실패", "warn")
    return {"ok": ok}


@app.post("/api/password")
async def change_password(req: Request):
    body = await req.json()
    if str(body.get("current", "")) != str(config["password"]):
        return {"ok": False}
    config["password"] = str(body.get("next", ""))
    save_config()
    await log("관리자 비밀번호 변경됨", "warn")
    return {"ok": True}


@app.get("/api/settings")
async def get_settings():
    return {"save_photos": config["save_photos"], "threshold": config["threshold"], "data_dir": str(DATA)}


@app.put("/api/settings")
async def put_settings(req: Request):
    body = await req.json()
    if "save_photos" in body:
        config["save_photos"] = bool(body["save_photos"])
        await log("통과 사진 저장: " + ("켬" if config["save_photos"] else "끔"))
    if "threshold" in body:
        config["threshold"] = max(10, min(90, int(body["threshold"])))
        await log("계수 임계선 위치: " + str(config["threshold"]) + "%")
    save_config()
    await push_state()
    return {"ok": True}


# ---------------------------------------------------------------- API: 장비 점검
@app.post("/api/device/conveyor")
async def device_conveyor(req: Request):
    body = await req.json()
    run = bool(body.get("run"))
    if state["session"]["status"] == "running":
        return JSONResponse({"detail": "session running"}, status_code=409)
    state["devices"]["conveyor"] = "busy" if run else "idle"
    state["pipeline"]["conveyor"] = "active" if run else "idle"
    await log("컨베이어 별도 제어: " + ("가동" if run else "정지"), "warn" if run else "info")
    await push_state()
    return {"ok": True}


@app.post("/api/device/test/{kind}")
async def device_test(kind: str):
    node_map = {"sensor": "sensor", "rfid": "rfid", "ocr": "camera"}
    dev_map = {"sensor": "sensor", "rfid": "rfid", "ocr": "camera"}
    if kind not in node_map:
        return JSONResponse({"detail": "unknown test"}, status_code=404)
    node, dev = node_map[kind], dev_map[kind]
    pipe = state["pipeline"]
    pipe[node] = "active"
    await push_state()
    await asyncio.sleep(1.1)
    success = random.random() > 0.07
    if success:
        pipe[node] = "ok"
        state["devices"][dev] = "ok"
        if kind == "rfid":
            tag = "04:" + ":".join(format(random.randint(0, 255), "02X") for _ in range(3))
            detail = "TEST 카드 인식 성공 · 태그 " + tag
        elif kind == "ocr":
            detail = "OCR 인식 성공 · 판독: TS-2401 / NAVY / 100"
        else:
            detail = "광센서 감지 신호 정상"
        await log("장비 점검 · " + detail, "ok")
    else:
        pipe[node] = "fault"
        state["devices"][dev] = "fault"
        detail = "응답 없음 — 연결을 확인하세요"
        await log("장비 점검 · " + kind.upper() + " " + detail, "error")
    await push_state()
    return {"ok": success, "detail": detail}


# ---------------------------------------------------------------- 스트림 / WS
@app.get("/stream")
async def stream():
    async def gen():
        while True:
            buf = io.BytesIO()
            render_frame().save(buf, format="JPEG", quality=70)
            frame = buf.getvalue()
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"
            )
            await asyncio.sleep(0.12)

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    try:
        await websocket.send_text(json.dumps({"type": "state", "state": public_state()}, ensure_ascii=False))
        await websocket.send_text(json.dumps({"type": "logs", "items": recent_logs[-100:]}, ensure_ascii=False))
        await websocket.send_text(json.dumps({"type": "brands", "brands": brands}, ensure_ascii=False))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(websocket)


# ---------------------------------------------------------------- 정적 파일 (빌드된 프론트)
DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        target = DIST / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(DIST / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
