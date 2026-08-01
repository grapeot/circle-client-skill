# Circle Client Skill

Circle Client Skill 是一个非官方、local-first 的 Circle 成员客户端。它从浏览器中已经成功的通知请求导入临时登录凭证，分页抓取个人未读通知，并将结果渲染为便于阅读和后续 AI 筛选的 Markdown、CSV 或响应式 HTML。

当前版本只提供只读通知能力，不需要 Circle Admin API 或 Headless API。

## 安装

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e '.[dev]'
```

## 配置

在浏览器 DevTools 的 Network 面板中打开 Circle 通知页，找到返回通知 JSON 的请求，右击该请求并选择 **Copy as cURL**。然后让 CLI 直接读取剪贴板：

```bash
circle-client configure --from-clipboard
```

也可以通过标准输入导入：

```bash
circle-client configure --stdin
```

完整 cURL 含有可复用的登录凭证。不要把它粘贴到聊天、issue、日志或 tracked 文件中。CLI 只保存后续请求需要的字段到本地 `.env`，不会保存原始 cURL。

## 使用

抓取 Inbox 中全部通知，默认每页请求 100 条：

```bash
circle-client fetch --group inbox --per-page 100 --output data/notifications.json
circle-client count
```

清除 Circle 的 new-notification badge count：

```bash
# 默认只输出 preflight，不发送 POST
circle-client reset-count

# 只有明确决定清零时才执行
circle-client reset-count --execute --confirm RESET-COUNT
```

Circle 内部 endpoint 名为 `mark_all_as_read`，但实测产品语义是重置 badge/new count，不会在本工具中表述成“全部通知已读”。

`fetch` 默认在连续遇到 100 条已读记录后停止，把它视为实际 unread frontier。若需要审计完整历史，可传 `--stop-after-consecutive-read 0`。

渲染为 Markdown 或 CSV：

```bash
circle-client render --input data/notifications.json --format md --output data/notifications.md
circle-client render --input data/notifications.json --format csv --output data/notifications.csv
circle-client render --input data/notifications.json --format html --output data/index.html
circle-client serve --directory data --host 0.0.0.0 --port 8765
```

检查本地凭证状态：

```bash
circle-client auth-status
```

## Agent Skill

Canonical skill 位于 `skills/circle_client.md`。可以把本仓库 URL 交给 Codex、Claude Code、Cursor、OpenCode 或其他 coding agent，让它先读取目标 workspace 的 `AGENTS.md` / `CLAUDE.md` 和路由文件，再把 canonical skill 加入当地的 skill discovery chain。

## 稳定性说明

本工具调用 Circle 网页使用的 internal API，而不是 Circle 官方公开 API。Circle 可能调整 endpoint、字段或认证方式；浏览器 JWT、cookies 和 Cloudflare clearance 也会过期。认证失效时，重新从正常工作的浏览器请求执行 Copy as cURL 并再次运行 `configure`。
