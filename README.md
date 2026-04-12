# NAS Speed Monitor

面向 NAS 的外网监测面板，提供两类长期观测：

- 分钟级心跳探测：多目标 `ping`，用于监控外网连通性、延迟抖动和异常时段
- 周期性正式测速：基于 Ookla 官方 `speedtest` CLI，记录下载、上传、延迟和测速节点历史

项目已经按当前极空间 NAS 的实际部署方式和移动端使用习惯做过优化，适合作为常驻 Docker 服务运行。

## 当前版本

`v0.2.0`  `2026-04-11`

- 单容器部署，SQLite 持久化历史数据
- 心跳展示默认保留 `5m / 1h` 两档，7 天概览的 `1h` 模式会使用 `15m` 细格
- 默认 3 条心跳链路：
  - `223.5.5.5` `AliDNS`，国内主基线
  - `119.29.29.29` `DNSPod`，国内副基线
  - `1.1.1.1` `Cloudflare`，国际近点
- 默认 Speedtest 优选节点池：
  - `3633` `China Telecom / Shanghai`
  - `5396` `China Telecom JiangSu 5G / Suzhou`
  - `30852` `Duke Kunshan University / Kunshan`
  - `59386` `浙江电信 / HangZhou`
- 链路诊断矩阵可区分单点异常、国内链路异常和国际链路异常
- 移动端已做专门适配：
  - 图表单列纵向排列
  - 手机屏幕下缩减留白、放大线条和文字
  - 心跳图和测速图使用独立移动端比例

## v0.2.0 更新摘要

- 看板加载从整页等待改成分区加载，局部失败时其余模块继续可用
- 7 天心跳视图默认自动切到 `1h` 聚合，晶格更紧凑，更容易看全景断联
- 心跳目标汇总改为 grouped SQL，7 天目标摘要明显提速
- Speedtest 图表保留失败样本时间点，单样本区间不再伪造趋势线
- 默认运行策略改为更省电的组合：
  - 心跳间隔 `300s`
  - 心跳目标 `223.5.5.5 / 119.29.29.29 / 1.1.1.1`
  - 正式测速固定时刻 `05:00 / 16:00`
- 首页显示当前版本和正式测速时刻，便于核对线上配置
- 详细版本记录见 [CHANGELOG.md](/Users/tian/Documents/New%20project/CHANGELOG.md)

## 界面示例

以下样图对应当前移动端单列布局，按你提供的手机端界面样本整理，用于说明首屏结构、图表顺序和信息分层：

![移动端界面样例](docs/mobile-layout-sample.svg)

主要模块：

- `连通性晶格`
  - 按时间展示在线率和高延迟状态
  - 适合快速识别断流和波动时段
- `链路诊断矩阵`
  - 对比各目标的平均延迟、`p95`、`p99`、成功率和相对基线偏移
  - 适合判断异常范围是在国内链路、国际链路还是单点目标
- `心跳延迟趋势`
  - 展示平均延迟、`p95`、`p99` 和异常事件
  - 用于观察短时毛刺和尾部风险
- `正式测速趋势`
  - 展示下载、上传和延迟的长期变化
  - 结合测速节点和失败标线判断外网质量
- `底部数据表`
  - 提供心跳目标明细、事件记录和测速历史明细

## 特性

- 多目标心跳探测，默认采样间隔 `300s`
- 心跳展示默认保留 `5m / 1h` 两档，7 天概览的 `1h` 模式会使用 `15m` 细格
- 自动识别断流和延迟毛刺事件
- 心跳图展示 `p95 / p99`
- 正式测速使用 Ookla 官方 CLI
- 支持 Bark 推送通知，适配 Cloudflare Worker Webhook
- 历史数据持久化到 SQLite
- 支持导出 CSV
- 支持手动触发测速
- 支持清理旧版低质量样本
- 可选内网 `iperf3` 测速

## 目录结构

```text
.
├── app.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── docs/
│   └── mobile-layout-sample.svg
├── templates/
│   └── index.html
└── static/
    ├── app.js
    └── style.css
```

## 快速开始

### Docker Compose

```bash
docker compose up -d --build
```

默认访问地址：

```text
http://你的NAS地址:8080
```

### 推荐优先调整的配置

- `INTERNET_SERVER_POOL`
  - 正式测速优选节点池
- `HEARTBEAT_TARGETS`
  - 心跳探测目标列表
- `SCHEDULE_MINUTES`
  - 正式测速周期
- `SCHEDULE_CLOCK_TIMES`
  - 正式测速固定时刻，优先级高于 `SCHEDULE_MINUTES`
