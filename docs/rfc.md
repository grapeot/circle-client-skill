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

### V1 新增：member session 的 base_url 推导

帖子、聊天和图片 endpoint 都挂在同一个 community host 下。为避免硬编码 host，`CircleSettings` 增加 `base_url` property，从 `notifications_url` 推导 `{scheme}://{netloc}`。所有新 API 方法通过 `self.settings.base_url` 构建 URL。

## Internal API 逆向

V1 的帖子、聊天和图片能力来自浏览器 ajax 逆向，不是官方文档。通过 Playwright CDP 拦截 fetch 请求获取 endpoint、method、payload schema 和 auth header。所有 endpoint 已用 plain `requests` + cookie + CSRF 验证通过。

### 已验证的 endpoint contract

| 操作 | Method | Endpoint | Body | Auth |
|---|---|---|---|---|
| 列 space | GET | `/internal_api/spaces` | — | cookie |
| 列帖子 | GET | `/internal_api/spaces/{id}/posts` | — | cookie |
| 获取单帖 | GET | `/internal_api/spaces/{id}/posts/{slug}` | — | cookie |
| 创建帖子 | POST | `/internal_api/spaces/{id}/posts` | `{"post":{name, space_id, status, user_id, tiptap_body, topics, slug, ...}}` | cookie+CSRF |
| 更新帖子 | PATCH | `/internal_api/spaces/{id}/posts/{slug}` | `{"post":{id, name, slug, space_id, ...}}` | cookie+CSRF |
| 删除帖子 | DELETE | `/internal_api/spaces/{id}/posts/{slug}` | — | cookie+CSRF |
| 帖子权限 | GET | `/internal_api/post_details?post_ids=&space_id=` | — | cookie |
| 列评论 | GET | `/internal_api/posts/{id}/comments` | — | cookie |
| 回复帖子 | POST | `/internal_api/posts/{id}/comments` | `{"comment":{body, tiptap_body, [parent_comment_id]}}` | cookie+CSRF |
| 上传图片 | POST | `/internal_api/direct_uploads` | `{"blob":{filename, byte_size, checksum, content_type, metadata}}` | cookie+CSRF |
| 图片上传第二步 | PUT | `<direct_upload.url>` (S3) | raw file bytes | direct_upload headers |
| 列聊天消息 | GET | `/internal_api/chat_rooms/{uuid}/messages` | — | cookie |
| 发聊天消息 | POST | `/internal_api/chat_rooms/{uuid}/messages` | `{"chat_room_message":{chat_room_participant_id, rich_text_body, [parent_message_id], unfurl_urls}}`。`rich_text_body` 可含服务端签发的 mention 节点 | cookie+CSRF |
| 编辑聊天消息 | PATCH | `/internal_api/chat_rooms/{uuid}/messages/{id}` | `{"chat_room_message":{rich_text_body, attachments}}`。无 participant id | cookie+CSRF |
| 搜索 mention | GET | `/users/mentions.json?query=&per_page=` | —。响应是 JSON 数组，不是 `/internal_api/` envelope | cookie |
| 读取 thread 回复 | GET | `/internal_api/chat_rooms/{uuid}/messages?parent_message_id={id}` | — | cookie |
| room 参与者 | GET | `/internal_api/chat_rooms/{uuid}/participants?page=` | —（records 含 id/name/community_member_id） | cookie |
| 加反应（chat 消息） | POST | `/internal_api/reactions` | `{"unicode":"2764-fe0f","chat_room_message":<id>}`；响应含 `{"success","message","reaction"}`，消息记录自带 `reactions` 数组可回读 | cookie+CSRF（2026-10-15 live 验证） |
| 评论 like/love/… | POST | `/user_likes` | `{"user_likeable_type":"Comment","user_likeable_id":<id>,"reaction_type":"like|celebrate|love|support|insightful|funny"}`；重复同 payload 在网页 UI 是 toggle 语义；comment 记录的 `reaction_summary`/`is_liked` 可回读 | cookie+CSRF（2026-10-15 live 验证） |

### 鉴权机制

GET 请求只需 `Cookie` header（浏览器 session cookie，含 HttpOnly 的 `remember_user_token` 和 `_circle_session`）。Mutation（POST/PATCH/DELETE）还需要 `X-CSRF-Token` header，值来自名为 `csrf_token` 的 cookie。Bearer JWT 在 `.env` 里保留，但实测 GET 不带 JWT 也能 200——JWT 是冗余的，保留作为 fallback。

