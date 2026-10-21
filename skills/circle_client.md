---
name: circle-client
description: >-
  Fetches a signed-in Circle member's notifications through Circle's web internal API
  and triages them in a local one-stop dashboard. Primary use case:
  viewing / visualizing / triaging your Circle notifications locally. Use when a user
  asks to see, review, visualize, export, or summarize their Circle notifications.
  Also routes post writes (new post, edit post, event recording posts): those go through
  a human-visible browser where the agent fills the composer and a human clicks Publish.
  Paywall creation, trial extension, and billing-date changes are not CLI commands;
  route them to references/paywall_subscriptions.md.
---

# Circle Client Skill

## 目标

把当前登录成员在 Circle 网页中可见的未读通知完整抓取到本地 JSON artifact（规范存储），并在 one-stop dashboard 里浏览、反应与标已读。已读通知不进入 artifact。当前稳定能力严格只读。

**浏览器默认可见。** 浏览器驱动的观察和交互默认走人类可见的 Chrome：用 `open-browser` 打开窗口，再连接它输出的 CDP。不要启动 headless，除非用户明确要求，或当前环境没有 GUI。

## 何时使用

- 用户要看、导出、汇总或筛选自己的 Circle notifications。
- 用户没有或不想使用 Admin API、Headless API、Circle MCP。
- 用户提供了浏览器 notification request 的 Copy as cURL，或已把它放进剪贴板。
- 用户要发帖、改帖，或把一场活动整理成回放帖：走下文「写帖子：可见浏览器」，不走 CLI。
- 用户要建测试 paywall、延长 trial 或改 billing date：没有对应 CLI。走「Paywall 与个人 trial 改期」。

## 看通知 / 通知可视化（首要工作流）

当用户说"看通知 / 我的通知 / notifications / 可视化通知 / 通知 dashboard / 通知面板 / 最近有什么通知 / check my notifications / show notifications / visualize my notifications"等任一表达时，默认走 `dashboard`，这是本 skill 的首要工作流，不要另写可视化脚本：

```bash
.venv/bin/circle-client dashboard            # 127.0.0.1:8780，自动开浏览器；Ctrl-C 停
```

`dashboard` 把未读按「要回应的讨论 / 点赞 / 其他」三区组织，是"可视化通知"的标准答案。静态 HTML 视图（`render --format html`）已于 0.2.0 移除，不要再写回。只有当用户明确要求聚合统计（类型分布、时间轴、TOP 互动者等）且 dashboard 不满足时，才在 fetch JSON 上写一次性分析代码，不要为单次需求扩张 CLI contract。

# Dashboard（one-stop 通知台，人用的交互面）

当用户想"一条龙处理通知"（看完内容、点头像级反应、标已读，不逐条点开 Circle 网页）时，用 dashboard：

```bash
.venv/bin/circle-client dashboard            # 127.0.0.1:8780，自动开浏览器；Ctrl-C 停
```

页面把未读按三个区组织：要回应的讨论（帖子评论按 post 聚合、lesson 评论按 room 聚合，线程按时间正序、新消息高亮、带上下文）、点赞（折叠成「N 人赞了《X》」行）、其他（成员/审核/live 链接）。每条新消息的动作条：反应（❤️/👍 或 comment 的 like/love/celebrate…）+ ✓已读 + 打开原页。反应成功会自动把该通知标已读（一次点击拉倒），行不会立刻消失：反应经定向回读（`/api/verify`，只重新拉该 context 确认 reaction 真的落地）后原地更新为 done 样式（半透明 + 「✓ 处理过」），点「刷新」才从列表移除。线程里的非未读行也能直接加反应（不标已读），浏览旧内容时不用离开页面。
加新 emoji（chat/lesson 消息）：在 gitignored `data/emotes.json` 加 `{"名字": "unicode码"}`（如 `{"clap": "1f44f"}`），刷新页面即生效；post 评论的反应类型是 Circle 固定的六种 named 类型，不可扩展。

工作机制与边界：

