# NAS Speed Monitor

面向 NAS 的网络监控面板，重点做两类观测：

- 轻量外网连通性探测：多目标 `ping`，分钟级采样，支持 `1m / 5m / 1h` 聚合
- 正式外网测速：Ookla 官方 `speedtest` CLI，持久化历史结果并展示趋势

项目适合群晖、威联通和其他可运行 Docker 的 NAS。默认数据使用 SQLite 持久化，页面内置历史曲线、异常标记、p95/p99 视图和事件标注。

当前这版已经按极空间 NAS 的实际部署路径做过一轮优化，尤其是：

- Docker 单容器部署流程更直接
- 数据目录和端口映射更适合 NAS 图形界面配置
- 默认节点池更偏向国内，极空间上开箱即用更顺畅
- 运行时不依赖构建代理，适合在 NAS 上长期常驻

## 特性

- 多目标心跳探测：默认监控 `223.5.5.5`、`114.114.114.114`、`1.1.1.1`
- 分钟级连通性晶格：适合快速判断外网是否稳定
- 聚合视图：支持分钟、5 分钟、小时三级粒度
- 异常事件：自动识别断流和延迟毛刺
- p95 / p99 延迟视图：比均值更容易看出抖动
- 正式 Speedtest：使用 Ookla 官方 CLI，而不是 Python 第三方实现
- 上海电信优选节点池：默认 `3633,5396,30852,59386`
- 历史持久化：SQLite 存储，容器重建后数据仍保留
- 手动测速、CSV 导出、旧样本清理
- 可选内网 `iperf3` 测速

## 界面概览

- 顶部：多目标心跳监控、时间范围切换、聚合粒度切换
- 中部：Speedtest 趋势图，带采样点、毛刺、阈值线和关键标签
- 侧栏：当前结论、最近变化、关键注释
- 下部：辅助画像、异常时段、失败记录、历史明细

## 目录结构

```text
.
├── app.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── templates/
│   └── index.html
└── static/
    ├── app.js
    └── style.css
```

## 快速开始

### 1. 直接使用 Docker Compose

```bash
docker compose up -d --build
```

默认访问地址：

```text
http://你的NAS地址:8080
```

### 2. 推荐先修改的配置

最重要的几个环境变量：

- `INTERNET_SERVER_POOL`：固定优选测速节点池
- `HEARTBEAT_TARGETS`：多目标心跳探测地址
- `SCHEDULE_MINUTES`：正式测速周期
- `HEARTBEAT_INTERVAL_SECONDS`：心跳采样间隔
- `RETENTION_DAYS`：数据保留天数
- `LAN_IPERF_HOST`：如果启用内网测速，需要填写 `iperf3` 服务端 IP

## 配置说明

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `TZ_OFFSET_HOURS` | `8` | 时区偏移 |
| `SCHEDULE_MINUTES` | `30` | 正式测速周期，单位分钟 |
| `RUN_ON_START` | `true` | 容器启动后是否立即跑一次正式测速 |
| `ENABLE_INTERNET_TEST` | `true` | 是否启用外网 Speedtest |
| `ENABLE_LAN_TEST` | `true` | 是否启用内网 `iperf3` |
| `ENABLE_HEARTBEAT_TEST` | `true` | 是否启用轻量心跳探测 |
| `HEARTBEAT_INTERVAL_SECONDS` | `60` | 心跳采样间隔，单位秒 |
| `HEARTBEAT_TARGET` | `223.5.5.5` | 主心跳目标 |
| `HEARTBEAT_TARGETS` | `223.5.5.5,114.114.114.114,1.1.1.1` | 多目标心跳地址列表 |
| `HEARTBEAT_TIMEOUT_SECONDS` | `2` | 单次 `ping` 超时秒数 |
| `INTERNET_SPEEDTEST_SERVER_ID` | 空 | 指定单一测速节点 |
| `INTERNET_SERVER_POOL` | `3633,5396,30852,59386` | 固定测速节点池，失败时会自动回退到自动选点 |
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

## 内网测速

如果你需要内网吞吐测试，先在局域网内另一台设备上启动：

```bash
iperf3 -s
```

然后把 `LAN_IPERF_HOST` 改成这台设备的局域网 IP，并确保：

- 设备长期在线
- 尽量是有线连接
- NAS 到这台设备网络路径稳定

## 数据存储

默认 SQLite 文件位于：

```text
/data/speed_history.db
```

在 `docker-compose.yml` 中默认映射为：

```yaml
volumes:
  - ./data:/data
```

所以容器升级或重建后，历史数据会保留。

## 已实现的接口

- `GET /`：Web 看板
- `GET /health`：健康检查
- `GET /api/history`：历史记录
- `GET /api/internet/summary`：外网测速汇总
- `GET /api/heartbeat/summary`：主目标心跳汇总
- `GET /api/heartbeat/targets`：心跳目标列表
- `GET /api/heartbeat/dashboard`：聚合后的心跳视图
- `POST /api/run`：手动触发正式测速
- `POST /api/admin/cleanup-legacy`：清理旧版低质量样本
- `GET /api/export.csv`：导出 CSV

## 部署建议

### 群晖 / 威联通

- 映射端口 `8080`
- 映射数据卷到 `/data`
- 用环境变量控制测速行为
- 如果 NAS 走代理构建镜像，运行容器时不建议再继承代理变量

### 极空间

这一版对极空间部署更友好，建议优先用“创建项目”或“导入 Compose”方式部署：

- 端口直接映射 `8080:8080`
- 数据目录映射到 NAS 本地持久化目录
- 如只关注外网稳定性，可先关闭 `ENABLE_LAN_TEST`
- 默认心跳和 Speedtest 配置已经能直接用于极空间的日常外网监控

### 上海电信场景

当前默认优选节点池偏向上海电信和周边：

- `3633` `China Telecom / Shanghai`
- `5396` `China Telecom JiangSu 5G / Suzhou`
- `30852` `Duke Kunshan University / Kunshan`
- `59386` `浙江电信 / HangZhou`

如需更换节点，可直接修改 `INTERNET_SERVER_POOL`。

## 已知限制

- `114.114.114.114` 在部分网络环境下可能会被限制 ICMP 或出现偶发失败
- Speedtest 结果会受运营商策略、节点负载、出口路由影响
- 当前 Web 图表是前端 SVG 绘制，适合监控和分析，不是报表系统

## 后续可以继续做的方向

- 多目标同图对比
- 告警推送到 Telegram / 企业微信 / 邮件
- 日报导出
- 更细的事件分类
- 独立的公网 IP 变更追踪