- `HEARTBEAT_INTERVAL_SECONDS`
  - 心跳采样周期
- `RETENTION_DAYS`
  - 自动清理历史数据的保留天数
- `LAN_IPERF_HOST`
  - 启用内网测速时填写 `iperf3` 服务端地址

## 配置说明

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `TZ_OFFSET_HOURS` | `8` | 时区偏移 |
| `SCHEDULE_MINUTES` | `120` | 正式测速周期，单位分钟；仅在未设置固定时刻时生效 |
| `SCHEDULE_CLOCK_TIMES` | `05:00,16:00` | 正式测速固定执行时刻，按本地时区每天执行，默认偏向低打扰时段 |
| `RUN_ON_START` | `true` | 容器启动后是否立即跑一次正式测速 |
| `ENABLE_INTERNET_TEST` | `true` | 是否启用外网 Speedtest |
| `ENABLE_LAN_TEST` | `true` | 是否启用内网 `iperf3` |
| `ENABLE_HEARTBEAT_TEST` | `true` | 是否启用心跳探测 |
| `HEARTBEAT_INTERVAL_SECONDS` | `300` | 心跳采样间隔，单位秒 |
| `HEARTBEAT_TARGET` | `223.5.5.5` | 主心跳目标 |
| `HEARTBEAT_TARGETS` | `223.5.5.5,119.29.29.29,1.1.1.1` | 心跳目标列表 |
| `HEARTBEAT_TIMEOUT_SECONDS` | `2` | 单次 `ping` 超时秒数 |
| `INTERNET_SPEEDTEST_SERVER_ID` | 空 | 指定单一测速节点 |
| `INTERNET_SERVER_POOL` | `3633,5396,30852,59386` | 固定测速节点池，失败时自动回退到自动选点 |
| `INTERNET_RETRIES` | `2` | 单次 Speedtest 最多重试次数 |
| `INTERNET_RETRY_DELAY_SECONDS` | `5` | Speedtest 重试间隔 |
| `DOWNLOAD_ALERT_MBPS` | `5` | 下载低于此值标为异常 |
| `UPLOAD_ALERT_MBPS` | `1` | 上传低于此值标为异常 |
| `LATENCY_ALERT_MS` | `100` | 延迟高于此值标为异常 |
| `TEST_DURATION_ALERT_SECONDS` | `60` | 单次测速耗时超过此值标为异常 |
| `LAN_IPERF_HOST` | `192.168.1.2` | 内网 `iperf3` 服务器 IP |
| `LAN_IPERF_PORT` | `5201` | 内网 `iperf3` 端口 |
| `LAN_IPERF_DURATION_SECONDS` | `10` | 单次内网测速时长 |
| `RETENTION_DAYS` | `0` | 数据保留天数，`0` 表示不自动清理 |
| `DATA_DIR` | `/data` | SQLite 数据目录 |
| `ENABLE_BARK_NOTIFICATIONS` | `false` | 是否启用 Bark 通知 |
| `BARK_WEBHOOK_URL` | 空 | Bark 的 Cloudflare Worker Webhook 地址，支持 `/icloud`、`/api/webhook` 或带 `{token}` 占位符的完整路径 |
| `BARK_WEBHOOK_TOKEN` | 空 | Bark Webhook 鉴权 token；如果 URL 末尾是 `/icloud` 或 `/api/webhook`，会自动拼到路径里 |
| `BARK_SOURCE_NAME` | `NAS 外网监测` | 推送消息来源名称 |
| `BARK_DEDUP_MINUTES` | `30` | 相同事件去重窗口 |
| `BARK_DAILY_REPORT_HOUR` | `8` | 每日摘要推送小时 |
| `BARK_DAILY_REPORT_MINUTE` | `30` | 每日摘要推送分钟 |
| `NOTIFY_DOMESTIC_FAILURE_STREAK` | `2` | 国内链路连续失败多少次后触发告警 |
| `NOTIFY_DOMESTIC_LOOKBACK_MINUTES` | `15` | 国内链路告警观察窗口 |
| `NOTIFY_INTERNATIONAL_LOOKBACK_MINUTES` | `30` | 国际链路“转好”观察窗口 |
| `NOTIFY_INTERNATIONAL_SUCCESS_RATE` | `95` | 国际链路视为畅通的成功率阈值 |
| `NOTIFY_INTERNATIONAL_LATENCY_MS` | `120` | 国际链路视为畅通的 p95 延迟阈值 |
| `NOTIFY_SPEEDTEST_DOWNLOAD_MBPS` | `300` | 触发测速严重降速告警的下载阈值 |
| `NOTIFY_SPEEDTEST_UPLOAD_MBPS` | `20` | 触发测速严重异常告警的上传阈值 |
| `NOTIFY_SPEEDTEST_LATENCY_MS` | `80` | 触发测速严重异常告警的延迟阈值 |
| `NOTIFY_SPEEDTEST_DURATION_SECONDS` | `120` | 触发测速严重异常告警的测速耗时阈值 |
| `NOTIFY_SPEEDTEST_STREAK` | `2` | 连续多少次测速严重异常后才推送 |

