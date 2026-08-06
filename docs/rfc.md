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
| 发聊天消息 | POST | `/internal_api/chat_rooms/{uuid}/messages` | `{"chat_room_message":{chat_room_participant_id, rich_text_body, [parent_message_id], unfurl_urls}}` | cookie+CSRF |

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
circle-client render --input data/notifications.json --format md
circle-client render --input data/notifications.json --format csv
circle-client render --input data/notifications.json --format html --output data/index.html
circle-client serve --directory data --host 0.0.0.0 --port 8765

# V1 — spaces, posts, comments, images, chat (all read ops are live, all mutations are dry-run-first)
circle-client spaces
circle-client list-posts -s <space_id> [--page N] [--per-page N]
circle-client create-post -s <space_id> --name "Title" --user-id <id> --execute --confirm CREATE-POST
circle-client update-post -s <space_id> --post-id <id> --slug <slug> --name "New Title" --user-id <id> --execute --confirm UPDATE-POST
circle-client delete-post -s <space_id> --slug <slug> --execute --confirm DELETE-POST
circle-client reply-post --post-id <id> --text "Reply text" --execute --confirm REPLY-POST
circle-client upload-image -f <path> --execute --confirm UPLOAD-IMAGE
circle-client chat-send --room-uuid <uuid> --participant-id <id> --text "Hello" [--parent-message-id <id>] --execute --confirm CHAT-SEND
circle-client list-chat-messages --room-uuid <uuid> [--page N] [--per-page N]
```

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

- `chat-send` 的 `parent_message_id` 参数当前标记为待验证。实测发送后返回的 `chat_thread_id` 等于 parent message id，但消息是否真正进入 thread 视图还是变成独立消息，需要浏览器端验证。当前实现照常提交 `parent_message_id`，不阻塞 V1 发布。
- `create-post` 和 `update-post` 的 `user_id` 参数需要调用者提供。这是 Circle internal API 的要求——前端从 localStorage 读取当前 user id 并放进 body。未来可以从 `.env` 或 auth-status 自动推导。
