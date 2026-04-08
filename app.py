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
from urllib.parse import urlparse, urlunparse
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
SCHEDULE_MINUTES = env_int("SCHEDULE_MINUTES", 120)
SCHEDULE_CLOCK_TIMES = [
    item.strip()
    for item in os.getenv("SCHEDULE_CLOCK_TIMES", "").split(",")
    if item.strip()
]
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
    for item in os.getenv("HEARTBEAT_TARGETS", f"{HEARTBEAT_TARGET},119.29.29.29,180.76.76.76,1.1.1.1,8.8.8.8").split(",")
    if item.strip()
]
NOTIFY_INTERNATIONAL_TARGETS = [
    item.strip()
    for item in os.getenv("NOTIFY_INTERNATIONAL_TARGETS", "8.8.8.8").split(",")
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
ENABLE_BARK_NOTIFICATIONS = env_bool("ENABLE_BARK_NOTIFICATIONS", False)
BARK_WEBHOOK_URL = os.getenv("BARK_WEBHOOK_URL", "").strip()
BARK_WEBHOOK_TOKEN = os.getenv("BARK_WEBHOOK_TOKEN", "").strip()
BARK_SOURCE_NAME = os.getenv("BARK_SOURCE_NAME", "NAS 外网监测").strip() or "NAS 外网监测"
BARK_PUSH_TIMEOUT_SECONDS = env_float("BARK_PUSH_TIMEOUT_SECONDS", 8.0)
BARK_DEDUP_MINUTES = env_int("BARK_DEDUP_MINUTES", 30)
BARK_DAILY_REPORT_HOUR = env_int("BARK_DAILY_REPORT_HOUR", 9)
BARK_DAILY_REPORT_MINUTE = env_int("BARK_DAILY_REPORT_MINUTE", 0)
NOTIFY_DOMESTIC_FAILURE_STREAK = env_int("NOTIFY_DOMESTIC_FAILURE_STREAK", 2)
NOTIFY_DOMESTIC_LOOKBACK_MINUTES = env_int("NOTIFY_DOMESTIC_LOOKBACK_MINUTES", 15)
NOTIFY_INTERNATIONAL_LOOKBACK_MINUTES = env_int("NOTIFY_INTERNATIONAL_LOOKBACK_MINUTES", 30)
NOTIFY_INTERNATIONAL_SUCCESS_RATE = env_float("NOTIFY_INTERNATIONAL_SUCCESS_RATE", 98.0)
NOTIFY_INTERNATIONAL_LATENCY_MS = env_float("NOTIFY_INTERNATIONAL_LATENCY_MS", 190.0)
NOTIFY_INTERNATIONAL_ANOMALY_SUCCESS_RATE = env_float("NOTIFY_INTERNATIONAL_ANOMALY_SUCCESS_RATE", 80.0)
NOTIFY_INTERNATIONAL_ANOMALY_LATENCY_MS = env_float("NOTIFY_INTERNATIONAL_ANOMALY_LATENCY_MS", 220.0)
NOTIFY_INTERNATIONAL_FAILURE_STREAK = env_int("NOTIFY_INTERNATIONAL_FAILURE_STREAK", 3)
NOTIFY_INTERNATIONAL_BAD_TARGETS = env_int("NOTIFY_INTERNATIONAL_BAD_TARGETS", 2)
NOTIFY_INTERNATIONAL_RECOVERY_MINUTES = env_int("NOTIFY_INTERNATIONAL_RECOVERY_MINUTES", 15)
NOTIFY_SPEEDTEST_DOWNLOAD_MBPS = env_float("NOTIFY_SPEEDTEST_DOWNLOAD_MBPS", 300.0)
NOTIFY_SPEEDTEST_UPLOAD_MBPS = env_float("NOTIFY_SPEEDTEST_UPLOAD_MBPS", 20.0)
NOTIFY_SPEEDTEST_LATENCY_MS = env_float("NOTIFY_SPEEDTEST_LATENCY_MS", 80.0)
NOTIFY_SPEEDTEST_DURATION_SECONDS = env_float("NOTIFY_SPEEDTEST_DURATION_SECONDS", 120.0)
NOTIFY_SPEEDTEST_STREAK = env_int("NOTIFY_SPEEDTEST_STREAK", 2)


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
HEARTBEAT_TARGET_CATALOG: dict[str, dict[str, str]] = {
    "223.5.5.5": {
        "group": "domestic",
        "label": "AliDNS",
        "provider": "Alibaba Cloud",
        "role": "国内主基线",
    },
    "119.29.29.29": {
        "group": "domestic",
        "label": "DNSPod",
        "provider": "Tencent Cloud",
        "role": "国内副基线",
    },
    "180.76.76.76": {
        "group": "domestic",
        "label": "Baidu DNS",
        "provider": "Baidu",
        "role": "国内次级对照",
    },
    "1.1.1.1": {
        "group": "international",
        "label": "Cloudflare",
        "provider": "Cloudflare",
        "role": "国际近点",
    },
    "8.8.8.8": {
        "group": "international",
        "label": "Google Public DNS",
        "provider": "Google",
        "role": "国际高延迟对照",
    },
    "9.9.9.9": {
        "group": "international",
        "label": "Quad9",
        "provider": "Quad9",
        "role": "国际备用对照",
    },
    "208.67.222.222": {
        "group": "international",
        "label": "OpenDNS",
        "provider": "Cisco OpenDNS",
        "role": "国际备用对照",
    },
}


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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT NOT NULL
            )
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


