# Bark Gateway Guide

通用的 Bark 网关接入说明，适合 NAS、Docker 常驻服务和脚本类任务复用。

这份文档使用脱敏示例，不依赖任何特定域名、特定 token 或私有设备 key。

## 推荐架构

建议统一走一层中转网关，而不是让每个项目都直接请求 Bark 服务端：

```text
NAS / 脚本 / Docker 服务
    -> Bark Gateway
    -> Bark Server
    -> Bark App
```

这样做的好处：

- 统一鉴权入口，项目侧不直接暴露 `device_key`
- 统一消息格式，标题和正文风格更整齐
- 后续可以统一切换 Bark 服务端、增加降噪或转发逻辑

## 环境变量

项目侧推荐使用下面这组变量：

```text
ENABLE_BARK_NOTIFICATIONS=true
BARK_WEBHOOK_URL=https://your-gateway.example.com/icloud
BARK_WEBHOOK_TOKEN=replace-with-your-token
BARK_SOURCE_NAME=NAS 外网监测
```

也可以直接写成完整路径：

```text
BARK_WEBHOOK_URL=https://your-gateway.example.com/icloud/replace-with-your-token
```

如果你的网关不是 `/icloud/<token>` 这种形式，也可以使用：

```text
BARK_WEBHOOK_URL=https://your-gateway.example.com/api/webhook
BARK_WEBHOOK_TOKEN=replace-with-your-token
```

或者：

```text
BARK_WEBHOOK_URL=https://your-gateway.example.com/api/webhook/replace-with-your-token
```

## 最小协议

请求方式：

```text
POST
Content-Type: application/json
```

请求体最小只需要一个字段：

```json
{"data":"来源 - 事件 - 详情"}
```

推荐格式：

```text
项目名 - 事件名 - 细节
```

示例：

```text
NAS 外网监测 - 国内链路异常 - 223.5.5.5 连续失败 2 次
NAS 外网监测 - 国际链路转好 - 1.1.1.1 最近 30 分钟成功率 100%
NAS 外网监测 - 网络日报 - 24h 连通率 99.82%
```

## 网关行为建议

中转网关建议至少做 3 件事：

1. 校验 token
2. 接收统一 JSON 结构
3. 转发到 Bark Server 并返回结果

如果需要更完整一点，可以额外做：

- 标题格式化
- 不同项目的分类字段
- 简单去重
- 失败重试
- 同时转发到其他渠道

## curl 示例

```bash
curl -sS -X POST "https://your-gateway.example.com/icloud/replace-with-your-token" \
  -H 'content-type: application/json' \
  --data '{"data":"NAS 外网监测 - 测试通知 - Bark 网关配置成功"}'
```

## Python 示例

```python
import json
import subprocess

payload = json.dumps({
    "data": "NAS 外网监测 - 测试通知 - Bark 网关配置成功"
}, ensure_ascii=False)

subprocess.run(
    [
        "curl",
        "-sS",
        "-X",
        "POST",
        "https://your-gateway.example.com/icloud/replace-with-your-token",
        "-H",
        "content-type: application/json",
        "--data",
        payload,
    ],
    check=True,
)
```

## Docker Compose 示例

```yaml
environment:
  ENABLE_BARK_NOTIFICATIONS: "true"
  BARK_WEBHOOK_URL: "https://your-gateway.example.com/icloud"
  BARK_WEBHOOK_TOKEN: "replace-with-your-token"
  BARK_SOURCE_NAME: "NAS 外网监测"
```

## 排查建议

如果项目侧发不出 Bark，可以按这个顺序查：

1. 网关地址能不能直接访问 `/health`
2. NAS 或容器能不能访问网关域名
3. token 是否匹配
4. 网关后面指向的 Bark Server 是否可达
5. Bark App 当前是否连接到了正确的 Bark Server

## 适合 NAS 的接法

对 NAS 项目，推荐：

- 所有通知都走统一 Bark Gateway
- 项目只保留网关 URL 和 token
- 把通知标题前缀固定成项目名
- 告警尽量做去重和恢复通知，避免高频打扰

这也是本项目当前使用的推荐接法。