### 图片上传的两步流程

与 circle_post 的 Admin API 路径一致，但 endpoint 不同：
- circle_post (Admin): `POST /direct_uploads`（base URL 是 `app.circle.so`）
- circle_client (member): `POST /internal_api/direct_uploads`（base URL 是 community host）

两者返回相同的 ActiveStorage blob 结构，含 `signed_id` 和 `direct_upload: {url, headers}`。第二步 PUT raw bytes 到 S3 的方式完全一致。

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
# V0 — notifications
circle-client configure --from-clipboard
circle-client configure --stdin
circle-client auth-status
circle-client count
circle-client reset-count
circle-client reset-count --execute --confirm RESET-COUNT
circle-client fetch --group inbox --per-page 100 --output data/notifications.json
circle-client open-notifications --input data/notifications.json --category lesson_comments
circle-client open-notifications --input data/notifications.json --category lesson_comments --execute --confirm OPEN-NOTIFICATIONS
circle-client react --message-id <id> (--emoji heart|thumb_up|star | --unicode <hex-code>) --execute --confirm REACT   # dry-run 默认
circle-client dashboard [--port 8780] [--no-open] [--directory data]    # 127.0.0.1，人用的交互面

# V1 — spaces, posts, comments, images, chat (all read ops are live, all mutations are dry-run-first)
circle-client spaces
circle-client get-space -s <space_id>
circle-client list-posts -s <space_id> [--page N] [--per-page N]
circle-client create-post -s <space_id> --name "Title" --user-id <id> --execute --confirm CREATE-POST
circle-client update-post -s <space_id> --post-id <id> --slug <slug> --name "New Title" --user-id <id> --execute --confirm UPDATE-POST
circle-client delete-post -s <space_id> --slug <slug> --execute --confirm DELETE-POST
circle-client reply-post --post-id <id> --text "Reply text" --execute --confirm REPLY-POST
circle-client upload-image -f <path> --execute --confirm UPLOAD-IMAGE
circle-client chat-send (--room-uuid <uuid> | --space-id <id>) --participant-id <id> --text "Hello" [--parent-message-id <id>] --execute --confirm CHAT-SEND
circle-client list-chat-messages (--room-uuid <uuid> | --space-id <id>) [--cursor <message_id>] [--direction previous|next]
circle-client list-chat-replies (--room-uuid <uuid> | --space-id <id>) --parent-message-id <id> [--cursor <message_id>] [--direction previous|next]
circle-client unreplied (--room-uuid <uuid> | --space-id <id>) --member-id <id> [--limit N]