- 服务端每次刷新重新 fetch 未读并做 enrichment（评论/消息正文走 `list_comments` / `list-chat-messages`），带 per-context 缓存和线程池；全部是只读 GET，首刷约几十秒，之后增量秒级。state 落 gitignored `data/dashboard.json`，动作追加入 `data/dashboard_log.jsonl`。
- 反应按 target 类型分两套已验证契约：chat 消息 `POST /internal_api/reactions` body `{"unicode","chat_room_message"}`；post 评论 `POST /user_likes` body `{"user_likeable_type":"Comment","user_likeable_id","reaction_type"}`（named 类型 like/love/celebrate/support/insightful/funny，同一 payload 再发一次是在网页 UI 里 toggle 的语义；本工具只加不减，误点去网页手动取消）。未验证的 target 类型在代码里由 `VERIFIED_REACTION_KINDS` 门控，页面不显示反应按钮。
- 服务只绑 127.0.0.1，校验 Origin；页面动作的每次点击 = 用户本人的一次明确授权（对应"人亲手点 Publish"）；server 不自动、不批量。CLI 的 `react` 命令仍走 dry-run + `--execute --confirm REACT`（agent 路径）。
- 对真实读者的回复不在页面里做：反应/已读之外需要回复时点「打开」去 Circle 网页（可见浏览器原则不变）。
- 设计文档：`docs/design_dashboard.md`。

## 批量打开通知（在浏览器里逐条打开）

当用户说"把所有 lesson comment / lesson notification / 这些通知都打开"这类表达时，用 `open-notifications`：读已有的 fetch artifact，按类筛出通知，去重后逐条交给操作系统打开（macOS `open` / Linux `xdg-open`），每条之间 sleep。它不联网、不需要凭证，且**默认 dry-run**——先打印计划，加 `--execute --confirm OPEN-NOTIFICATIONS` 才真正打开：

```bash
# 1) 先看计划（dry-run，默认）
.venv/bin/circle-client open-notifications --input data/notifications.json --category lesson_comments
# 2) 核对条数无误后再执行
.venv/bin/circle-client open-notifications --input data/notifications.json --category lesson_comments --interval 3 --execute --confirm OPEN-NOTIFICATIONS
```

为什么是 CLI 而不是 HTML 按钮：页面 JS 用 `window.open` 连开多个标签会被弹窗拦截器挡下（只有用户点击那一下同步打开的窗口才被允许），而 OS opener 由系统派发给浏览器，不受此限制。

- `--category`：`lesson_comments` / `comments` / `likes` / `members` / `other` / `all`（复用 normalize 的分类逻辑）。
- `--interval`：每条间隔秒数（默认 3）。
- `--order`：`newest`（默认）/ `oldest`。
- `--dedupe` / `--no-dedupe`：是否按完整 URL 去重（默认去重；同一消息的 `course_comment` 和 `comment_mention` 会折叠成一条）。
- `-g` / `--background`：标签进后台，不抢焦点。
- `--opener`：覆盖自动探测的 opener。
- URL 必须是 http(s) 且落在 artifact 的 `source.host` 上，其它一律跳过并在计划里报告，防止被篡改的 artifact 让本机打开任意地址。

## 配置

凭证过期时（`auth-status` 显示失效、或 API 返回 401），用以下方式刷新：

### 方式一：configure-browser（推荐）

```bash
.venv/bin/circle-client configure-browser --url https://your-community.circle.so
```

打开一个可见浏览器窗口，登录后自动提取 cookie + CSRF + community_id，写入 `.env`。不需要 DevTools，不需要 Copy as cURL。

需要 Playwright：`uv pip install -e '.[browser]'` + `python -m playwright install chromium`

### 方式二：configure（从 Copy as cURL，备选）

浏览器 DevTools → Network 找到一个 `/internal_api/` 请求，右键 Copy as cURL，然后：

```bash
.venv/bin/circle-client configure --from-clipboard
```

**不要让用户把 cookie 或 cURL 粘贴到聊天里。** 用户 Copy 后说"已复制"，CLI 从剪贴板读取。

### 验证

```bash
.venv/bin/circle-client auth-status
.venv/bin/circle-client count  # 快速验证凭证是否有效
```

## 获取最新内容（跨 space 类型）

需要"某 space 最近 N 条内容"时，先用 `get-space` 判断 `type`，再分发到对应命令；两者默认都按时间倒序返回（newest first），调用方不需要先知道 space 类型：

1. `.venv/bin/circle-client get-space -s <space_id>` 看 `type` 字段。
2. `basic` / `course` / `event` → `list-posts -s <space_id> --per-page N`（置顶帖钉顶，其余按 `published_at` 倒序）。
3. `chat` → `list-chat-messages --space-id <space_id> --direction previous --previous-per-page N`（room 级 feed，已按 `created_at` 倒序）。

course space 的 lesson 正文和 lesson 讨论不在 post 列表里，也不走 `reply-post`。要看课程内容或 lesson 评论，用下方「课程内容与 lesson comments」。

