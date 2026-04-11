# NAS Speed Monitor Next Steps

## Current Context

Project root on this machine:

```text
/Users/tian/Documents/New project
```

Live NAS deployment:

```text
Host: 192.168.31.219
SSH: 13524652333@192.168.31.219 -p 10000
App directory: /opt/nas-speed-monitor
Container: nas-speed-monitor
Image: nas-speed-monitor:latest
Port: http://192.168.31.219:18080
Data volume: /opt/nas-speed-monitor/data:/data
SQLite DB in container: /data/speed_history.db
```

Important live env differences from `docker-compose.yml`:

```text
RUN_ON_START=false
ENABLE_LAN_TEST=false
ENABLE_BARK_NOTIFICATIONS=true
BARK_WEBHOOK_URL=https://bark.wutianhao.com/icloud
BARK_WEBHOOK_TOKEN is set on NAS
Port mapping is 18080:8080, not 8080:8080
```

Do not overwrite the live container with plain `docker compose up` unless you first reconcile those live settings.

## Files To Read First

Read these in order:

```text
README.md
BARK_GATEWAY.md
app.py
templates/index.html
static/app.js
static/style.css
```

For UI changes, use the local skill:

```text
/Users/tian/.codex/skills/taste-skill/SKILL.md
```

No external web documentation is currently required for this task. If changing Ookla Speedtest CLI behavior, inspect the installed CLI output on the NAS instead of relying on memory.

## What Was Recently Changed

The dashboard is a Flask app with vanilla JS/SVG charts and SQLite.

Recent local and deployed changes already landed on the NAS:

- Frontend data loading is now section-based instead of all-or-nothing.
  - Each block has its own loading, error, and empty state.
  - A partial refresh failure no longer wipes other sections.
- Heartbeat target summary is no longer built by looping through `fetch_history(...)` per target.
  - `heartbeat_targets(...)` now uses grouped SQL for counts and aggregates.
  - This removed the main 7-day target summary bottleneck.
- The 7-day heartbeat view is now intentionally coarser by default.
  - For `168h`, the UI automatically prefers `1h` buckets instead of `5m`.
  - The heartbeat lattice also compresses day width and shortens day labels so more of the panorama fits on screen before horizontal scrolling.
- Heartbeat outage event labels remain visible, but only sufficiently separated outage starts are labeled to reduce clutter.
- Speedtest chart now keeps failed samples in the X-axis domain, so failures appear at their real time.
- If a speedtest range has only one successful sample and no failures, the chart shows a single-test summary instead of a fake trend line.
- The homepage now exposes the current speedtest schedule in server-rendered HTML via `data-speedtest-schedule`, so the frontend summary matches the live schedule.
- Default live operating profile was tuned for lower power and less disturbance:
  - `HEARTBEAT_INTERVAL_SECONDS=120`
  - `HEARTBEAT_TARGETS=223.5.5.5,119.29.29.29,1.1.1.1`
  - `SCHEDULE_CLOCK_TIMES=05:00,16:00`
- Backend speedtest errors preserve the first line of CLI output instead of only `exit status 2`.

## Current Observations

Measured on the NAS itself after the latest deployment on `2026-04-11`:

```text
GET /health                          200, db=/data/speed_history.db
GET /                                ~0.08s, 6.6KB
GET /api/heartbeat/dashboard?hours=6&bucket=5m&target=223.5.5.5  ~0.16s, 25KB
GET /api/heartbeat/targets?hours=24  ~3.50s, 1.1KB
GET /api/heartbeat/targets?hours=168 ~1.35s, 1.1KB
```

Database size and record counts:

```text
/data/speed_history.db: about 39MB
heartbeat rows: about 61,305
internet rows: about 242
```

The biggest user-facing problem is no longer backend compute cost. At this point:

- The current single-container Flask + SQLite architecture is already close to the lowest-power shape that still meets the requirement.
- The remaining tradeoff is mostly sampling density versus visibility:
  - fewer heartbeat targets and longer heartbeat intervals reduce wakeups and DB growth
  - fewer formal speedtests reduce network usage, CLI runtime, and transient CPU spikes
- Browser-to-NAS access may still be affected by local proxy settings; local shell tests initially tried to use `127.0.0.1:7897` as a proxy and failed until bypassed.

## Speedtest Status

Today, `2026-04-11`, scheduled speedtests did run at approximately:

```text
01:32
07:32
13:32
19:33
```

All four failed. Last successful speedtest is:

```text
2026-04-10 19:30
```

The historical failures above happened before the schedule was changed. The currently deployed fixed schedule is now:

```text
05:00
16:00
```

Manual test inside the container:

```bash
docker exec nas-speed-monitor speedtest --accept-license --accept-gdpr -s 3633 -f json
```

Observed output:

```text
{"error":"Latency test failed"}
```

`speedtest -L -f json` can list servers, so the container is not fully offline. The failure is during the actual latency test phase.