# Global flag — applies to all subcommands
circle-client <command> [...] --json   # output complete raw JSON instead of compact text
```

### 输出格式原则

默认输出是紧凑纯文本（对齐表格或结构化卡片），面向 AI agent 和人类终端用户同时优化：字段稳定可 grep，行式或表格式可正则解析，不输出 `success`/`count`/`page` 等信封元字段（除非它本身是业务内容，如 `count` 的数字）。

`--json` 是全局 flag，挂在主 parser 上、所有子命令继承。它输出**完整原始 API 响应**，不做字段裁剪，供下游 pipeline 无损消费。默认模式和 JSON 模式职责清晰分离：前者精简，后者完整。

具体格式由 `formatters.py` 承载，每种命令一个格式器。列表类输出为对齐表格（非 Markdown，避免 `|` 管道符噪声），单条详情为 key-value 卡片，mutation dry-run 为结构化 preflight 块，mutation live 为一行确认，错误为人类可读单行 + status/request_id。`get-post` 默认从 tiptap body 提取纯文本，`--raw-body` 保留原始 tiptap JSON 块。通知可视化统一走 `dashboard`；静态 `render` 与 `serve` 命令已于 0.2.0 移除（fetch 的 JSON artifact 仍是规范存储）。

## 本地批量打开通知

`open-notifications` 把"在浏览器里逐条打开未读通知"这段本地动作收编成命令，避免每次临时写脚本。它读已有 fetch artifact，按 category 过滤、按 `source.host` 校验 URL、按 URL 去重、按时间排序，然后逐条交给操作系统 opener（macOS `open` / Linux `xdg-open`），间隔默认 3 秒。

放在 CLI 而不是 HTML 页面按钮里的原因：页面 JS 用 `window.open` 连续打开多个标签，浏览器弹窗拦截器只放行用户点击那一下同步打开的窗口，后续调用被静默拦截；OS opener 由系统派发给浏览器，不受该限制。

安全与语义边界：

- 纯本地、只读、不联网、不加载 `.env`、不改变任何 Circle 状态。打开通知不等于标记已读，两者不隐式耦合。
- URL 必须是 `http(s)` 且落在 artifact 的 `source.host` 上，否则跳过并在计划里报告；相对路径按该 host 补全。
- opener 以参数列表调用（`[opener, "-g"?, url]`），不经过 shell。
- 默认 dry-run（只打印计划行），live 需要 `--execute --confirm OPEN-NOTIFICATIONS`，与其它命令的 confirm-token 契约一致。
- `--category`（lesson_comments/comments/likes/members/other/all）、`--interval`、`--order`、`--dedupe/--no-dedupe`、`-g/--background`、`--opener` 均可调。纯逻辑在 `opener.py`（`plan_targets` / `open_sequentially`），可离线单测。

## Mutation Boundary

`reset-count` 与未来的 `mark-all-read` 必须是两个不同命令，因为清零 badge count 与把通知全部标记为已读不是同一语义。Circle 当前 reset-count 的内部路径虽然叫 `mark_all_as_read`，实测行为仍按 reset count 建模。

`reset-count` 默认只输出 POST target、CSRF/cookie presence 等脱敏 preflight。Live POST 必须同时提供 `--execute --confirm RESET-COUNT`，不自动重试。`mark-all-read` 尚未实现。

### V1 mutation 边界

所有 V1 mutation（create-post、update-post、delete-post、reply-post、upload-image、chat-send）遵循同一 dry-run-first 契约：

- 不带 `--execute` 时只打印 preflight（操作类型、目标 ID、关键参数、CSRF/cookie presence），不加载 `.env` 的 mutation 字段，不碰网络。
- `--execute` 必须同时提供 `--confirm <ACTION-NAME>`，且用户当次明确授权。
- 每种 mutation 的 confirm token 不同（CREATE-POST、UPDATE-POST、DELETE-POST、REPLY-POST、UPLOAD-IMAGE、CHAT-SEND），防止误用。
- 错误信息透传 HTTP status code 和 response body 片段（最多 500 字符），不封装。

### V1 已知限制

- `create-post` 和 `update-post` 的 `user_id` 参数需要调用者提供。这是 Circle internal API 的要求——前端从 localStorage 读取当前 user id 并放进 body。未来可以从 `.env` 或 auth-status 自动推导。

### Chat 分页

Circle chat 不用 page+per_page 分页，而是用 cursor-based pagination：
- `previous_per_page`：向过去方向拉取的消息数
- `next_per_page`：向未来方向拉取的消息数
- `id`：数字 message ID 游标。向历史翻页使用响应的 `first_id`，向未来翻页使用 `last_id`

历史方向请求使用 `id=<first_id>&previous_per_page=50&next_per_page=0`；未来方向请求使用 `id=<last_id>&previous_per_page=0&next_per_page=50`。服务端会在相邻页重复 cursor anchor，完整扫描必须按数字 message ID 去重，并在结束时用 `total_count` 校验唯一记录数。`before_creation_uuid` 已实测为无效参数，不属于当前 contract。

Thread 回复用同一个 messages endpoint，通过 `parent_message_id` query param 过滤。发 thread reply 时在 POST body 的 `chat_room_message.parent_message_id` 字段带上 parent 消息的数字 ID。

Thread reply 的 POST 返回 `{creation_uuid, sent_at, parent_message_id}`——注意没有 `id` 字段，只有 `creation_uuid`。如果需要获取新消息的 ID，需要通过 `fetch_chat_replies` 再次查询。

### chat room UUID 解析

`/internal_api/spaces` 列表端点只返回数字 `chat_room_id`，不含 UUID。`/internal_api/spaces/{id}` 单个 space detail 返回 `chat_room_uuid`。所有 chat 命令支持 `--space-id` 便捷参数：提供时自动调 `get_space` 解析 UUID，免去手动查 UUID。`--room-uuid` 和 `--space-id` 二选一；已知 UUID 时直接用 `--room-uuid` 避免额外 API 调用。

### unreplied 判定

`thread_participants_preview` 字段在 root 消息里直接含完整参与者列表，每个 participant 有 `community_member_id` 和 `name`。`community_member_id` 跨所有 room 一致（每用户一个），`chat_room_participant_id` 则每 room 不同。判定目标成员是否参与某条 root 消息的 thread：检查 `thread_participants_preview` 里有没有目标 `community_member_id`。即便 `replies_count > 0`（别人回了但目标成员没回），也算 unreplied。`--member-id` 为必填参数，不设默认值（public-ready repo 不含真实用户身份）。`scan_chat_roots` 辅助方法处理完整分页遍历：cursor anchor overlap 去重、cursor 前进检查、`max_pages` 上限和 `total_count` 一致性验证。

## Dashboard V2（one-stop 交互面）

完整设计见 `docs/design_dashboard.md`。要点：

- `circle-client dashboard` 在 127.0.0.1:8780 起 `_DashboardHTTPServer`：`GET /` 返回单页 UI（`dashboard_ui.py` 内嵌模板，无外部资源）；`GET /api/state` 重新 fetch 未读 + 分组 + enrichment（per-context 缓存 + ThreadPool，评论走 `list_comments` 分页、lesson 讨论走 `list-chat-messages` + replies、参与者名字走 participants endpoint）；`POST /api/react` 与 `POST /api/mark_read` 是唯一两条 mutation 路径。
- 页面动作与 Circle 状态的映射：react = 反应 + 该通知 mark_as_read（「拉倒」语义）；mark_read 单条；点赞折叠组的「全部已读」由 UI 逐条循环单条请求，server 不批量。
- 安全模型：只绑回环地址、校验 Origin、JSON Content-Type 必填；每次点击 = 用户本人的一次明确授权动作（对应「人亲手点 Publish」的本地 UI 延伸）；CLI 的 `react` 命令单独保留 dry-run-first 契约给 agent 路径。
- Reaction 双契约并存：chat 消息用 unicode `/internal_api/reactions`；post 评论用 named 类型的 `/user_likes`。target 类型由 `VERIFIED_REACTION_KINDS` 门控，未经 live round-trip 验证的类型不显示反应按钮。
- **反应作用域**：未读目标行（带 notification 挂钩）= 反应 + 自动 mark_as_read；线程里的任意非未读行也显示反应按钮（react-only，notification_id 为空，server 校验该行存在于当前页面上下文，不标已读）。
- **反应确认不做乐观绘制**：react 成功后失效该 context 的缓存（context 带 `context_id`，按 target kind 映射回缓存 key），前端 400ms 防抖刷新；页面上看到的反应数/反应列表一律来自刷新后的真实回读数据。
- Emoji 集：内置 `reactions.REACTION_EMOTES`（chat 消息，unicode 契约）；`data/emotes.json`（gitignored，`{"名字": "unicode码"}`）可增量扩展，无效条目跳过并在 state 里带 warning，文件坏则回退内置集合。post 评论只有 Circle 固定的六种 named 类型，不受该配置影响。
- **排序规则**：讨论区 context 按 lesson 讨论 room → 帖子评论 → 其他链接卡分层（同层内按 targets 最新 created_at 倒序，Python stable sort 两步实现）；点赞组按最新活动倒序。
- **Room 窗口不是全集**：messages endpoint 默认只回最近的 roots（实测某 room 只有 21 条），老 thread 的新 reply 会落在窗口外；enrichment 在目标缺失时按 cursor 向后翻页（`previous_per_page=200`，上限 12 页，无新 id 即停）再扫全部已知 root 的 replies。彻底缺失的目标渲染成提示行 + 打开链接，不给任何反应/已读动作。
- **线程组织**：rows 带 `parent_id`/`reply_to`/`depth`。room 按 thread root 时间序、root 先于 replies；帖子评论按 root 时间 + DFS。**卡片只渲染目标所在的 thread**（用户只 care 未读消息，无关 root 不渲染）；bare root 带 `hidden_replies` 提示。老 thread 用通知 URL 的 `#message_<root>` 锚点直达（对根直接 fetch replies，一次请求），backward walk（有界）只是无锚点时的兜底。作者名 best effort（participants 前 3 页 + 通知 actor；课程 room 名单 2400+ 不可全量）。
- 实测预算：首刷 51 个 context ~35s（含评论分页与 participants 名字分页），缓存命中后增量刷新秒级。
- 「全部已读」（点赞折叠组）在 UI 里做二次确认（6 秒内再点一次才执行），执行时由前端逐条调 mark_read（250ms 间隔），server 端保持"单请求单动作"。