要拿单条全文：post 用 `get-post --slug`；chat message 当前没有单独 fetch 命令，表格预览只截前 80 字符，需要全文时加 `--json` 取 `records[].body`。

要拿每篇 post 的回复数：`list-posts --with-counts`（对每个 post 多发一次 `list_comments per_page=1` 取 `count`，N+1 请求，按需开启）。**post 级别的 likes 数无法通过 member-session API 获取**——Circle 的 post-list 和 post-detail endpoint 都不返回 `likes_count`，也不存在 `/likes` endpoint；只有 comment 对象带 `likes_count`。

## 排序与分页契约

- **page 内排序**：`list-posts`、`list-chat-messages`、`lesson-comments` 的根消息默认 newest-first；`list-chat-replies` 和 `lesson-comments` 拉到的 thread 回复保持 ascending（thread 自上而下阅读）。
- **cursor 翻页**：`list-chat-messages` 和 `lesson-comments` 的 `--direction next/previous` 描述的是"取更新/更老的页"，page 内 ordering 固定，两者不耦合。pagination 元数据（`first_id`/`last_id`/`has_*`）始终对应 Circle API 返回的 ascending 原页，用于推导下一页 cursor。

## 可用命令

从项目根目录运行：

```bash
# 通知（V0）
.venv/bin/circle-client configure --from-clipboard
.venv/bin/circle-client open-browser --path /c/example-space   # 可见 Chrome + 注入会话，本身不写 Circle
.venv/bin/circle-client auth-status
.venv/bin/circle-client count
.venv/bin/circle-client reset-count
.venv/bin/circle-client mark-notification-read <notification_id>
.venv/bin/circle-client react --message-id <id> --emoji heart [--execute --confirm REACT]
.venv/bin/circle-client open-notifications --input data/notifications.json --category lesson_comments
.venv/bin/circle-client open-notifications --input data/notifications.json --category lesson_comments --execute --confirm OPEN-NOTIFICATIONS
.venv/bin/circle-client dashboard [--port 8780] [--no-open]

# 帖子、空间、评论、图片、聊天（V1）
.venv/bin/circle-client spaces
.venv/bin/circle-client list-posts -s <space_id> [--page N] [--per-page N] [--full] [--with-counts]
.venv/bin/circle-client get-post -s <space_id> --slug <slug> [--extract-text]
.venv/bin/circle-client create-post -s <space_id> --name "Title" --user-id <id> --dry-run
.venv/bin/circle-client create-post -s <space_id> --name "Title" --user-id <id> --execute --confirm CREATE-POST
.venv/bin/circle-client update-post -s <space_id> --post-id <id> --slug <slug> --name "New" --user-id <id> --execute --confirm UPDATE-POST
.venv/bin/circle-client delete-post -s <space_id> --slug <slug> --execute --confirm DELETE-POST
.venv/bin/circle-client reply-post --post-id <id> --text "Reply" --execute --confirm REPLY-POST
.venv/bin/circle-client upload-image -f <path> --execute --confirm UPLOAD-IMAGE
.venv/bin/circle-client search-mentions --query member --per-page 20
.venv/bin/circle-client mention-sgids --room-uuid 00000000-0000-0000-0000-000000000000
.venv/bin/circle-client mention-sgids -s 9000000 --section-id 9000001 --lesson-id 9000002
.venv/bin/circle-client chat-send --room-uuid 00000000-0000-0000-0000-000000000000 --participant-id 9000010 --text "Hello" --mention-sgid FAKE-SGID-0001 --parent-message-id 9000003 --execute --confirm CHAT-SEND
.venv/bin/circle-client chat-send -s 9000000 --section-id 9000001 --lesson-id 9000002 --participant-id 9000010 --text "Hello" --parent-message-id 9000003
.venv/bin/circle-client update-chat-message --room-uuid 00000000-0000-0000-0000-000000000000 --message-id 9000001 --text "Hello" --mention-sgid FAKE-SGID-0001
.venv/bin/circle-client update-chat-message --room-uuid 00000000-0000-0000-0000-000000000000 --message-id 9000001 --text "Hello" --execute --confirm UPDATE-CHAT-MESSAGE
.venv/bin/circle-client list-chat-messages --space-id <id> --direction previous --previous-per-page N   # 默认 newest-first
.venv/bin/circle-client list-chat-replies --room-uuid <uuid> --parent-message-id <id>                      # thread 保持 ascending
.venv/bin/circle-client list-chat-messages --room-uuid <uuid> --direction previous --previous-per-page 50 # 发送后回读用

# 课程内容与 lesson 讨论（只读）
.venv/bin/circle-client course-lessons -s <space_id>
.venv/bin/circle-client course-lesson -s <space_id> --section-id <id> --lesson-id <id>
.venv/bin/circle-client lesson-comments -s 9000000 --section-id 9000001 --lesson-id 9000002
.venv/bin/circle-client lesson-comments -s 9000000 --section-id 9000001 --lesson-id 9000002 --focus 9000003
.venv/bin/circle-client lesson-comments -s 9000000 --section-id 9000001 --lesson-id 9000002 --focus 9000004

# 课程管理：section、Draft lesson、lesson 编辑器（写操作默认 dry-run；浏览器命令连 open-browser 开的 Chrome）
.venv/bin/circle-client course-sections -s 9000000                                      # 含 Draft 和空 section（只读）
.venv/bin/circle-client create-section -s 9000000 --name "Bonus Module" --execute --confirm CREATE-SECTION
.venv/bin/circle-client rename-section -s 9000000 --section-id 9000001 --name "..." --execute --confirm RENAME-SECTION
.venv/bin/circle-client create-lesson -s 9000000 --section-id 9000001 --manifest lessons/01.json --execute --confirm CREATE-LESSON
.venv/bin/circle-client fill-lesson -s 9000000 --lesson-id 9000002 --manifest lessons/01.json [--thumbnail cover.png] --cdp http://127.0.0.1:9333 --execute --confirm FILL-LESSON
.venv/bin/circle-client lesson-featured-video -s 9000000 --lesson-id 9000002 --video intro.mp4 --execute --confirm LESSON-FEATURED-VIDEO
.venv/bin/circle-client lesson-media-settings -s 9000000 --lesson-id 9000002 --vtt subs.vtt --chapters chapters.txt --video-thumbnail cover.png --execute --confirm LESSON-MEDIA-SETTINGS
```

