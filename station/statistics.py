"""Complete job and daily reports, with Seoul calendar boundaries."""
from __future__ import annotations
import csv
import io
import json
import sqlite3
from contextlib import closing
from collections import Counter, defaultdict
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
RUNNING = {"FEEDING", "INSPECTING", "STOPPING", "EJECTING", "RETRY_PENDING"}
ENDED = {"DONE", "FINISHED", "ABORTED"}


def instant(value):
    return datetime.fromisoformat(value).astimezone(KST)


def report(store, since: date, until: date, include_tests=False, brand_id=None, preset_id=None):
    if since > until or (until - since).days > 3660:
        raise ValueError("조회 기간은 시작일부터 최대 10년입니다.")
    start = datetime.combine(since, time.min, KST)
    end = datetime.combine(until + timedelta(days=1), time.min, KST)
    now = datetime.now(KST)
    # A separate WAL reader keeps long reports out of the controller's write lock.
    with closing(sqlite3.connect(store.path)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        sessions = [json.loads(r[0]) for r in db.execute("SELECT body FROM sessions ORDER BY created_at DESC")]
        inspections = [json.loads(r[0]) for r in db.execute("SELECT body FROM inspections")]
        events = [{**dict(r), "body": json.loads(r["body"])} for r in db.execute("SELECT * FROM events ORDER BY seq")]
        db.rollback()
    by_inspection, by_event = defaultdict(list), defaultdict(list)
    for r in inspections:
        by_inspection[r["session_id"]].append(r)
    for e in events:
        ident = e["body"].get("session_id")
        if ident:
            by_event[ident].append(e)
    daily = defaultdict(lambda: Counter(count=0, passed=0, failed=0, aborted=0, adjustments=0,
        di1=0, di2=0, vision=0, camera_retries=0, errors=0, run_seconds=0, stopped_seconds=0, jobs=0, unread=0, mismatches=0, retries=0))
    jobs = []
    details = []
    timing_unknown_jobs = 0
    for s in sessions:
        if brand_id and s["recipe"].get("brand_id") != brand_id:
            continue
        if preset_id and s["recipe"].get("preset_id") != preset_id:
            continue
        if s["recipe"].get("test_run") and not include_tests:
            continue
        created = instant(s["created_at"])
        es = by_event[s["id"]]
        rows = by_inspection[s["id"]]
        known_finish = s.get("finished_at") or next((e["created_at"] for e in es
            if e["body"].get("phase", e["body"].get("result", {}).get("phase")) in ENDED), None)
        timing_unknown = s["phase"] in ENDED and not known_finish
        finished = instant(known_finish) if known_finish else now
        if timing_unknown:
            # Bound the filter by recorded activity, without inventing a duration
            # or treating an old finished job as still stopped today.
            finished = max([created, *(instant(e["created_at"]) for e in es),
                            *(instant(r.get("finished_at", r["created_at"])) for r in rows)])
        if created >= end or finished < start:
            continue
        timing_unknown_jobs += int(timing_unknown)
        metrics = Counter(di1=0, di2=0, vision=0, camera_retries=0, errors=0, retries=0,
                          unread=0, mismatches=0, aborted=0, run_seconds=0, stopped_seconds=0)
        previous, phase = created, "READY"
        def segment(a, b, state):
            if timing_unknown:
                return
            key = "run_seconds" if state in RUNNING else "stopped_seconds"
            metrics[key] += max(0, (b - a).total_seconds())
            a, b = max(a, start), min(b, end)
            while a < b:
                boundary = min(b, datetime.combine(a.date() + timedelta(days=1), time.min, KST))
                daily[a.date().isoformat()][key] += (boundary - a).total_seconds()
                a = boundary
        for e in es:
            at = instant(e["created_at"])
            segment(previous, min(at, finished), phase)
            previous = min(at, finished)
            phase = e["body"].get("phase", e["body"].get("result", {}).get("phase", phase))
            kind = e["kind"]
            key = {"DI1_DETECTED": "di1", "DI2_DETECTED": "di2", "VISION_CROSSING": "vision",
                   "CAMERA_RETRY": "camera_retries", "FAULT": "errors"}.get(kind)
            if key:
                value = e["body"].get("count", 1)
                metrics[key] += value
                if start <= at < end:
                    daily[at.date().isoformat()][key] += value
            if kind == "MANUAL_ADJUSTMENT" and start <= at < end:
                daily[at.date().isoformat()]["adjustments"] += e["body"]["delta"]
                daily[at.date().isoformat()]["count"] += e["body"]["delta"]
        segment(previous, finished, phase)
        if start <= created < end:
            daily[created.date().isoformat()]["jobs"] += 1
        failures = Counter()
        latencies = []
        for r in rows:
            at = instant(r.get("finished_at", r["created_at"]))
            metrics["retries"] += int(r["attempt"] > 1)
            if r.get("elapsed_ms") is not None:
                latencies.append(r["elapsed_ms"])
            failures.update(f["code"] for f in r.get("failures", []))
            codes = {f["code"] for f in r.get("failures", [])}
            unread = int(bool(codes & {"REQUIRED_FIELD_MISSING", "OCR_MISSING", "RFID_MISSING"}))
            mismatches = int(bool(codes & {"TARGET_MISMATCH", "QUANTITY_MISMATCH"}))
            metrics["unread"] += unread
            metrics["mismatches"] += mismatches
            metrics["aborted"] += int(r["status"] == "ABORTED")
            if start <= at < end:
                key = {"PASS": "passed", "FAIL": "failed", "ABORTED": "aborted"}.get(r["status"])
                if key:
                    daily[at.date().isoformat()][key] += 1
                daily[at.date().isoformat()]["retries"] += int(r["attempt"] > 1)
                daily[at.date().isoformat()]["unread"] += unread
                daily[at.date().isoformat()]["mismatches"] += mismatches
                if r["status"] == "PASS":
                    daily[at.date().isoformat()]["count"] += 1
                details.append({"session_id": s["id"], "inspection_id": r["id"], "time": at.isoformat(),
                    "product_id": r["product_id"], "attempt": r["attempt"], "status": r["status"],
                    "di2_count": r.get("di2_count"), "vision_count": r.get("vision_count"),
                    "elapsed_ms": r.get("elapsed_ms"),
                    "capture_delay_ms": r.get("capture_delay_actual_ms"), "rfid_delay_ms": r.get("rfid_delay_actual_ms"),
                    "inference_ms": (r.get("tracking") or {}).get("inference_ms"), "failures": ", ".join(f["code"] for f in r.get("failures", []))})
        if timing_unknown:
            metrics["run_seconds"] = metrics["stopped_seconds"] = None
        jobs.append({"id": s["id"], "work": s["recipe"].get("work_name") or s["brand"]["name"],
            "brand": s["brand"]["name"], "options": json.dumps(s["recipe"]["targets"], ensure_ascii=False),
            "preset_revision": s["recipe"].get("preset_revision"), "model": (s["recipe"].get("flow") or {}).get("model_path", ""),
            "model_sha256": s.get("model_identity", {}).get("sha256", ""),
            "per_minute": round(s["count"] * 60 / metrics["run_seconds"], 3) if metrics["run_seconds"] else None,
            "started_at": created.isoformat(), "finished_at": finished.isoformat() if known_finish else "",
            "phase": s["phase"], "test_run": bool(s["recipe"].get("test_run")),
            "count": s["count"], "passed": s["passed"], "failed": s["failed"], "adjustments": s["adjustments"],
            **dict(metrics), "average_ms": sum(latencies) / len(latencies) if latencies else None,
            "maximum_ms": max(latencies) if latencies else None,
            "failures": json.dumps(dict(failures), ensure_ascii=False)})
    return {"timezone": "Asia/Seoul", "since": str(since), "until": str(until), "jobs": jobs,
            "timing_unknown_jobs": timing_unknown_jobs,
            "daily": [{"date": key, **dict(value)} for key, value in sorted(daily.items(), reverse=True)], "inspections": details}


def csv_bytes(rows):
    output = io.StringIO(newline="")
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        labels = {"id": "작업 ID", "session_id": "작업 ID", "work": "작업", "brand": "브랜드",
            "options": "선택 옵션", "preset_revision": "프리셋 버전", "model": "모델 파일", "model_sha256": "모델 SHA256",
            "started_at": "시작 시각", "finished_at": "종료 시각", "phase": "작업 상태", "test_run": "시험 작업",
            "date": "일자", "count": "수량", "passed": "합격", "failed": "불합격", "aborted": "중단", "adjustments": "보정",
            "di1": "DI1 감지", "di2": "DI2 통과", "vision": "비전 통과", "camera_retries": "카메라 재연결 시도",
            "errors": "장비 오류", "retries": "재검사", "unread": "미판독", "mismatches": "불일치",
            "run_seconds": "운전 시간(초)", "stopped_seconds": "정지 시간(초)", "jobs": "작업 수",
            "per_minute": "분당 수량", "average_ms": "평균 검사 시간(ms)", "maximum_ms": "최대 검사 시간(ms)",
            "failures": "불합격 사유", "inspection_id": "검사 ID", "time": "시각", "product_id": "제품 ID",
            "attempt": "검사 차수", "status": "판정", "di2_count": "DI2 수량", "vision_count": "비전 수량",
            "elapsed_ms": "처리 시간(ms)", "capture_delay_ms": "실제 촬영 지연(ms)",
            "rfid_delay_ms": "실제 RFID 지연(ms)", "inference_ms": "모델 처리 시간(ms)"}
        writer.writerow({key: labels.get(key, key) for key in rows[0]})
        for row in rows:
            # Spreadsheet exports must not turn names/paths into formulas.
            writer.writerow({k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v for k, v in row.items()})
    return ("\ufeff" + output.getvalue()).encode("utf-8")
