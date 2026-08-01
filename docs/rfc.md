# Circle Client Skill RFC

## 架构结论

项目采用独立 repo 和独立认证模型，不并入 `circle-post-skill`。Circle Post 使用长期 Admin API token 并执行内容 mutation；本项目使用短期 member browser session，默认严格只读。两者只共享 Circle 品牌，不共享安全边界或 API contract。

## 数据流

```text
Browser Network request
  -> Copy as cURL
  -> local parser (never executes shell)
  -> gitignored .env
  -> read-only paginated GET
  -> lossless JSON artifact
  -> Markdown / CSV derived artifact
  -> optional ad-hoc AI filtering
```

## 认证导入

Importer 接受 clipboard、stdin 或本地文件。它只允许 HTTPS，并要求 URL path 精确匹配 `/internal_api/notifications`。当前保留以下字段：

- Notifications URL
- Bearer Authorization
- Cookie（若存在）
- User-Agent（Cloudflare clearance 可能与它绑定）
- Referer
- X-Circle-Frontend-Version

Importer 不保存完整 cURL，不执行其中任何内容，也不输出凭证。`.env` 权限固定为 `0600`。JWT payload 只用于本地显示 `exp`，不把 decode 当成签名验证。

Circle 支持 custom community domain，因此不能靠 `circle.so` host allowlist 判断合法 community。当前安全约束改为 HTTPS、固定 endpoint path，以及 URL/Referer same-origin。

## 分页

客户端覆盖原始请求中的 `notification_group`、`page` 和 `per_page`，并优先沿用响应的 `next_search_after` cursor。优先读取响应的 `has_next_page`、`has_more`、pagination/meta page 信息；都不存在时才用返回数量是否达到 `per_page` 推断。

Fetch 会扫描服务端分页，但只保留 `read_at = null` 的记录。`new_notifications_count` 是 Circle badge 的新通知计数，不代表全部未读数量，不能拿它作为 fetch 的分页终止条件。

通知按时间倒序返回。默认把连续 100 条已读视为实际 unread frontier 并停止；任何未读记录都会把连续已读 streak 清零。调用者可用 `--stop-after-consecutive-read 0` 禁用该启发式并扫描完整历史。

为防 internal API 异常导致死循环，客户端同时设置 `max_pages` 和整页 fingerprint 去重。

## Artifact Contract

Fetch JSON 顶层结构：

```json
{
  "schema_version": 1,
  "fetched_at": "2026-01-01T00:00:00+00:00",
  "source": {
    "host": "community.example.com",
    "notification_group": "inbox",
    "per_page": 100,
    "pages_fetched": 2
  },
  "count": 123,
  "notifications": []
}
```

`notifications` 保留服务端原始对象，不在 fetch 阶段做有损 normalization。Markdown/CSV 是派生视图，可以随着真实 schema 调整。

## CLI Contract

```bash
circle-client configure --from-clipboard
circle-client configure --stdin
circle-client auth-status
circle-client count
circle-client reset-count
circle-client reset-count --execute --confirm RESET-COUNT
circle-client fetch --group inbox --per-page 100 --output data/notifications.json
circle-client render --input data/notifications.json --format md
circle-client render --input data/notifications.json --format csv
circle-client render --input data/notifications.json --format html --output data/index.html
circle-client serve --directory data --host 0.0.0.0 --port 8765
```

## Mutation Boundary

`reset-count` 与未来的 `mark-all-read` 必须是两个不同命令，因为清零 badge count 与把通知全部标记为已读不是同一语义。Circle 当前 reset-count 的内部路径虽然叫 `mark_all_as_read`，实测行为仍按 reset count 建模。

`reset-count` 默认只输出 POST target、CSRF/cookie presence 等脱敏 preflight。Live POST 必须同时提供 `--execute --confirm RESET-COUNT`，不自动重试。`mark-all-read` 尚未实现。