`fetch` 默认在连续 100 条已读记录后停止。用户明确要求完整历史审计时才使用 `--stop-after-consecutive-read 0`。

所有 mutation 命令（create-post、update-post、delete-post、reply-post、upload-image、chat-send、update-chat-message、reset-count、mark-notification-read，以及课程管理的 create-section、rename-section、create-lesson、fill-lesson、lesson-featured-video、lesson-media-settings）默认 dry-run。只给 `--room-uuid` 时 preflight 不发请求；用 `--space-id` 或 lesson id 解析 room 时会先发只读 GET。Live 执行需同时提供 `--execute --confirm <ACTION>`，且用户当次明确授权。

## 课程内容与 lesson comments

course 类 space 的 lesson 内容是正文加媒体，不是 post。lesson 讨论也不是 post comment，而是挂在该 lesson 上的 chat room。三个命令都是只读 GET，按这个顺序用：

1. `course-lessons -s <space_id>` 从 space 的 `course_sections` 取出 section id 和 lesson id。`course_sections` 缺失、为 null 或为空时命令会失败，说明这不是 course space。
2. `course-lesson -s <space_id> --section-id <id> --lesson-id <id>` 拿正文、附件文件名和 `chat_room_uuid`。lesson endpoint 必须走带 section 的路径；不带 section 的 variant 会 404。
3. `lesson-comments` 用同一组 id 读讨论。根消息 newest-first，pagination 元数据保留 ascending 原页。对 `replies_count > 0` 的根消息一律再拉一页回复，N+1 是固有成本，没有开关。`--json` 输出 `roots` 和 `threads`（key 是字符串形式的根消息 id），不用 `records`，也没有 `with_threads` 字段。
   `--focus <message-id>` 在 window 截断之后只留包含该消息的线程：root id 命中则留该 root 及其 replies；未命中则在已抓 replies 里找，命中则留其 root 和全部 replies。都不中，或不在本次 window 里，会报未找到。
   注意：lesson 讨论 room 里服务端会忽略 per-page 参数、一次返回全部根消息，所以命令在输出层按 `--previous-per-page`（默认 20）截断到最新 N 条；要看更多把 per-page 调大。

要在 lesson 讨论里发或改消息，room 不用手填 uuid：`chat-send` / `update-chat-message` 接受 `-s <space_id> --section-id <id> --lesson-id <id>`，内部读 lesson 的 `chat_room_uuid`。发送仍然要 `--participant-id`（**该 room 自己的 id，见「回复与发送」一节**）；编辑不传 participant id。对真实读者的回复优先走可见浏览器（[`references/reply_in_browser.md`](references/reply_in_browser.md)），CLI live 发送后必须回读核验。

