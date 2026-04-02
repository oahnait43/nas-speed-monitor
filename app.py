import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / os.getenv("DB_NAME", "speed_history.db")
TIMEZONE_OFFSET = env_int("TZ_OFFSET_HOURS", 8)
SCHEDULE_MINUTES = env_int("SCHEDULE_MINUTES", 30)
RUN_ON_START = env_bool("RUN_ON_START", True)
ENABLE_INTERNET_TEST = env_bool("ENABLE_INTERNET_TEST", True)
ENABLE_LAN_TEST = env_bool("ENABLE_LAN_TEST", True)
ENABLE_HEARTBEAT_TEST = env_bool("ENABLE_HEARTBEAT_TEST", True)
LAN_HOST = os.getenv("LAN_IPERF_HOST", "")
LAN_PORT = env_int("LAN_IPERF_PORT", 5201)
LAN_DURATION = env_int("LAN_IPERF_DURATION_SECONDS", 10)
HEARTBEAT_INTERVAL_SECONDS = env_int("HEARTBEAT_INTERVAL_SECONDS", 60)
HEARTBEAT_TARGET = os.getenv("HEARTBEAT_TARGET", "223.5.5.5").strip() or "223.5.5.5"
HEARTBEAT_TIMEOUT_SECONDS = env_int("HEARTBEAT_TIMEOUT_SECONDS", 2)
HEARTBEAT_TARGETS = [
    item.strip()
    for item in os.getenv("HEARTBEAT_TARGETS", f"{HEARTBEAT_TARGET},114.114.114.114,1.1.1.1").split(",")
    if item.strip()
]
INTERNET_SERVER_ID = os.getenv("INTERNET_SPEEDTEST_SERVER_ID", "").strip()
INTERNET_SERVER_POOL = [item.strip() for item in os.getenv("INTERNET_SERVER_POOL", "").split(",") if item.strip()]
RETENTION_DAYS = env_int("RETENTION_DAYS", 0)
INTERNET_RETRIES = env_int("INTERNET_RETRIES", 2)
INTERNET_RETRY_DELAY_SECONDS = env_float("INTERNET_RETRY_DELAY_SECONDS", 5.0)
DOWNLOAD_ALERT_Mbps = env_float("DOWNLOAD_ALERT_MBPS", 5.0)
UPLOAD_ALERT_Mbps = env_float("UPLOAD_ALERT_MBPS", 1.0)
LATENCY_ALERT_MS = env_float("LATENCY_ALERT_MS", 100.0)
TEST_DURATION_ALERT_SECONDS = env_float("TEST_DURATION_ALERT_SECONDS", 60.0)
SPEEDTEST_BIN = os.getenv("SPEEDTEST_BIN", "speedtest")


BASE_COLUMNS = [
    ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
    ("kind", "TEXT NOT NULL"),
    ("target", "TEXT"),
    ("measured_at", "TEXT NOT NULL"),
    ("success", "INTEGER NOT NULL"),
    ("download_mbps", "REAL"),
    ("upload_mbps", "REAL"),
    ("latency_ms", "REAL"),
    ("raw_json", "TEXT"),
    ("error_message", "TEXT"),
]

EXTRA_COLUMNS = [
    ("server_id", "TEXT"),
    ("server_name", "TEXT"),
    ("server_location", "TEXT"),
    ("server_country", "TEXT"),
    ("server_host", "TEXT"),
    ("server_sponsor", "TEXT"),
    ("isp_name", "TEXT"),
    ("external_ip", "TEXT"),
    ("packet_loss", "REAL"),
    ("jitter_ms", "REAL"),
    ("bytes_sent", "INTEGER"),
    ("bytes_received", "INTEGER"),
    ("result_url", "TEXT"),
    ("test_duration_ms", "INTEGER"),
]


app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

stop_event = threading.Event()
job_lock = threading.Lock()
PING_LATENCY_PATTERN = re.compile(r"time[=<]([\d.]+)\s*ms")


def db_connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def current_columns(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("PRAGMA table_info(measurements)").fetchall()
    return {row["name"] for row in rows}


def init_db() -> None:
    columns_sql = ",\n".join(f"{name} {column_type}" for name, column_type in BASE_COLUMNS)
    with closing(db_connect()) as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS measurements (
                {columns_sql}
            )
            """
        )
        existing = current_columns(conn)
        for name, column_type in EXTRA_COLUMNS:
            if name not in existing:
                conn.execute(f"ALTER TABLE measurements ADD COLUMN {name} {column_type}")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_measurements_kind_time
            ON measurements(kind, measured_at DESC)
            """
        )
        conn.commit()


def local_now() -> datetime:
    tz = timezone(timedelta(hours=TIMEZONE_OFFSET))
    return datetime.now(tz)


def iso_now() -> str:
    return local_now().isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    rank = (len(ordered) - 1) * p
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    result = ordered[lower] * (1 - weight) + ordered[upper] * weight
    return round(result, 2)