## 数据存储

通用 Bark 网关接入规范见 [BARK_GATEWAY.md](/Users/tian/Documents/New%20project/BARK_GATEWAY.md)。

默认 SQLite 文件位置：

```text
/data/speed_history.db
```

在 `docker-compose.yml` 中默认映射为：

```yaml
volumes:
  - ./data:/data
```

所以容器升级或重建后，历史数据会保留。

## 已实现接口

- `GET /`
  - Web 看板
- `GET /health`
  - 健康检查
- `GET /api/history`
  - 历史记录
- `GET /api/internet/summary`
  - 外网测速汇总
- `GET /api/heartbeat/summary`
  - 主目标心跳汇总
- `GET /api/heartbeat/targets`
  - 各心跳目标汇总
- `GET /api/heartbeat/dashboard`
  - 聚合心跳视图
- `POST /api/run`
  - 手动触发正式测速
- `POST /api/admin/cleanup-legacy`
  - 清理旧版低质量样本
- `POST /api/admin/test-notify`
  - 发送一条 Bark 测试通知
- `GET /api/export.csv`
  - 导出 CSV

## Bark 推送策略

当前版本的 Bark 策略偏克制，避免高频打扰：

- 国内链路异常
  - 任一国内基线目标连续失败达到阈值后立即推送
  - 恢复后再补一条恢复通知
- 国际链路转好
  - 国际目标在观察窗口内成功率和 `p95` 同时达标时推送
  - 更适合“平时不稳定，偶尔变顺畅时提醒”
- 正式测速严重异常
  - 采用单独、更宽松的通知阈值
  - 只有连续多次明显降速或高延迟才推送
- 每日摘要
  - 每天固定时间推送 24 小时在线率、延迟和测速概况

如果你已有 Cloudflare Worker 转发 Bark，可以直接填写：

```text
ENABLE_BARK_NOTIFICATIONS=true
BARK_WEBHOOK_URL=https://你的-worker/icloud
BARK_WEBHOOK_TOKEN=你的-token
```

也可以直接写成完整路径：

```text
BARK_WEBHOOK_URL=https://你的-worker/icloud/你的-token
```

如果你希望把 Bark 网关单独标准化给其他 NAS 或脚本项目复用，可以参考：

- [BARK_GATEWAY.md](/Users/tian/Documents/New%20project/BARK_GATEWAY.md)

## NAS 部署建议

### 极空间

这一版优先针对极空间做了优化：

- Docker 单容器部署流程更顺畅
- 数据目录和端口映射更适合 NAS 图形界面配置
- 默认目标池和测速节点池可以直接用于外网质量监控
- 运行时不依赖构建代理，适合长期常驻

推荐：

- 端口映射 `8080:8080`
- 数据目录映射到 NAS 本地持久化路径
- 如果只关注外网稳定性，先关闭 `ENABLE_LAN_TEST`

### 群晖 / 威联通

- 映射端口 `8080`
- 映射数据卷到 `/data`
- 使用环境变量控制测速行为
- 如果 NAS 构建镜像依赖代理，运行容器时不建议继承代理变量

## 内网测速

如果需要内网吞吐测试，先在局域网内另一台设备上启动：

```bash
iperf3 -s
```

然后把 `LAN_IPERF_HOST` 改成它的局域网 IP，并尽量满足：

- 设备长期在线
- 优先有线连接
- NAS 到该设备的网络路径稳定

## 已知限制

- Speedtest 结果会受运营商策略、节点负载和出口路由影响
- `8.8.8.8`、`9.9.9.9`、`208.67.222.222` 这类国际目标在部分网络环境下可能出现高延迟或丢包
- `114.114.114.114` 在部分网络环境下会长期限制 ICMP，默认已不再作为首选样本
- 当前前端图表基于 SVG 绘制，更适合监控和排障，不是报表系统

## 后续方向

- 异常告警推送到 Telegram / 企业微信 / 邮件
- 日报和周报导出
- 更细的事件分类
- 公网 IP 变更追踪
- 心跳目标自定义分组