从 `course_comment` 通知进去可以跳过前两步。通知 JSON 的 `action_inbox_path` 形如 `/settings/inbox/course-comments/<room-uuid>`，把末段 uuid 交给 `list-chat-messages --room-uuid <uuid>`。`action_web_url` 里的 `#message_<id>` 是根消息 id，要看 thread 时传给 `list-chat-replies --parent-message-id <id>`。

## 编辑消息与 mention

mention 的 sgid 是服务端签名的，不能自己拼。知道名字时先 `search-mentions --query <name>`，从表格或 `--json` 数组里取 `sgid`。不知道确切名字、但讨论里已经 @ 过对方时，用 `mention-sgids` 从当前 room window 聚合被 mention 过的人。一条消息只带被 mention 者的 sgid，不含作者本人的 sgid；要 @ 作者，得从别的消息或 `search-mentions` 拿。

表格预览会把 mention 显示成 `@Name`。`circle_ios_fallback_text` 会压平段落并丢掉 mention，不要用它当消息正文。

```bash
.venv/bin/circle-client mention-sgids --room-uuid 00000000-0000-0000-0000-000000000000
.venv/bin/circle-client chat-send --room-uuid 00000000-0000-0000-0000-000000000000 --participant-id 9000010 --text "Hello" --mention-sgid FAKE-SGID-0001 --parent-message-id 9000003 --execute --confirm CHAT-SEND
```

会把当前 window 里 `replies_count > 0` 的根消息的一页回复也算进去。当前 window 没有 mention 时，改用 `search-mentions --query <name>`。

拿到 sgid 后传给 `chat-send --mention-sgid` 或 `update-chat-message --mention-sgid`（可重复）。只在 `--text` 模式有效；`--tiptap-file` / `--tiptap-json` 是把整个 `rich_text_body` 透传，这时再带 `--mention-sgid` 会直接报错。

`update-chat-message` 默认 dry-run。live 编辑：

```bash
.venv/bin/circle-client update-chat-message --room-uuid 00000000-0000-0000-0000-000000000000 --message-id 9000001 --text "updated" --execute --confirm UPDATE-CHAT-MESSAGE
```

## 安全边界

- 不要求用户把完整 cURL 粘贴进聊天。优先让用户 Copy 后只说“已复制”，再由 CLI 从 clipboard 读取。
- 不打印、总结或写入 tracked 文件中的 JWT、Cookie、CSRF token 或原始 cURL。
- `.env` 和 `data/` 都是本地私密状态，不能提交。
- `fetch` 和 `count` 是 GET。
- `course-lessons`、`course-lesson`、`course-sections`、`lesson-comments`、`search-mentions`、`mention-sgids` 都是只读 GET。
- 课程管理的写命令默认 dry-run（dry-run 不连浏览器、不上传）；live 需要 `--execute --confirm <ACTION>` 和用户当次授权。浏览器命令只编辑 Draft lesson，`--allow-published` 需要用户对这次修改单独授权。
- `update-chat-message` 默认 dry-run；live 执行必须同时使用 `--execute --confirm UPDATE-CHAT-MESSAGE`，并获得用户对当次动作的明确授权。
- `reset-count` 默认 dry-run；live 执行必须同时使用 `--execute --confirm RESET-COUNT`，并获得用户对当次动作的明确授权。
- `mark-notification-read <id>` 把单条通知标记已读（`PATCH /internal_api/notifications/<id>/mark_as_read`，cookie+CSRF，200/204 均视为成功）；默认 dry-run，live 必须 `--execute --confirm MARK-NOTIFICATION-READ` 且当次授权。已读是服务端状态：`read_at` 落库后该通知从 unread fetch 中消失、`count` 下降；只读 comment 页面不会写 `read_at`，只有 inbox 里点开通知或本命令才会。
- `react` 给 chat room 消息加 emoji 反应（`POST /internal_api/reactions`，body `{"unicode": <code>, "chat_room_message": <id>}`）；默认 dry-run，live 必须 `--execute --confirm REACT` 且当次授权。post 评论类反应（named like 类型，`POST /user_likes`）目前只在 dashboard 的页面动作里提供，CLI 暂不暴露。本工具只加反应、不 un-react；取消去 Circle 网页手动操作。
- `dashboard` 起的本地服务只绑 127.0.0.1、校验 Origin；页面动作（react/mark_read）的每次点击是用户本人的一次明确授权动作，server 不自动批处理。全部动作追加审计日志（gitignored）。`/api/verify` 是只读回读端点（反应后重拉单 context 确认落地），不产生 mutation、不进审计日志；失败响应是固定错误消息（不透传上游响应内容）。
- `reset-count` 与 mark-all-read 是不同 mutation。当前没有 mark-all-read 能力（`mark-notification-read` 是单条，不是 mark-all），不得根据内部 endpoint 名字猜测或代替实现。
- `open-browser` 只启动可见 Chrome、注入 cookie、打开一个社区页面后断开，不发任何 mutation；输出里没有 cookie 值。端口已被占用或 profile 已被锁住时拒绝启动，绝不附着到已有浏览器。目标 URL 必须是社区 host 上的 HTTPS 地址。
- `open-notifications` 是本地只读动作：只读 fetch artifact、只调本地 URL opener，不联网、不动 Circle 状态，也不隐式标记已读。默认 dry-run，live 需要 `--execute --confirm OPEN-NOTIFICATIONS`；只打开落在 artifact `source.host` 上的 http(s) URL。
- 帖子的写操作（发帖、编辑帖子）走可见浏览器，不走 `create-post` / `update-post`；Publish 和 Save draft 都不由 agent 点。