def floor_time(dt: datetime, minutes: int) -> datetime:
    minute = (dt.minute // minutes) * minutes
    return dt.replace(minute=minute, second=0, microsecond=0)


def prune_old_data() -> None:
    if RETENTION_DAYS <= 0:
        return
    cutoff = (local_now() - timedelta(days=RETENTION_DAYS)).isoformat()
    with closing(db_connect()) as conn:
        conn.execute("DELETE FROM measurements WHERE measured_at < ?", (cutoff,))
        conn.commit()


def is_official_cli_result(raw_json_text: str | None) -> bool:
    return bool(raw_json_text and '"type": "result"' in raw_json_text)


def cleanup_legacy_internet_samples() -> int:
    with closing(db_connect()) as conn:
        rows = conn.execute(
            """
            SELECT id, raw_json
            FROM measurements
            WHERE kind = 'internet'
            ORDER BY id ASC
            """
        ).fetchall()
        legacy_ids = [row["id"] for row in rows if not is_official_cli_result(row["raw_json"])]
        if legacy_ids:
            placeholders = ", ".join("?" for _ in legacy_ids)
            conn.execute(f"DELETE FROM measurements WHERE id IN ({placeholders})", legacy_ids)
            conn.commit()
        return len(legacy_ids)


def insert_measurement(kind: str, target: str, success: bool, **fields: Any) -> None:
    payload = {
        "kind": kind,
        "target": target,
        "measured_at": iso_now(),
        "success": 1 if success else 0,
        "download_mbps": fields.get("download_mbps"),
        "upload_mbps": fields.get("upload_mbps"),
        "latency_ms": fields.get("latency_ms"),
        "raw_json": json.dumps(fields["raw_json"], ensure_ascii=False) if fields.get("raw_json") is not None else None,
        "error_message": fields.get("error_message"),
        "server_id": fields.get("server_id"),
        "server_name": fields.get("server_name"),
        "server_location": fields.get("server_location"),
        "server_country": fields.get("server_country"),
        "server_host": fields.get("server_host"),
        "server_sponsor": fields.get("server_sponsor"),
        "isp_name": fields.get("isp_name"),
        "external_ip": fields.get("external_ip"),
        "packet_loss": fields.get("packet_loss"),
        "jitter_ms": fields.get("jitter_ms"),
        "bytes_sent": fields.get("bytes_sent"),
        "bytes_received": fields.get("bytes_received"),
        "result_url": fields.get("result_url"),
        "test_duration_ms": fields.get("test_duration_ms"),
    }
    columns = list(payload.keys())
    placeholders = ", ".join("?" for _ in columns)
    with closing(db_connect()) as conn:
        conn.execute(
            f"INSERT INTO measurements ({', '.join(columns)}) VALUES ({placeholders})",
            [payload[column] for column in columns],
        )
        conn.commit()


def speedtest_command(*args: str) -> list[str]:
    return [SPEEDTEST_BIN, "--accept-license", "--accept-gdpr", *args]


def run_speedtest_cli(*args: str, timeout: int = 180) -> dict[str, Any]:
    completed = subprocess.run(
        speedtest_command(*args),
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return json.loads(completed.stdout)


def parse_speedtest_result(result: dict[str, Any], elapsed_ms: int) -> dict[str, Any]:
    server = result.get("server", {}) or {}
    interface = result.get("interface", {}) or {}
    isp = result.get("isp", "") or interface.get("isp")
    external_ip = interface.get("externalIp") or result.get("interface", {}).get("externalIp")
    packet_loss = result.get("packetLoss")
    ping = result.get("ping", {}) or {}
    download = result.get("download", {}) or {}
    upload = result.get("upload", {}) or {}
    result_meta = result.get("result", {}) or {}
    return {
        "target": str(server.get("name") or server.get("host") or INTERNET_SERVER_ID or "auto"),
        "download_mbps": round(float(download.get("bandwidth", 0.0)) * 8 / 1_000_000, 2),
        "upload_mbps": round(float(upload.get("bandwidth", 0.0)) * 8 / 1_000_000, 2),
        "latency_ms": round(float(ping.get("latency", 0.0)), 2),
        "raw_json": result,
        "server_id": str(server.get("id", "")) or None,
        "server_name": server.get("name"),
        "server_location": server.get("location"),
        "server_country": server.get("country"),
        "server_host": server.get("host"),
        "server_sponsor": server.get("name"),
        "isp_name": isp,
        "external_ip": external_ip,
        "packet_loss": packet_loss,
        "jitter_ms": ping.get("jitter"),
        "bytes_sent": upload.get("bytes"),
        "bytes_received": download.get("bytes"),
        "result_url": result_meta.get("url"),
        "test_duration_ms": elapsed_ms,
    }


def anomaly_flags(download_mbps: float | None, upload_mbps: float | None, latency_ms: float | None, test_duration_ms: int | None) -> list[str]:
    flags: list[str] = []
    if download_mbps is not None and download_mbps < DOWNLOAD_ALERT_Mbps:
        flags.append("download_low")
    if upload_mbps is not None and upload_mbps < UPLOAD_ALERT_Mbps:
        flags.append("upload_low")
    if latency_ms is not None and latency_ms > LATENCY_ALERT_MS:
        flags.append("latency_high")
    if test_duration_ms is not None and test_duration_ms > int(TEST_DURATION_ALERT_SECONDS * 1000):
        flags.append("duration_high")
    return flags


def speedtest_candidates() -> list[str | None]:
    if INTERNET_SERVER_POOL:
        return INTERNET_SERVER_POOL + [None]
    if INTERNET_SERVER_ID:
        return [INTERNET_SERVER_ID, None]
    return [None]


def run_single_speedtest(server_id: str | None) -> dict[str, Any]:
    if server_id:
        return run_speedtest_cli("-s", server_id, "-f", "json")
    return run_speedtest_cli("-f", "json")


def list_speedtest_candidates(limit: int = 20) -> list[dict[str, Any]]:
    payload = run_speedtest_cli("-L", "-f", "json", timeout=240)
    servers = payload.get("servers", []) or payload.get("servers", {}).get("items", []) or []
    items: list[dict[str, Any]] = []
    for entry in servers:
        items.append(
            {
                "id": str(entry.get("id", "")) or None,
                "sponsor": entry.get("name") or entry.get("sponsor"),
                "name": entry.get("location") or entry.get("name"),
                "country": entry.get("country"),
                "host": entry.get("host"),
                "distance_km": round(float(entry.get("distance", 999999)), 2),
            }
        )
    items.sort(key=lambda item: item["distance_km"])
    return items[:limit]


def run_internet_test() -> None:
    target = ",".join(INTERNET_SERVER_POOL) if INTERNET_SERVER_POOL else (INTERNET_SERVER_ID or "auto")
    last_error = "未拿到测速结果。"
    for server_id in speedtest_candidates():
        server_label = server_id or "auto"
        for attempt in range(1, INTERNET_RETRIES + 1):
            started = time.perf_counter()
            try:
                result = run_single_speedtest(server_id)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                parsed = parse_speedtest_result(result, elapsed_ms)
                parsed["raw_json"]["selection"] = {
                    "preferred_server_id": server_id,
                    "preferred_pool": INTERNET_SERVER_POOL,
                    "attempt": attempt,
                    "fallback_auto": server_id is None,
                }
                insert_measurement("internet", parsed.pop("target"), True, **parsed)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = f"节点 {server_label} 第 {attempt} 次测速失败: {exc}"
                if attempt < INTERNET_RETRIES:
                    time.sleep(INTERNET_RETRY_DELAY_SECONDS)

    insert_measurement(
        kind="internet",
        target=target,
        success=False,
        error_message=last_error,
        test_duration_ms=None,
    )


def run_lan_test() -> None:
    if not LAN_HOST:
        insert_measurement(
            kind="lan",
            target="未配置",
            success=False,
            error_message="LAN_IPERF_HOST 未配置，无法执行内网测速。",
        )
        return

    cmd = [
        "iperf3",
        "-c",
        LAN_HOST,
        "-p",
        str(LAN_PORT),
        "-t",
        str(LAN_DURATION),
        "-J",
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=LAN_DURATION + 30,
        )
        result = json.loads(completed.stdout)
        summary = result.get("end", {}).get("sum_received", {})
        reverse = result.get("end", {}).get("sum_sent", {})
        insert_measurement(
            kind="lan",
            target=f"{LAN_HOST}:{LAN_PORT}",
            success=True,
            download_mbps=round(summary.get("bits_per_second", 0.0) / 1_000_000, 2),
            upload_mbps=round(reverse.get("bits_per_second", 0.0) / 1_000_000, 2),
            latency_ms=None,
            raw_json=result,
            test_duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except subprocess.TimeoutExpired:
        insert_measurement(
            kind="lan",
            target=f"{LAN_HOST}:{LAN_PORT}",
            success=False,
            error_message="iperf3 测速超时。",
        )
    except subprocess.CalledProcessError as exc:
        error_text = exc.stderr.strip() or exc.stdout.strip() or "iperf3 执行失败。"
        insert_measurement(
            kind="lan",
            target=f"{LAN_HOST}:{LAN_PORT}",
            success=False,
            error_message=error_text,
        )
    except Exception as exc:  # noqa: BLE001
        insert_measurement(
            kind="lan",
            target=f"{LAN_HOST}:{LAN_PORT}",
            success=False,
            error_message=str(exc),
        )


def parse_ping_latency(output: str) -> float | None:
    match = PING_LATENCY_PATTERN.search(output)
    if not match:
        return None
    return round(float(match.group(1)), 2)


def run_single_heartbeat_test(target: str) -> None:
    cmd = [
        "ping",
        "-c",
        "1",
        "-W",
        str(HEARTBEAT_TIMEOUT_SECONDS),
        target,
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=HEARTBEAT_TIMEOUT_SECONDS + 3,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        insert_measurement(
            kind="heartbeat",
            target=target,
            success=True,
            latency_ms=parse_ping_latency(output),
            raw_json={
                "command": cmd,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
            test_duration_ms=elapsed_ms,
        )
    except subprocess.TimeoutExpired:
        insert_measurement(
            kind="heartbeat",
            target=target,
            success=False,
            error_message=f"ping {target} 超时",
            test_duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except subprocess.CalledProcessError as exc:
        error_text = exc.stderr.strip() or exc.stdout.strip() or f"ping {target} 失败"
        insert_measurement(
            kind="heartbeat",
            target=target,
            success=False,
            error_message=error_text,
            raw_json={
                "command": cmd,
                "stdout": exc.stdout,
                "stderr": exc.stderr,
            },
            test_duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001
        insert_measurement(
            kind="heartbeat",
            target=target,
            success=False,
            error_message=str(exc),
            test_duration_ms=int((time.perf_counter() - started) * 1000),
        )


def run_heartbeat_test() -> None:
    for target in HEARTBEAT_TARGETS:
        run_single_heartbeat_test(target)


def run_all_tests() -> None:
    if not job_lock.acquire(blocking=False):
        return
    try:
        if ENABLE_INTERNET_TEST:
            run_internet_test()
        if ENABLE_LAN_TEST:
            run_lan_test()
        prune_old_data()
    finally:
        job_lock.release()


def scheduler_loop() -> None:
    if RUN_ON_START:
        run_all_tests()
    if ENABLE_HEARTBEAT_TEST:
        run_heartbeat_test()

    next_speedtest = time.monotonic() + max(SCHEDULE_MINUTES * 60, 1)
    next_heartbeat = time.monotonic() + max(HEARTBEAT_INTERVAL_SECONDS, 1)
    while not stop_event.is_set():
        wait_for = max(0.5, min(next_speedtest, next_heartbeat) - time.monotonic())
        if stop_event.wait(wait_for):
            break
        now = time.monotonic()
        if ENABLE_HEARTBEAT_TEST and now >= next_heartbeat:
            run_heartbeat_test()
            next_heartbeat = now + max(HEARTBEAT_INTERVAL_SECONDS, 1)
        if now >= next_speedtest:
            run_all_tests()
            next_speedtest = now + max(SCHEDULE_MINUTES * 60, 1)


def latest_rows() -> dict[str, dict[str, Any] | None]:
    output: dict[str, dict[str, Any] | None] = {"internet": None, "lan": None, "heartbeat": None}
    with closing(db_connect()) as conn:
        for kind in ("internet", "lan", "heartbeat"):
            row = conn.execute(
                """
                SELECT *
                FROM measurements
                WHERE kind = ?
                ORDER BY measured_at DESC
                LIMIT 1
                """,
                (kind,),
            ).fetchone()
            output[kind] = dict(row) if row else None
    return output


def compact_overview(summary: dict[str, Any]) -> dict[str, Any]:
    latest = summary.get("latest_success") or {}
    return {
        "current_download_mbps": latest.get("download_mbps"),
        "current_upload_mbps": latest.get("upload_mbps"),
        "current_latency_ms": latest.get("latency_ms"),
        "current_node": latest.get("server_sponsor") or latest.get("server_name"),
        "current_isp": latest.get("isp_name"),
        "current_external_ip": latest.get("external_ip"),
        "last_measured_at": latest.get("measured_at"),
        "last_status": "异常" if latest.get("anomalies") else "正常",
        "anomaly_count": len(latest.get("anomalies") or []),
    }


def fetch_history(kind: str, hours: int, target: str | None = None) -> list[dict[str, Any]]:
    params: list[Any] = [kind]
    query = """
        SELECT *
        FROM measurements
        WHERE kind = ?
    """
    if target:
        query += " AND target = ?"
        params.append(target)
    if hours > 0:
        cutoff = (local_now() - timedelta(hours=hours)).isoformat()
        query += " AND measured_at >= ?"
        params.append(cutoff)
    query += " ORDER BY measured_at ASC"

    with closing(db_connect()) as conn:
        rows = conn.execute(query, params).fetchall()
    items = [dict(row) for row in rows]
    for item in items:
        item["anomalies"] = anomaly_flags(
            item.get("download_mbps"),
            item.get("upload_mbps"),
            item.get("latency_ms"),
            item.get("test_duration_ms"),
        )
    return items


def fetch_internet_summary(hours: int) -> dict[str, Any]:
    params: list[Any] = ["internet"]
    where = "WHERE kind = ?"
    if hours > 0:
        cutoff = (local_now() - timedelta(hours=hours)).isoformat()
        where += " AND measured_at >= ?"
        params.append(cutoff)

    with closing(db_connect()) as conn:
        aggregate = conn.execute(
            f"""
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success_count,
                AVG(CASE WHEN success = 1 THEN download_mbps END) AS avg_download_mbps,
                AVG(CASE WHEN success = 1 THEN upload_mbps END) AS avg_upload_mbps,
                AVG(CASE WHEN success = 1 THEN latency_ms END) AS avg_latency_ms,
                MIN(CASE WHEN success = 1 THEN download_mbps END) AS min_download_mbps,
                MAX(CASE WHEN success = 1 THEN download_mbps END) AS max_download_mbps,
                MIN(CASE WHEN success = 1 THEN upload_mbps END) AS min_upload_mbps,
                MAX(CASE WHEN success = 1 THEN upload_mbps END) AS max_upload_mbps,
                MIN(CASE WHEN success = 1 THEN latency_ms END) AS min_latency_ms,
                MAX(CASE WHEN success = 1 THEN latency_ms END) AS max_latency_ms,
                AVG(CASE WHEN success = 1 THEN test_duration_ms END) AS avg_test_duration_ms
            FROM measurements
            {where}
            """
            ,
            params,
        ).fetchone()

        latest_success = conn.execute(
            f"""
            SELECT *
            FROM measurements
            {where} AND success = 1
            ORDER BY measured_at DESC
            LIMIT 1
            """,
            params,
        ).fetchone()

        recent_failures = conn.execute(
            f"""
            SELECT measured_at, error_message
            FROM measurements
            {where} AND success = 0
            ORDER BY measured_at DESC
            LIMIT 5
            """,
            params,
        ).fetchall()

        latest_server = conn.execute(
            f"""
            SELECT server_sponsor, server_name, server_country, isp_name, external_ip
            FROM measurements
            {where} AND success = 1
            ORDER BY measured_at DESC
            LIMIT 1
            """,
            params,
        ).fetchone()

        daily_rows = conn.execute(
            f"""
            SELECT
                substr(measured_at, 1, 10) AS day,
                COUNT(*) AS total_count,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success_count,
                AVG(CASE WHEN success = 1 THEN download_mbps END) AS avg_download_mbps,
                AVG(CASE WHEN success = 1 THEN upload_mbps END) AS avg_upload_mbps,
                AVG(CASE WHEN success = 1 THEN latency_ms END) AS avg_latency_ms,
                MAX(CASE WHEN success = 1 THEN download_mbps END) AS peak_download_mbps,
                MAX(CASE WHEN success = 1 THEN upload_mbps END) AS peak_upload_mbps
            FROM measurements
            {where}
            GROUP BY substr(measured_at, 1, 10)
            ORDER BY day DESC
            LIMIT 14
            """,
            params,
        ).fetchall()

        anomaly_counts = conn.execute(
            f"""
            SELECT
                SUM(CASE WHEN success = 1 AND download_mbps < ? THEN 1 ELSE 0 END) AS download_low_count,
                SUM(CASE WHEN success = 1 AND upload_mbps < ? THEN 1 ELSE 0 END) AS upload_low_count,
                SUM(CASE WHEN success = 1 AND latency_ms > ? THEN 1 ELSE 0 END) AS latency_high_count,
                SUM(CASE WHEN success = 1 AND test_duration_ms > ? THEN 1 ELSE 0 END) AS duration_high_count
            FROM measurements
            {where}
            """,
            [DOWNLOAD_ALERT_Mbps, UPLOAD_ALERT_Mbps, LATENCY_ALERT_MS, int(TEST_DURATION_ALERT_SECONDS * 1000), *params],
        ).fetchone()

        success_rows = conn.execute(
            f"""
            SELECT measured_at, download_mbps, upload_mbps, latency_ms, test_duration_ms
            FROM measurements
            {where} AND success = 1
            ORDER BY measured_at ASC
            """,
            params,
        ).fetchall()

    total_count = aggregate["total_count"] or 0
    success_count = aggregate["success_count"] or 0
    success_rate = round((success_count / total_count) * 100, 2) if total_count else 0.0
    latest_success_dict = dict(latest_success) if latest_success else None
    if latest_success_dict:
        latest_success_dict["anomalies"] = anomaly_flags(
            latest_success_dict.get("download_mbps"),
            latest_success_dict.get("upload_mbps"),
            latest_success_dict.get("latency_ms"),
            latest_success_dict.get("test_duration_ms"),
        )

    anomaly_periods: dict[str, dict[str, Any]] = {}
    streak = {
        "count": 0,
        "start": None,
        "end": None,
        "last_flags": [],
    }
    for row in success_rows:
        row_dict = dict(row)
        flags = anomaly_flags(
            row_dict.get("download_mbps"),
            row_dict.get("upload_mbps"),
            row_dict.get("latency_ms"),
            row_dict.get("test_duration_ms"),
        )
        hour_bucket = row_dict["measured_at"][11:13]
        bucket = anomaly_periods.setdefault(hour_bucket, {"samples": 0, "anomalies": 0})
        bucket["samples"] += 1
        if flags:
            bucket["anomalies"] += 1
            if streak["count"] == 0:
                streak["start"] = row_dict["measured_at"]
            streak["count"] += 1
            streak["end"] = row_dict["measured_at"]
            streak["last_flags"] = flags
        else:
            streak["count"] = 0
            streak["start"] = None
            streak["end"] = None
            streak["last_flags"] = []

    anomaly_hours = [
        {
            "hour": hour,
            "samples": data["samples"],
            "anomalies": data["anomalies"],
            "rate": round((data["anomalies"] / data["samples"]) * 100, 2) if data["samples"] else 0.0,
        }
        for hour, data in sorted(anomaly_periods.items())
        if data["anomalies"] > 0
    ]

    return {
        "hours": hours,
        "total_count": total_count,
        "success_count": success_count,
        "failure_count": total_count - success_count,
        "success_rate": success_rate,
        "avg_download_mbps": aggregate["avg_download_mbps"],
        "avg_upload_mbps": aggregate["avg_upload_mbps"],
        "avg_latency_ms": aggregate["avg_latency_ms"],
        "min_download_mbps": aggregate["min_download_mbps"],
        "max_download_mbps": aggregate["max_download_mbps"],
        "min_upload_mbps": aggregate["min_upload_mbps"],
        "max_upload_mbps": aggregate["max_upload_mbps"],
        "min_latency_ms": aggregate["min_latency_ms"],
        "max_latency_ms": aggregate["max_latency_ms"],
        "avg_test_duration_ms": aggregate["avg_test_duration_ms"],
        "latest_success": latest_success_dict,
        "latest_server": dict(latest_server) if latest_server else None,
        "recent_failures": [dict(row) for row in recent_failures],
        "daily_rollups": [dict(row) for row in daily_rows],
        "anomaly_counts": dict(anomaly_counts) if anomaly_counts else {},
        "anomaly_hours": anomaly_hours,
        "current_anomaly_streak": {
            "count": streak["count"],
            "start": streak["start"],
            "end": streak["end"],
            "flags": streak["last_flags"],
        },
        "thresholds": {
            "download_alert_mbps": DOWNLOAD_ALERT_Mbps,
            "upload_alert_mbps": UPLOAD_ALERT_Mbps,
            "latency_alert_ms": LATENCY_ALERT_MS,
            "test_duration_alert_seconds": TEST_DURATION_ALERT_SECONDS,
        },
        "server_strategy": {
            "preferred_server_id": INTERNET_SERVER_ID or None,
            "preferred_pool": INTERNET_SERVER_POOL,
            "fallback_to_auto": True,
        },
        "overview": compact_overview(
            {
                "latest_success": latest_success_dict,
            }
        ),
    }


def detect_heartbeat_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latencies = [float(row["latency_ms"]) for row in rows if row.get("success") and row.get("latency_ms") is not None]
    spike_threshold = percentile(latencies, 0.95) or 20.0
    events: list[dict[str, Any]] = []
    failure_streak: list[dict[str, Any]] = []
    for row in rows:
        if row.get("success"):
            if len(failure_streak) >= 2:
                events.append(
                    {
                        "type": "outage",
                        "severity": "high",
                        "target": row.get("target"),
                        "start": failure_streak[0]["measured_at"],
                        "end": failure_streak[-1]["measured_at"],
                        "label": f"连续失败 {len(failure_streak)} 次",
                    }
                )
            failure_streak = []
            latency = row.get("latency_ms")
            if latency is not None and float(latency) >= spike_threshold and float(latency) >= 12:
                events.append(
                    {
                        "type": "latency_spike",
                        "severity": "medium",
                        "target": row.get("target"),
                        "start": row["measured_at"],
                        "end": row["measured_at"],
                        "label": f"延迟毛刺 {float(latency):.1f} ms",
                        "value": round(float(latency), 2),
                    }
                )
        else:
            failure_streak.append(row)
    if len(failure_streak) >= 2:
        events.append(
            {
                "type": "outage",
                "severity": "high",
                "target": failure_streak[-1].get("target"),
                "start": failure_streak[0]["measured_at"],
                "end": failure_streak[-1]["measured_at"],
                "label": f"连续失败 {len(failure_streak)} 次",
            }
        )
    return events[-24:]


def aggregate_heartbeat_rows(rows: list[dict[str, Any]], bucket_minutes: int) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        measured_at = parse_iso(row["measured_at"])
        bucket_dt = floor_time(measured_at, bucket_minutes)
        bucket_key = bucket_dt.isoformat()
        bucket = buckets.setdefault(
            bucket_key,
            {
                "bucket_start": bucket_key,
                "bucket_minutes": bucket_minutes,
                "target": row.get("target"),
                "samples": 0,
                "success_count": 0,
                "failure_count": 0,
                "latencies": [],
            },
        )
        bucket["samples"] += 1
        if row.get("success"):
            bucket["success_count"] += 1
            if row.get("latency_ms") is not None:
                bucket["latencies"].append(float(row["latency_ms"]))
        else:
            bucket["failure_count"] += 1

    output: list[dict[str, Any]] = []
    for _, bucket in sorted(buckets.items()):
        latencies = bucket.pop("latencies")
        avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else None
        output.append(
            {
                **bucket,
                "avg_latency_ms": avg_latency,
                "min_latency_ms": round(min(latencies), 2) if latencies else None,
                "max_latency_ms": round(max(latencies), 2) if latencies else None,
                "p95_latency_ms": percentile(latencies, 0.95),
                "p99_latency_ms": percentile(latencies, 0.99),
                "uptime_ratio": round((bucket["success_count"] / bucket["samples"]) * 100, 2) if bucket["samples"] else 0.0,
            }
        )
    return output


def heartbeat_targets() -> list[dict[str, Any]]:
    with closing(db_connect()) as conn:
        rows = conn.execute(
            """
            SELECT
                target,
                COUNT(*) AS samples,
                MAX(measured_at) AS latest_measured_at,
                AVG(CASE WHEN success = 1 THEN latency_ms END) AS avg_latency_ms,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success_count
            FROM measurements
            WHERE kind = 'heartbeat'
            GROUP BY target
            ORDER BY target ASC
            """
        ).fetchall()
    return [
        {
            "target": row["target"],
            "samples": row["samples"],
            "latest_measured_at": row["latest_measured_at"],
            "avg_latency_ms": round(row["avg_latency_ms"], 2) if row["avg_latency_ms"] is not None else None,
            "success_rate": round((row["success_count"] / row["samples"]) * 100, 2) if row["samples"] else 0.0,
        }
        for row in rows
    ]


def fetch_heartbeat_summary(hours: int) -> dict[str, Any]:
    history = fetch_history("heartbeat", hours, HEARTBEAT_TARGETS[0] if HEARTBEAT_TARGETS else None)
    total_count = len(history)
    success_count = sum(1 for row in history if row.get("success"))
    failure_count = total_count - success_count
    uptime_ratio = round((success_count / total_count) * 100, 2) if total_count else 0.0
    latest = history[-1] if history else None
    latencies = [float(row["latency_ms"]) for row in history if row.get("success") and row.get("latency_ms") is not None]

    current_streak = 0
    max_failure_streak = 0
    streak_start = None
    streak_end = None
    for row in history:
        if row.get("success"):
            current_streak = 0
        else:
            current_streak += 1
            max_failure_streak = max(max_failure_streak, current_streak)
            if current_streak == 1:
                streak_start = row["measured_at"]
            streak_end = row["measured_at"]

    rows_by_day: dict[str, dict[str, int]] = {}
    for row in history:
        day = row["measured_at"][:10]
        bucket = rows_by_day.setdefault(day, {"samples": 0, "failures": 0})
        bucket["samples"] += 1
        if not row.get("success"):
            bucket["failures"] += 1

    day_rollups = [
        {
            "day": day,
            "samples": values["samples"],
            "failures": values["failures"],
            "uptime_ratio": round(((values["samples"] - values["failures"]) / values["samples"]) * 100, 2) if values["samples"] else 0.0,
        }
        for day, values in sorted(rows_by_day.items(), reverse=True)
    ][:14]

    return {
        "hours": hours,
        "target": HEARTBEAT_TARGETS[0] if HEARTBEAT_TARGETS else HEARTBEAT_TARGET,
        "targets": HEARTBEAT_TARGETS,
        "interval_seconds": HEARTBEAT_INTERVAL_SECONDS,
        "total_count": total_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "uptime_ratio": uptime_ratio,
        "latest": latest,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "min_latency_ms": round(min(latencies), 2) if latencies else None,
        "max_latency_ms": round(max(latencies), 2) if latencies else None,
        "current_failure_streak": current_streak,
        "current_failure_window": {
            "start": streak_start if current_streak else None,
            "end": streak_end if current_streak else None,
        },
        "max_failure_streak": max_failure_streak,
        "day_rollups": day_rollups,
    }


def fetch_heartbeat_dashboard(hours: int, bucket: str, target: str | None) -> dict[str, Any]:
    target_name = target or (HEARTBEAT_TARGETS[0] if HEARTBEAT_TARGETS else HEARTBEAT_TARGET)
    bucket_map = {
        "1m": 1,
        "5m": 5,
        "1h": 60,
    }
    bucket_minutes = bucket_map.get(bucket, 5)
    rows = fetch_history("heartbeat", hours, target_name)
    series = aggregate_heartbeat_rows(rows, bucket_minutes)
    latencies = [float(row["latency_ms"]) for row in rows if row.get("success") and row.get("latency_ms") is not None]
    return {
        "hours": hours,
        "bucket": bucket,
        "bucket_minutes": bucket_minutes,
        "target": target_name,
        "series": series,
        "events": detect_heartbeat_events(rows),
        "stats": {
            "samples": len(rows),
            "success_count": sum(1 for row in rows if row.get("success")),
            "failure_count": sum(1 for row in rows if not row.get("success")),
            "uptime_ratio": round((sum(1 for row in rows if row.get("success")) / len(rows)) * 100, 2) if rows else 0.0,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "p95_latency_ms": percentile(latencies, 0.95),
            "p99_latency_ms": percentile(latencies, 0.99),
            "min_latency_ms": round(min(latencies), 2) if latencies else None,
            "max_latency_ms": round(max(latencies), 2) if latencies else None,
        },
    }


@app.route("/")
def index() -> str:
    return render_template(
        "index.html",
        schedule_minutes=SCHEDULE_MINUTES,
        latest=latest_rows(),
        lan_host=LAN_HOST,
        internet_enabled=ENABLE_INTERNET_TEST,
        lan_enabled=ENABLE_LAN_TEST,
        heartbeat_enabled=ENABLE_HEARTBEAT_TEST,
        internet_retries=INTERNET_RETRIES,
        heartbeat_target=HEARTBEAT_TARGETS[0] if HEARTBEAT_TARGETS else HEARTBEAT_TARGET,
        heartbeat_targets=HEARTBEAT_TARGETS,
        thresholds={
            "download_alert_mbps": DOWNLOAD_ALERT_Mbps,
            "upload_alert_mbps": UPLOAD_ALERT_Mbps,
            "latency_alert_ms": LATENCY_ALERT_MS,
            "test_duration_alert_seconds": TEST_DURATION_ALERT_SECONDS,
        },
    )


@app.route("/api/history")
def api_history():
    kind = request.args.get("kind", "internet")
    hours = int(request.args.get("hours", "24"))
    target = request.args.get("target") or None
    if kind not in {"internet", "lan", "heartbeat"}:
        return jsonify({"error": "kind 必须是 internet、lan 或 heartbeat"}), 400
    return jsonify(fetch_history(kind, hours, target))


@app.route("/api/internet/summary")
def api_internet_summary():
    hours = int(request.args.get("hours", "24"))
    return jsonify(fetch_internet_summary(hours))


@app.route("/api/heartbeat/summary")
def api_heartbeat_summary():
    hours = int(request.args.get("hours", "12"))
    return jsonify(fetch_heartbeat_summary(hours))


@app.route("/api/heartbeat/targets")
def api_heartbeat_targets():
    return jsonify(heartbeat_targets())


@app.route("/api/heartbeat/dashboard")
def api_heartbeat_dashboard():
    hours = int(request.args.get("hours", "24"))
    bucket = request.args.get("bucket", "5m")
    target = request.args.get("target") or None
    return jsonify(fetch_heartbeat_dashboard(hours, bucket, target))


@app.route("/api/internet/candidates")
def api_internet_candidates():
    limit = int(request.args.get("limit", "20"))
    return jsonify(list_speedtest_candidates(limit))


@app.route("/api/latest")
def api_latest():
    return jsonify(latest_rows())


@app.route("/api/run", methods=["POST"])
def api_run():
    thread = threading.Thread(target=run_all_tests, daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "测速任务已触发"})


@app.route("/api/admin/cleanup-legacy", methods=["POST"])
def api_cleanup_legacy():
    deleted = cleanup_legacy_internet_samples()
    return jsonify({"ok": True, "deleted": deleted})


@app.route("/api/export.csv")
def api_export():
    temp_file = DATA_DIR / "export.csv"
    with closing(db_connect()) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM measurements
            ORDER BY measured_at ASC
            """
        ).fetchall()

    header = [column for column, _ in BASE_COLUMNS + EXTRA_COLUMNS]
    lines = [",".join(header)]
    for row in rows:
        values = [str(row[key] if row[key] is not None else "") for key in header]
        escaped = ['"' + value.replace('"', '""') + '"' for value in values]
        lines.append(",".join(escaped))
    temp_file.write_text("\n".join(lines), encoding="utf-8")
    return send_file(temp_file, mimetype="text/csv", as_attachment=True, download_name="speed-history.csv")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "db": str(DB_PATH)})


def main() -> None:
    init_db()
    scheduler = threading.Thread(target=scheduler_loop, daemon=True)
    scheduler.start()
    app.run(host="0.0.0.0", port=8080, debug=False)


if __name__ == "__main__":
    main()
