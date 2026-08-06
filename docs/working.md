# Working

## Changelog

### 2026-08-06

- 通过 Playwright CDP 拦截 Circle 前端 fetch 调用，逆向出 posts/spaces/comments/chat/image upload 的 internal API endpoint。
- 所有 endpoint 已用 plain `requests` + cookie + CSRF 验证通过（test posts space + test chat room）。
- 新增 `CircleSettings.base_url` property，从 notifications_url 推导 community host。
- 新增 `CircleClient._request` 通用 HTTP 方法，支持 GET/POST/PATCH/DELETE，透传 status code 和 response body 片段到错误信息。
- 新增 10 个 client 方法：list_spaces, get_space, list_space_topics, list_posts, get_post, create_post, update_post, delete_post, get_post_details, list_comments, create_comment, upload_image, list_chat_messages, send_chat_message。
- 新增 10 个 CLI 子命令：spaces, list-posts, create-post, update-post, delete-post, reply-post, upload-image, chat-send, list-chat-messages。所有 mutation 默认 dry-run，live 执行需 `--execute --confirm <ACTION>`。
- 新增 `tests/test_posts_chat.py` 覆盖所有新 endpoint 的 method、URL、payload schema 和错误处理。
- 更新 PRD（V1 目标）、RFC（endpoint contract 表、base_url 推导、V1 mutation 边界、已知限制）。

### 2026-07-31

- 建立 public-ready Python/uv 项目骨架、中文文档和 canonical skill。
- 定义 browser cURL -> local `.env` -> paginated JSON -> Markdown/CSV 的只读工作流。
- 实现 cURL 安全解析、凭证状态、通知分页抓取和 Markdown/CSV 渲染。
- 为当时尚无请求证据的 count 与 reset 动作保留独立边界，随后按真实请求逐项实现。
- 根据真实 browser request 增加 `new_notifications_count` 只读 GET。
- 增加 lesson comment 高亮、comment 展开、likes/member joins 折叠的响应式 HTML 页面和本地 server。
- Live schema 显示 inbox 包含已读与未读混合记录；fetch 改为只持久化 `read_at = null`，并使用 `next_search_after` cursor。
- 验证服务端接受 `per_page=100` 和 `per_page=500`；live 全量抓取可用 500 降低请求数。
- 确认 `new_notifications_count` 是 badge/new count，不等同于全部 unread 数量。
- 全历史有约 2.8 万条记录；根据实际阅读模式增加“连续 100 条已读即停止”的 unread frontier，避免无价值的数百页扫描。
- HTML 在当前页面内记录已点击链接并改变卡片背景；不使用 browser storage，刷新或关闭页面后状态自动清空。
- 根据真实请求实现 dry-run-first `reset-count`；Circle endpoint 虽名为 `mark_all_as_read`，产品语义按实测的 badge count reset 建模。
- 用户授权的 live reset-count 先通过 dry-run，再执行 POST 并返回 HTTP 200；执行前后 badge count 均为 0，验证幂等路径且未改变通知 artifact。

## Lessons Learned

- Circle Admin API token 与 member browser JWT 是两套不同身份模型，不应放进同一个 skill。
- `reset notification count` 与 `mark all notifications read` 语义不同，后续必须保持为两个独立动作。
- Browser cURL 含完整 session credential；让 CLI 直接读 clipboard 比粘贴进 AI 对话更安全。
- Circle internal API 的 endpoint 在 `/internal_api/` 前缀下，不是 Admin API 的根路径。例如图片上传：Admin API 是 `POST /direct_uploads`（host: app.circle.so），member API 是 `POST /internal_api/direct_uploads`（host: community domain）。两者返回格式一致但路径不同。
- `document.cookie` 拿不到 HttpOnly cookie（`remember_user_token`、`_circle_session`）；需要用 Playwright CDP `context.cookies()` 导出完整 cookie header。
- SSO 登录的 Circle 社区直接拼深链 URL 会被 referer 校验拦截（"We were unable to process your request"）；必须从 feed/首页点击导航进目标 space。
- 页面 reload 会重置 `window.__captured`；fetch monkey-patch 拦截器在 SPA 内部导航时存活，但在全页刷新时丢失。Update post 的 Save 触发了页面刷新，需要改用 CDP `page.on("request"/"response")` 持久监听。
- Chat thread reply 的 `parent_message_id` 在 API 层面返回 202 且 `chat_thread_id` 等于 parent id，但浏览器端消息可能不进入 thread 视图而是变成独立消息。需要后续浏览器验证。
- `csrf_token` cookie 可能在页面 reload 后变化；`.env` 里的 CSRF 值需要定期更新。