## 回复与发送：可见浏览器优先，CLI 必须回读

**原则：对真实读者可见的回复（lesson 讨论回复、给成员回帖、chat room 发言）先 `open-browser` 打开目标页面**，用户在可见窗口里能当场看到发没发出去、能点进去核对；这个窗口同时是回读和兜底路径。CLI 的 `chat-send` 保留给 test space 和脚本化场景。

- 只要用 CLI live 发送，发送后**必须回读核验**：`list-chat-replies --room-uuid <uuid> --parent-message-id <root-id>` 或 `list-chat-messages` 里出现新 message id 才算成功。**HTTP 202 / `creation_uuid` / "OK: sent" 都不是送达证据。**
- `chat_room_participant_id` 是 **per-room** 值，不是账号常量；同一个账号在不同 room 里的 id 不同。用 CLI 发送前先从目标 room 的 `GET /internal_api/chat_rooms/<uuid>/participants` 里按 `community_member_id` 认领自己；填错时 Circle 仍返回 202 但消息被静默丢弃。不要把这个值写进脚本或公开文件。
- 完整操作路径（点根消息展开 thread → 在 `[contenteditable=true]` 的 tiptap 编辑器输入 → `@` 触发 mention 选人 → 点 `aria-label="Send message"` → 回读新消息 id）见 [`references/reply_in_browser.md`](references/reply_in_browser.md)。
- 发送是对外可见动作，需要用户当次明确授权；授权前可以开好浏览器、填好草稿、截图给用户看。

## 写帖子：可见浏览器（发帖、编辑帖子、活动回放帖）

**原则：发帖、编辑帖子不走 CLI。** 用 `open-browser` 开一个人类可见的 Chrome（独立 profile 和调试端口，不是 headless），注入已保存的会话；agent 通过 CDP 把标题、封面、正文、图片、视频填进编辑器，核对后停在编辑器里。**不点 Publish，也不点 Save draft**，由人继续修改并亲手发布；Topic 默认留给人选，用户要求时可以代选（没选 Topic 时 Publish 是灰的）。`create-post` / `update-post` 作为底层能力保留，不用来发给真实读者看的帖子。

- 往真实 space 填编辑器同样需要用户在主会话里明确授权（上传封面和视频会在服务端建 blob）。
- 不连接人正在用的浏览器。交付后不再对那个窗口跑任何脚本，不关、不刷新。
- `open-browser` 输出 `cdp_endpoint`，后续脚本用 `chromium.connect_over_cdp(cdp_endpoint)` 连接，退出时只断开，不调用 `browser.close()`。

```bash
.venv/bin/circle-client open-browser --path /c/example-recordings --port 9333 --profile-dir data/visible_browser/profile
```

编辑器的通用操作见 [`references/browser_post_composer.md`](references/browser_post_composer.md)，要点：

- 打开 Create post 后先点 **Full screen** 展开，否则工具栏、图片气泡菜单和下拉列表容易被遮挡。
- 正文插图走 Add image 打开的 "Attach image" 对话框（设文件后点 Save），不会弹系统文件选择框；每次上传前后对比 `editor.getJSON()`，记下新增节点的 `signed_id`。
- 横图满宽；手机截图等竖图设成半宽（image 节点 `width_ratio: 0.5, alignment: "left"`，等同于点图片后气泡菜单的第一个选项）。
- 先把所有图片和视频各上传一次，再用 `setContent('')` + `insertContentAt` 把正文和媒体节点交替重建，不靠粘贴。
- 发帖编辑器里没有字幕入口；字幕只能发布后在 Customize media 里加，视频已烧录字幕时不要再加软字幕。

