---
name: circle-client
description: >-
  Fetches a signed-in Circle member's notifications through Circle's web internal API,
  using a locally imported browser Copy as cURL request, and renders lossless JSON as
  Markdown or CSV. Use for Circle unread notifications, notification export, or local
  AI-assisted notification triage. This is not Circle Admin API or Circle MCP.
---

# Circle Client Skill

## 目标

把当前登录成员在 Circle 网页中可见的未读通知完整抓取到本地 artifact，并渲染成适合阅读或 AI 后处理的 Markdown/CSV/HTML。已读通知不进入 artifact。当前稳定能力严格只读。

## 何时使用

- 用户要看、导出、汇总或筛选自己的 Circle notifications。
- 用户没有或不想使用 Admin API、Headless API、Circle MCP。
- 用户提供了浏览器 notification request 的 Copy as cURL，或已把它放进剪贴板。

发布或更新 Circle 帖子应使用独立的 Circle Post Skill，不要用本 skill。

## 可用命令

从项目根目录运行：

```bash
.venv/bin/circle-client configure --from-clipboard
.venv/bin/circle-client auth-status
.venv/bin/circle-client count
.venv/bin/circle-client reset-count
.venv/bin/circle-client fetch --group inbox --per-page 100 --output data/notifications.json
.venv/bin/circle-client render --input data/notifications.json --format md --output data/notifications.md
.venv/bin/circle-client render --input data/notifications.json --format csv --output data/notifications.csv
.venv/bin/circle-client render --input data/notifications.json --format html --output data/index.html
.venv/bin/circle-client serve --directory data --host 0.0.0.0 --port 8765
```

`fetch` 默认在连续 100 条已读记录后停止。用户明确要求完整历史审计时才使用 `--stop-after-consecutive-read 0`。

## 安全边界

- 不要求用户把完整 cURL 粘贴进聊天。优先让用户 Copy 后只说“已复制”，再由 CLI 从 clipboard 读取。
- 不打印、总结或写入 tracked 文件中的 JWT、Cookie、CSRF token 或原始 cURL。
- `.env` 和 `data/` 都是本地私密状态，不能提交。
- `fetch` 和 `count` 是 GET。
- `reset-count` 默认 dry-run；live 执行必须同时使用 `--execute --confirm RESET-COUNT`，并获得用户对当次动作的明确授权。
- `reset-count` 与 mark-all-read 是不同 mutation。当前没有 mark-all-read 能力，不得根据内部 endpoint 名字猜测或代替实现。

## 输出与 AI Filter

Fetch JSON 是 source of truth，保留 Circle 返回的完整 notification object。Markdown/CSV 只是阅读视图。用户要求按作者、时间、类型、关键词或重要性筛选时，Agent 可以现场读取 JSON 并编写一次性分析代码；不要为了单次筛选扩张 CLI contract。

## 验收标准

- `auth-status` 只显示 host、credential presence 和 JWT expiration，不泄露凭证。
- `fetch` 遍历全部页面，输出 JSON count 与数组长度一致。
- `render` 输出文件行数/条目数与 fetch artifact 一致。
- 认证失败时，指导用户从一个当前成功的 notification Fetch/XHR 重新 Copy as cURL。
- 所有 live artifact 留在 gitignored `data/`。