## Next Tasks

1. Investigate the current Speedtest CLI failure.
   - Check whether specific nodes fail or all actual tests fail:

```bash
sudo docker exec nas-speed-monitor speedtest --accept-license --accept-gdpr -s 3633 -f json
sudo docker exec nas-speed-monitor speedtest --accept-license --accept-gdpr -s 5396 -f json
sudo docker exec nas-speed-monitor speedtest --accept-license --accept-gdpr -f json
```

   - If all return `Latency test failed`, inspect NAS outbound firewall/proxy/routing or Ookla node reachability.
   - Do not trigger repeated full tests too aggressively.

2. Decide whether fixed low-disturbance speedtest windows are enough.
   - Right now the system uses fixed quiet-hour windows: `05:00 / 16:00`.
   - A truly adaptive schedule is possible, but it is not implemented yet.
   - The lightest next step would be:
     - track recent successful heartbeat latency plus recent NAS network counters
     - choose the next speedtest from a small candidate window set
     - skip or delay a run when current activity is above a threshold
   - This should stay conservative; formal speedtests are expensive compared with heartbeat pings.

3. Re-check whether `24h` target summary should be optimized further.
   - Current probe was about `3.50s`, which is acceptable for a secondary panel but still noticeably slower than the rest of the page.
   - If needed later, reduce percentile work further or pre-aggregate by time window.

## Deployment Procedure

Because the NAS container runs with live settings that differ from `docker-compose.yml`, preserve the existing env and port mapping.

Sync changed files:

```bash
scp -O -P 10000 app.py 13524652333@192.168.31.219:/opt/nas-speed-monitor/app.py
scp -O -P 10000 templates/index.html 13524652333@192.168.31.219:/opt/nas-speed-monitor/templates/index.html
scp -O -P 10000 static/app.js 13524652333@192.168.31.219:/opt/nas-speed-monitor/static/app.js
scp -O -P 10000 static/style.css 13524652333@192.168.31.219:/opt/nas-speed-monitor/static/style.css
```

On the NAS, rebuild while preserving env:

```bash
cd /opt/nas-speed-monitor
sudo docker inspect nas-speed-monitor --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -Ev '^(PATH|LANG|GPG_KEY|PYTHON_VERSION|PYTHON_SHA256|PYTHONDONTWRITEBYTECODE|PYTHONUNBUFFERED)=' \
  > .runtime.env
grep -q '^HEARTBEAT_INTERVAL_SECONDS=' .runtime.env && sed -i 's/^HEARTBEAT_INTERVAL_SECONDS=.*/HEARTBEAT_INTERVAL_SECONDS=120/' .runtime.env || echo 'HEARTBEAT_INTERVAL_SECONDS=120' >> .runtime.env
grep -q '^HEARTBEAT_TARGET=' .runtime.env && sed -i 's/^HEARTBEAT_TARGET=.*/HEARTBEAT_TARGET=223.5.5.5/' .runtime.env || echo 'HEARTBEAT_TARGET=223.5.5.5' >> .runtime.env
grep -q '^HEARTBEAT_TARGETS=' .runtime.env && sed -i 's/^HEARTBEAT_TARGETS=.*/HEARTBEAT_TARGETS=223.5.5.5,119.29.29.29,1.1.1.1/' .runtime.env || echo 'HEARTBEAT_TARGETS=223.5.5.5,119.29.29.29,1.1.1.1' >> .runtime.env
grep -q '^SCHEDULE_CLOCK_TIMES=' .runtime.env && sed -i 's/^SCHEDULE_CLOCK_TIMES=.*/SCHEDULE_CLOCK_TIMES=05:00,16:00/' .runtime.env || echo 'SCHEDULE_CLOCK_TIMES=05:00,16:00' >> .runtime.env
sudo chmod 600 .runtime.env
sudo docker build -t nas-speed-monitor:latest .
sudo docker rm -f nas-speed-monitor
sudo docker run -d \
  --name nas-speed-monitor \
  --restart unless-stopped \
  --env-file /opt/nas-speed-monitor/.runtime.env \
  -p 18080:8080 \
  -v /opt/nas-speed-monitor/data:/data \
  nas-speed-monitor:latest
sudo rm -f .runtime.env
```

Verify:

```bash
curl -sS http://127.0.0.1:18080/health
curl -sS -o /dev/null -w 'index %{http_code} %{time_total} %{size_download}\n' \
  http://127.0.0.1:18080/
curl -sS -o /dev/null -w 'targets24 %{http_code} %{time_total} %{size_download}\n' \
  'http://127.0.0.1:18080/api/heartbeat/targets?hours=24'
curl -sS -o /dev/null -w 'targets168 %{http_code} %{time_total} %{size_download}\n' \
  'http://127.0.0.1:18080/api/heartbeat/targets?hours=168'
```