帖子发布后给视频补字幕和章节（帖子页视频右上角 Customize media 对话框）是对已发布帖子的修改：要用户对这一次修改明确授权，agent 点 Save 后立刻用 `video.textTracks` 回读。英文讲座不要用 Circle 的自动转写，上传自制的中英双语 .vtt；时间轴映射、按比例切分、双语组装和校验用离线模块 `circle_client_skill.subtitles`。

活动回放帖特有的流程（从空间归纳惯例、帖子结构与标题模板 `<活动标题>｜<系列名>回放`、录像里他人发言的处理与时间戳平移、起草 → 事实核对 → voice rewrite → surgical fix、发布后的双语字幕与章节、相关的坑）见 [`references/recording_posts.md`](references/recording_posts.md)；它的编辑器部分同样引用上面的通用文档。

## 课程 lesson（批量搬教材）

**原则：新建的 section 和 lesson 一律是 Draft；浏览器命令发现 lesson 已发布就拒绝（除非 `--allow-published` 且用户对这次修改明确授权）；Publish 由人点。**

分工：**机械步骤用 CLI，判断留给 agent。** 建 section / lesson、按清单填正文、上传 featured 视频、字幕、章节、缩略图都是命令，命令内部处理了踩过的坑（保存前等表单同步、首尾空段落、悬停才出现的按钮、对话框内 seek、等新视频处理到能 seek、删章节的二次确认、缩略图裁剪对话框），并在保存后回读核对。agent 要做的是：先读几个现有 lesson 归纳这门课的写法（标题、多语言排法、视频 lesson 模板），再把教材转成 **lesson 清单**（`{"title", "items": [{"html"} | {"media", "kind": "image"|"video", "portrait"}]}`；表格、行内代码、公式要在这一步转换掉，编辑器没有这些节点），然后按顺序跑命令。

```bash
.venv/bin/circle-client open-browser --path /c/example-course --port 9333 --profile-dir data/visible_browser/profile
.venv/bin/circle-client course-sections -s 9000000
.venv/bin/circle-client create-lesson -s 9000000 --section-id 9000001 --manifest out/01.json --execute --confirm CREATE-LESSON
.venv/bin/circle-client fill-lesson -s 9000000 --lesson-id 9000002 --manifest out/01.json --execute --confirm FILL-LESSON
```

`lesson-media-settings` 要等 featured 视频处理完再跑；它中途失败时什么都没存（封面、字幕也一样），整步重跑。lesson 的 Publish 流程里没有通知学员的选项，不要让人在发布时决定通知。

完整流程、清单格式、章节文件格式、每个命令背后的接口和坑、交付前核对清单见 [`references/course_lessons.md`](references/course_lessons.md)。

## 活动（event）

**原则：本 skill 里与活动相关的脚本只用于 probe（观察表单、默认值、回读状态）。活动的写操作（创建、编辑、发布）走浏览器 UI，由人操作或由用户明确授权的浏览器 session 操作，不通过 CLI/API 命令。Publish 永远由人亲手点。** 通知类命令照旧走 CLI。往真实社区 space 写数据需要用户在主会话里明确授权；转述给 sub-agent 的授权可能被 agent 权限系统拦下，先在 test space 里试。

CLI 没有 `create-event` / `publish-event` 一类命令，也不要为单次需求临时写一个。几个最容易踩的事实：Save 只建草稿（`status` 写死 `"draft"`）；发布邮件、确认邮件、提醒邮件的开关只在草稿编辑页里，默认全开；发布邮件只在 Publish 那一刻发，之后无法重发；secret test space 里有非 admin 成员时，Publish 一样会发通知；表单时间按成员资料时区解释。

完整的字段、tab、通知默认值、副作用和 endpoint 见 [`references/events.md`](references/events.md)。

## Post moderation（管理员会话）

`get-flagged-content` 只读待审正文；`approve-post` / `reject-post` 默认离线 dry-run，live 需明确授权、`--execute` 与匹配的 `--confirm APPROVE-POST` / `REJECT-POST`。必须提供预期 `--post-id` 和 `--space-id`，仅支持 Post。先 GET 核对目标，再 PATCH，最后回读 approved/rejected；同动作顺序重复只读后跳过，不保证并发 exactly-once。完整参数与失败恢复见 [`references/post_moderation.md`](references/post_moderation.md)。