def get_state(key: str, default: str | None = None) -> str | None:
    with closing(db_connect()) as conn:
        row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(key: str, value: str) -> None:
    with closing(db_connect()) as conn:
        conn.execute(
            """
            INSERT INTO app_state(key, value, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, iso_now()),
        )
        conn.commit()


def get_state_json(key: str, default: Any) -> Any:
    raw = get_state(key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def set_state_json(key: str, value: Any) -> None:
    set_state(key, json.dumps(value, ensure_ascii=False))


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


def parse_schedule_clock(value: str) -> tuple[int, int]:
    parts = value.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"无效的定时格式: {value}")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"无效的定时时间: {value}")
    return hour, minute


def normalized_schedule_clocks() -> list[tuple[int, int]]:
    clocks: list[tuple[int, int]] = []
    for item in SCHEDULE_CLOCK_TIMES:
        try:
            clocks.append(parse_schedule_clock(item))
        except ValueError:
            continue
    return sorted(set(clocks))


def next_scheduled_run(after: datetime | None = None) -> datetime:
    base = after or local_now()
    clocks = normalized_schedule_clocks()
    if not clocks:
        return base + timedelta(minutes=max(SCHEDULE_MINUTES, 1))

    candidates: list[datetime] = []
    for day_offset in (0, 1):
        target_day = (base + timedelta(days=day_offset)).date()
        for hour, minute in clocks:
            candidate = datetime.combine(
                target_day,
                datetime.min.time(),
                tzinfo=base.tzinfo,
            ).replace(hour=hour, minute=minute)
            if candidate > base:
                candidates.append(candidate)
    return min(candidates) if candidates else base + timedelta(days=1)


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
    evaluate_notifications("heartbeat")


def run_all_tests() -> None:
    if not job_lock.acquire(blocking=False):
        return
    try:
        if ENABLE_INTERNET_TEST:
            run_internet_test()
        if ENABLE_LAN_TEST:
            run_lan_test()
        prune_old_data()
        evaluate_notifications("speedtest")
    finally:
        job_lock.release()


def scheduler_loop() -> None:
    if RUN_ON_START:
        run_all_tests()
    if ENABLE_HEARTBEAT_TEST:
        run_heartbeat_test()

    next_speedtest_at = next_scheduled_run()
    next_heartbeat = time.monotonic() + max(HEARTBEAT_INTERVAL_SECONDS, 1)
    while not stop_event.is_set():
        speedtest_wait = max(0.5, (next_speedtest_at - local_now()).total_seconds())
        heartbeat_wait = max(0.5, next_heartbeat - time.monotonic())
        wait_for = max(0.5, min(speedtest_wait, heartbeat_wait))
        if stop_event.wait(wait_for):
            break
        now = time.monotonic()
        if ENABLE_HEARTBEAT_TEST and now >= next_heartbeat:
            run_heartbeat_test()
            next_heartbeat = now + max(HEARTBEAT_INTERVAL_SECONDS, 1)
        if local_now() >= next_speedtest_at:
            run_all_tests()
            next_speedtest_at = next_scheduled_run()


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


def recent_rows(kind: str, minutes: int, target: str | None = None) -> list[dict[str, Any]]:
    rows = fetch_history(kind, max(1, int((minutes / 60) + 1)), target)
    cutoff = local_now() - timedelta(minutes=minutes)
    return [row for row in rows if parse_iso(row["measured_at"]) >= cutoff]


def notify_speedtest_flags(row: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if row.get("success") != 1:
        flags.append("speedtest_failed")
        return flags
    if row.get("download_mbps") is not None and float(row["download_mbps"]) < NOTIFY_SPEEDTEST_DOWNLOAD_MBPS:
        flags.append("download_low")
    if row.get("upload_mbps") is not None and float(row["upload_mbps"]) < NOTIFY_SPEEDTEST_UPLOAD_MBPS:
        flags.append("upload_low")
    if row.get("latency_ms") is not None and float(row["latency_ms"]) > NOTIFY_SPEEDTEST_LATENCY_MS:
        flags.append("latency_high")
    if row.get("test_duration_ms") is not None and int(row["test_duration_ms"]) > int(NOTIFY_SPEEDTEST_DURATION_SECONDS * 1000):
        flags.append("duration_high")
    return flags


def bark_enabled() -> bool:
    return ENABLE_BARK_NOTIFICATIONS and bool(BARK_WEBHOOK_URL)


def bark_post(title: str, body: str) -> tuple[bool, str]:
    if not bark_enabled():
        return False, "Bark 未启用"
    webhook_url = BARK_WEBHOOK_URL
    parsed = urlparse(webhook_url)
    is_bark_api_v2 = parsed.path.rstrip("/") in {"", "/push"}

    if is_bark_api_v2 and BARK_WEBHOOK_TOKEN:
        push_path = "/push"
        if parsed.path.rstrip("/") == "/push":
            push_path = parsed.path or "/push"
        webhook_url = urlunparse(parsed._replace(path=push_path, params="", query="", fragment=""))
        payload = {
            "title": f"{BARK_SOURCE_NAME} - {title}".strip(),
            "body": body.strip(),
            "device_key": BARK_WEBHOOK_TOKEN,
        }
    elif BARK_WEBHOOK_TOKEN and "{token}" in webhook_url:
        webhook_url = webhook_url.replace("{token}", BARK_WEBHOOK_TOKEN)
        payload = {
            "data": f"{BARK_SOURCE_NAME} - {title}\n{body}".strip(),
        }
    elif BARK_WEBHOOK_TOKEN and webhook_url.rstrip("/").endswith("/icloud"):
        webhook_url = f"{webhook_url.rstrip('/')}/{BARK_WEBHOOK_TOKEN}"
        payload = {
            "data": f"{BARK_SOURCE_NAME} - {title}\n{body}".strip(),
        }
    elif BARK_WEBHOOK_TOKEN and webhook_url.rstrip("/").endswith("/api/webhook"):
        webhook_url = f"{webhook_url.rstrip('/')}/{BARK_WEBHOOK_TOKEN}"
        payload = {
            "data": f"{BARK_SOURCE_NAME} - {title}\n{body}".strip(),
        }
    else:
        payload = {
            "data": f"{BARK_SOURCE_NAME} - {title}\n{body}".strip(),
        }
    cmd = [
        "curl",
        "-sS",
        "-X",
        "POST",
        webhook_url,
        "-H",
        "content-type: application/json",
        "--data",
        json.dumps(payload, ensure_ascii=False),
    ]
    if (
        BARK_WEBHOOK_TOKEN
        and not is_bark_api_v2
        and "{token}" not in BARK_WEBHOOK_URL
        and not BARK_WEBHOOK_URL.rstrip("/").endswith("/icloud")
        and not BARK_WEBHOOK_URL.rstrip("/").endswith("/api/webhook")
    ):
        cmd.extend(["-H", f"x-icloudpd-token: {BARK_WEBHOOK_TOKEN}"])
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=max(3, int(BARK_PUSH_TIMEOUT_SECONDS)),
        )
        text = (completed.stdout or "").strip() or (completed.stderr or "").strip() or "ok"
        return True, text
    except subprocess.CalledProcessError as exc:
        return False, (exc.stderr or exc.stdout or str(exc)).strip()
    except subprocess.TimeoutExpired:
        return False, "Bark webhook 请求超时"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def should_send_notification(event_key: str, dedup_minutes: int | None = None) -> bool:
    dedup = dedup_minutes if dedup_minutes is not None else BARK_DEDUP_MINUTES
    last_sent = get_state(f"notify:last_sent:{event_key}")
    if not last_sent:
        return True
    return parse_iso(last_sent) <= (local_now() - timedelta(minutes=dedup))


def mark_notification_sent(event_key: str) -> None:
    set_state(f"notify:last_sent:{event_key}", iso_now())


def transition_flag_state(name: str, active: bool) -> tuple[bool, bool]:
    key = f"notify:state:{name}"
    previous = get_state(key, "0") == "1"
    current = "1" if active else "0"
    if current != ("1" if previous else "0"):
        set_state(key, current)
    return previous, active


def send_bark_notification(event_key: str, title: str, body: str, dedup_minutes: int | None = None) -> bool:
    if not bark_enabled() or not should_send_notification(event_key, dedup_minutes):
        return False
    ok, response_text = bark_post(title, body)
    if ok:
        mark_notification_sent(event_key)
    else:
        set_state(f"notify:last_error:{event_key}", response_text)
    return ok


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


def classify_heartbeat_target(target: str) -> str:
    return HEARTBEAT_TARGET_CATALOG.get(target, {}).get("group", "international")


def heartbeat_target_meta(target: str) -> dict[str, str]:
    return HEARTBEAT_TARGET_CATALOG.get(
        target,
        {
            "group": classify_heartbeat_target(target),
            "label": target,
            "provider": "Custom",
            "role": "自定义目标",
        },
    )


def heartbeat_targets(hours: int = 24) -> list[dict[str, Any]]:
    cutoff = (local_now() - timedelta(hours=hours)).isoformat() if hours > 0 else None
    output: list[dict[str, Any]] = []
    primary_target = HEARTBEAT_TARGETS[0] if HEARTBEAT_TARGETS else HEARTBEAT_TARGET
    baseline_avg = None

    for target in HEARTBEAT_TARGETS:
        rows = fetch_history("heartbeat", hours, target)
        samples = len(rows)
        success_rows = [row for row in rows if row.get("success")]
        latencies = [float(row["latency_ms"]) for row in success_rows if row.get("latency_ms") is not None]
        latest = rows[-1] if rows else None
        summary = {
            "target": target,
            **heartbeat_target_meta(target),
            "samples": samples,
            "latest_measured_at": latest["measured_at"] if latest else None,
            "latest_success": latest.get("success") if latest else None,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "p95_latency_ms": percentile(latencies, 0.95),
            "p99_latency_ms": percentile(latencies, 0.99),
            "success_rate": round((len(success_rows) / samples) * 100, 2) if samples else 0.0,
            "failure_count": samples - len(success_rows),
        }
        if target == primary_target:
            baseline_avg = summary["avg_latency_ms"]
        output.append(summary)

    for item in output:
        if baseline_avg is not None and item["avg_latency_ms"] is not None:
            item["delta_vs_primary_ms"] = round(item["avg_latency_ms"] - baseline_avg, 2)
        else:
            item["delta_vs_primary_ms"] = None
        if item["success_rate"] < 95 or (item["latest_success"] is False):
            item["health"] = "degraded"
        elif item["avg_latency_ms"] is not None and item["avg_latency_ms"] > 60:
            item["health"] = "slow"
        else:
            item["health"] = "healthy"

    output.sort(key=lambda item: (item["group"], item["target"]))
    return output


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


def consecutive_failures(rows: list[dict[str, Any]]) -> int:
    streak = 0
    for row in reversed(rows):
        if row.get("success"):
            break
        streak += 1
    return streak


def evaluate_domestic_notifications() -> None:
    domestic_targets = [target for target in HEARTBEAT_TARGETS if classify_heartbeat_target(target) == "domestic"]
    for target in domestic_targets:
        rows = recent_rows("heartbeat", NOTIFY_DOMESTIC_LOOKBACK_MINUTES, target)
        if not rows:
            continue
        streak = consecutive_failures(rows)
        latest = rows[-1]
        active = streak >= NOTIFY_DOMESTIC_FAILURE_STREAK
        previous, current = transition_flag_state(f"domestic_outage:{target}", active)
        meta = heartbeat_target_meta(target)
        if current and not previous:
            send_bark_notification(
                f"domestic_outage:{target}",
                "国内链路异常",
                f"{target} {meta['label']} 连续失败 {streak} 次，最近一次时间 {latest['measured_at']}。",
                dedup_minutes=10,
            )
        elif previous and not current:
            latency = latest.get("latency_ms")
            latency_text = f"{float(latency):.2f} ms" if latency is not None else "恢复"
            send_bark_notification(
                f"domestic_outage_recovery:{target}",
                "国内链路恢复",
                f"{target} {meta['label']} 已恢复，当前延迟 {latency_text}，恢复时间 {latest['measured_at']}。",
                dedup_minutes=10,
            )


def international_target_status(target: str, lookback_minutes: int) -> dict[str, Any] | None:
    rows = recent_rows("heartbeat", lookback_minutes, target)
    if not rows:
        return None
    success_rows = [row for row in rows if row.get("success") and row.get("latency_ms") is not None]
    latencies = [float(row["latency_ms"]) for row in success_rows]
    success_rate = round((len(success_rows) / len(rows)) * 100, 2) if rows else 0.0
    p95_latency = percentile(latencies, 0.95)
    latest = rows[-1]
    streak = consecutive_failures(rows)
    return {
        "target": target,
        "meta": heartbeat_target_meta(target),
        "rows": rows,
        "latest": latest,
        "success_rate": success_rate,
        "p95_latency_ms": p95_latency,
        "failure_streak": streak,
    }


def evaluate_international_notifications() -> None:
    international_targets = [
        target for target in NOTIFY_INTERNATIONAL_TARGETS
        if target in HEARTBEAT_TARGETS and classify_heartbeat_target(target) == "international"
    ]
    anomaly_statuses = [
        international_target_status(target, NOTIFY_INTERNATIONAL_LOOKBACK_MINUTES)
        for target in international_targets
    ]
    anomaly_statuses = [item for item in anomaly_statuses if item]
    if not anomaly_statuses:
        return

    bad_targets = []
    for status in anomaly_statuses:
        success_rate = status["success_rate"]
        p95_latency = status["p95_latency_ms"]
        failure_streak = status["failure_streak"]
        is_bad = bool(
            success_rate < NOTIFY_INTERNATIONAL_ANOMALY_SUCCESS_RATE
            or failure_streak >= NOTIFY_INTERNATIONAL_FAILURE_STREAK
            or (p95_latency is not None and p95_latency > NOTIFY_INTERNATIONAL_ANOMALY_LATENCY_MS)
        )
        if is_bad:
            bad_targets.append(status)

    min_bad_targets = min(NOTIFY_INTERNATIONAL_BAD_TARGETS, len(international_targets))
    anomaly_active = len(bad_targets) >= max(1, min_bad_targets)
    previous_anomaly, current_anomaly = transition_flag_state("international_outage", anomaly_active)
    if current_anomaly and not previous_anomaly:
        parts = []
        for status in bad_targets:
            meta = status["meta"]
            latest = status["latest"]
            latency_text = (
                f"p95 {status['p95_latency_ms']:.2f} ms"
                if status["p95_latency_ms"] is not None else "p95 --"
            )
            parts.append(
                f"{status['target']} {meta['label']} 成功率 {status['success_rate']:.2f}%，"
                f"{latency_text}，连续失败 {status['failure_streak']} 次，最近一次 {latest['measured_at']}"
            )
        send_bark_notification(
            "international_outage",
            "国际链路明显波动",
            f"最近 {NOTIFY_INTERNATIONAL_LOOKBACK_MINUTES} 分钟内有 {len(bad_targets)} 个国际目标同时异常："
            + "；".join(parts),
            dedup_minutes=45,
        )

    recovery_statuses = [
        international_target_status(target, NOTIFY_INTERNATIONAL_RECOVERY_MINUTES)
        for target in international_targets
    ]
    recovery_statuses = [item for item in recovery_statuses if item]
    recovery_active = bool(
        recovery_statuses
        and len(recovery_statuses) == len(international_targets)
        and all(
            status["failure_streak"] == 0
            and status["success_rate"] >= NOTIFY_INTERNATIONAL_SUCCESS_RATE
            and status["p95_latency_ms"] is not None
            and status["p95_latency_ms"] <= NOTIFY_INTERNATIONAL_LATENCY_MS
            for status in recovery_statuses
        )
    )
    previous_recovery, current_recovery = transition_flag_state("international_good", recovery_active)
    if previous_anomaly and not current_anomaly and current_recovery and not previous_recovery:
        summary = "；".join(
            [
                f"{status['target']} {status['meta']['label']} 成功率 {status['success_rate']:.2f}%，p95 {status['p95_latency_ms']:.2f} ms"
                for status in recovery_statuses
            ]
        )
        send_bark_notification(
            "international_good",
            "国际链路恢复稳定",
            f"最近 {NOTIFY_INTERNATIONAL_RECOVERY_MINUTES} 分钟国际目标恢复稳定：{summary}",
            dedup_minutes=120,
        )


def evaluate_speedtest_notifications() -> None:
    rows = fetch_history("internet", 24)
    if not rows:
        return
    success_rows = [row for row in rows if row.get("success")]
    latest_success = success_rows[-1] if success_rows else None
    latest_rows = success_rows[-NOTIFY_SPEEDTEST_STREAK:] if success_rows else []
    active = len(latest_rows) >= NOTIFY_SPEEDTEST_STREAK and all(notify_speedtest_flags(row) for row in latest_rows)
    previous, current = transition_flag_state("speedtest_anomaly", active)
    if current and not previous and latest_success:
        flags = notify_speedtest_flags(latest_success)
        parts = [
            f"下载 {latest_success.get('download_mbps', '--')} Mbps",
            f"上传 {latest_success.get('upload_mbps', '--')} Mbps",
            f"延迟 {latest_success.get('latency_ms', '--')} ms",
        ]
        if latest_success.get("server_sponsor") or latest_success.get("server_name"):
            parts.append(f"节点 {(latest_success.get('server_sponsor') or latest_success.get('server_name'))}")
        send_bark_notification(
            "speedtest_anomaly",
            "测速明显异常",
            f"连续 {NOTIFY_SPEEDTEST_STREAK} 次测速异常，命中 {', '.join(flags)}。{'，'.join(parts)}。",
            dedup_minutes=90,
        )
    elif previous and not current and latest_success:
        send_bark_notification(
            "speedtest_recovery",
            "测速恢复",
            f"下载 {latest_success.get('download_mbps', '--')} Mbps，上传 {latest_success.get('upload_mbps', '--')} Mbps，延迟 {latest_success.get('latency_ms', '--')} ms。",
            dedup_minutes=90,
        )


def evaluate_daily_report_notification() -> None:
    now = local_now()
    if now.hour != BARK_DAILY_REPORT_HOUR or now.minute < BARK_DAILY_REPORT_MINUTE:
        return
    report_day = now.strftime("%Y-%m-%d")
    if get_state("notify:daily_report_day") == report_day:
        return
    heartbeat = fetch_heartbeat_summary(24)
    internet = fetch_internet_summary(24)
    targets = heartbeat_targets(24)
    international_status = [item for item in targets if item["group"] == "international"]
    international_ok = sum(1 for item in international_status if item["health"] == "healthy")
    latest = internet.get("latest_success") or {}
    international_parts = []
    for item in international_status:
        label = item.get("label") or item.get("provider") or item["target"]
        health_text = {
            "healthy": "正常",
            "slow": "偏慢",
            "degraded": "异常",
        }.get(item.get("health"), "未知")
        avg_text = f"{item['avg_latency_ms']:.2f} ms" if item.get("avg_latency_ms") is not None else "--"
        p95_text = f"{item['p95_latency_ms']:.2f} ms" if item.get("p95_latency_ms") is not None else "--"
        international_parts.append(
            f"{label} {health_text}，成功率 {item['success_rate']:.2f}%，均值 {avg_text}，p95 {p95_text}"
        )
    international_summary = (
        f"国际健康 {international_ok}/{len(international_status)}；" + "；".join(international_parts)
        if international_status else "国际目标暂无样本"
    )
    body = (
        f"24h 连通率 {heartbeat['uptime_ratio']:.2f}%，主目标均值 {heartbeat.get('avg_latency_ms') or '--'} ms；"
        f"测速均值 下载 {round(internet.get('avg_download_mbps') or 0, 2)} Mbps / 上传 {round(internet.get('avg_upload_mbps') or 0, 2)} Mbps / 延迟 {round(internet.get('avg_latency_ms') or 0, 2)} ms；"
        f"{international_summary}；"
        f"最近测速节点 {latest.get('server_sponsor') or latest.get('server_name') or '--'}。"
    )
    if send_bark_notification("daily_report", "网络日报", body, dedup_minutes=60):
        set_state("notify:daily_report_day", report_day)


def evaluate_notifications(trigger: str) -> None:
    if not bark_enabled():
        return
    if trigger in {"heartbeat", "all"}:
        evaluate_international_notifications()
    if trigger in {"speedtest", "all"}:
        evaluate_speedtest_notifications()
    evaluate_daily_report_notification()


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
    hours = int(request.args.get("hours", "24"))
    return jsonify(heartbeat_targets(hours))


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


@app.route("/api/admin/test-notify", methods=["POST"])
def api_test_notify():
    ok = send_bark_notification(
        "manual_test",
        "测试通知",
        "这是一条来自 NAS 外网监测面板的测试消息，用于确认 Bark 推送链路可用。",
        dedup_minutes=0,
    )
    return jsonify({"ok": ok, "enabled": bark_enabled()})


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