## Paywall 与个人 trial 改期

本仓库没有 `paywall-*` 或 billing 命令。成员 cookie 和 CSRF 也不是 Admin API token。隔离测试 paywall、正常 checkout、延长 genuine trial、取消后归档，走人类可见浏览器，可选再调用官方 Admin API v2。已验证和仅文档的分界、以及不能照抄的请求模板，见 [`references/paywall_subscriptions.md`](references/paywall_subscriptions.md)。这份手册不授权新的 live 写操作；每次写入仍要当次明确授权。

## Probe 工具（默认可见窗口）

CLI 没覆盖的页面（活动表单、新面板）先用 probe 工具看，不要猜 endpoint。`circle_client_skill.probe` 只做四件事：观察、截图、抓请求、回读状态。需要 `browser` extra（`uv pip install -e '.[browser]'` + `python -m playwright install chromium`）。

`ProbeSession` 必须默认使用可见窗口（`headless=False`）。`headless=True` 只是 opt-in：用户明确要求 headless，或当前环境没有 GUI 时才传。`python -m circle_client_skill.probe` 不带 headless 参数，走同一个可见默认。

```bash
# 只读示例：打开可见窗口、截图、导出可见表单控件和脱敏后的 internal_api 请求日志
.venv/bin/python -m circle_client_skill.probe --path /c/example-space --out data/probe --tag example
```

```python
from pathlib import Path
from circle_client_skill.probe import ProbeSession

with ProbeSession(env_path=Path(".env"), headless=False) as probe:   # 默认就是可见窗口；headless=True 仅在用户明确要求或无 GUI 时使用
    probe.page.goto(probe.url("/c/example-space"), wait_until="domcontentloaded")
    probe.screenshot(Path("data/probe/example.png"))
probe.capture.dump(Path("data/probe"), "example")      # 写盘前已脱敏
print(probe.guard.blocked)                             # 被拦下的写请求（已去 query）
```

- `ProbeSession` 从现有 `.env` 读 cookie 注入 Chromium，默认 `headless=False`（可见窗口）。不打印凭证；page/context/browser/Playwright 在 `finally` 里逐个关闭，一步失败不影响后面几步。service worker 被禁用，避免绕过路由拦截。
- `RouteGuard` 装在整个 browser context 上：发往 community host 的非 GET/HEAD/OPTIONS 请求一律 abort 并记进 `guard.blocked`；其他 host（CDN、分析、S3 直传）不管。默认放行列表为空。注意打开页面本身就会触发写请求（`reset_unread_count`、analytics、Cloudflare beacon 等），在 `blocked` 里看到它们是正常的。
- `RequestCapture` 只记 `/internal_api/` 的 XHR/fetch。`dump()` 写盘前做两层脱敏：Cookie/Authorization/CSRF 等字段名、URL 里的签名参数，以及 `.env` 里实际的 cookie/CSRF/JWT 值，无论出现在哪里都替换成 `[REDACTED]`。响应正文里仍可能有成员姓名等私人数据，所以输出只放 gitignored 的 `data/`。
- **放宽白名单**：只有当人已经授权一次具体的浏览器写操作时，才给 `ProbeSession(allow=...)` 传规则，而且只放那一个 endpoint，例如 `allow=("POST /internal_api/spaces/1111/events",)`。规则格式是 `"[METHOD] /path"`，path 按 fnmatch 匹配、忽略 query，`*` 可跨 `/`；不写 method 表示任意非 GET 方法。不要放 `/internal_api/*` 这种大范围规则。上传封面这类连带请求要逐个列出（例如 `"POST /internal_api/direct_uploads"`）。
- 活动的写操作和 Publish 仍按上面的原则走浏览器 UI；probe 工具没有任何活动写命令。

## 输出与 AI Filter

Fetch JSON 是 source of truth，保留 Circle 返回的完整 notification object。用户要求按作者、时间、类型、关键词或重要性筛选时，Agent 可以现场读取 JSON 并编写一次性分析代码；不要为了单次筛选扩张 CLI contract。

## 验收标准

- `auth-status` 只显示 host、credential presence 和 JWT expiration，不泄露凭证。
- `fetch` 遍历全部页面，输出 JSON count 与数组长度一致。
- 认证失败时，指导用户从一个当前成功的 notification Fetch/XHR 重新 Copy as cURL。
- 所有 live artifact 留在 gitignored `data/`。
