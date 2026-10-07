# Working

## Changelog

### 2026-10-07 Recording subtitles and chapters

- `skills/references/recording_posts.md` 新增第六节「视频字幕与章节」：帖子发布后，在帖子页视频右上角的 Customize media 对话框里上传自制字幕（Enable transcription → Upload a custom transcript → `input[name="transcript.user_webvtt_file"]`）、加章节（pause + 设 `currentTime` 后点 "Add at MM:SS"，`input[name=title]` 填标题回车），Save 后用 `video.textTracks` 回读 captions/chapters 轨的 cue 数、seek 抽查 `activeCues`、截图看双行渲染和进度条分段。坑表补了自动转写语言识别错、`[role=dialog]` 误匹配 media-error-dialog、视频在 shadow DOM、窗口全关后会话丢失等。
- 执行原则：Customize media 的 Save 是对已发布帖子的写操作，要用户对这一次修改明确授权，Save 后立刻回读。写进 root skill 和 AGENTS.md。
- 新增 `src/circle_client_skill/subtitles.py`（纯离线、不联网、不加 CLI 命令）：`parse_vtt`（可拆 Zoom 的 `Name: ` 前缀）、`remap_cues`（剪掉区间内的 cue 丢弃、之后前移、截断点之后丢弃、末条夹到视频时长）、`split_times` / `build_bilingual_vtt`（按英文长度比例在原 cue 时间内分配子段、相邻 cue 留 0.05 s 不重叠、中上英下两行）、`validate_vtt`（单调、正时长、无重叠、cue 数、残留错误拼写）。翻译和 ASR 纠错由 agent 做，不在代码里。
- 新增 `tests/test_subtitles.py`（离线，合成 fixture）。本地用一次真实录像的数据核对过：映射结果和组装出的 .vtt 与当时手写脚本的产物逐字节一致；真实数据不在仓库里。

### 2026-10-07 Recording posts and visible-browser writes

- 新增 `skills/references/recording_posts.md`：活动回放帖的完整工作流。包括怎样从回放空间统计惯例（置顶说明帖、最近十几帖逐项计数）、帖子结构（中文第一人称整理文、标题 `<活动标题>｜<系列名>回放` 且系列名不写死、原生视频、`MM:SS｜标题` 观看导航、资源链接、评论邀请、不放优惠码、2.8:1 封面）、录像里他人发言的确认与剪辑及时间戳平移、起草 → 事实核对 → voice rewrite → surgical fix，以及可见浏览器填写编辑器的流程、核对清单和坑。
- 确立执行原则并写进 root skill：发帖、编辑帖子不走 CLI。开人类可见的浏览器，agent 填好标题、封面、正文、视频后停在编辑器里，不点 Publish、不点 Save draft，由人修改并亲手发布。`create-post` / `update-post` 保留为底层能力。
- 新命令 `open-browser`（`src/circle_client_skill/visible_browser.py`）：以独立 `--user-data-dir` 和 `--remote-debugging-port` 启动 detached 的可见 Chrome，等 `/json/version` 就绪后 `connect_over_cdp`，注入 `.env` 的 cookie，打开一个社区页面，然后只断开 CDP、不关浏览器。端口已有监听（只做 TCP connect 探测，不发数据）或 profile 有 `Singleton*` 锁时拒绝启动，绝不附着到已有浏览器；目标 URL 必须是社区 host 上的 HTTPS 地址；输出只有 endpoint、端口、profile、URL、pid 和 cookie 条数。命令本身不发 mutation。
- 新增 `tests/test_visible_browser.py`（离线，fake Playwright、fake Popen）：启动参数、cookie 注入、只断开不关闭、导航失败也 stop、占用端口/锁住的 profile 在启动前拒绝、URL host/scheme 校验、Chrome 查找顺序、CDP 轮询的重试/进程退出/超时、CLI 输出和错误不含凭证。
- 没有 live 跑 `open-browser`：实际流程用的是同一套手法的临时脚本（gitignored `data/`）。

### 2026-10-03 Probe tooling

- 新增 `src/circle_client_skill/probe/`：`ProbeSession`（从 `.env` 注入 cookie 的 headless Chromium，禁用 service worker，`finally` 里逐个关闭 page/context/browser/Playwright）、`RouteGuard`（拦截发往 community host 的非 GET 请求，默认放行列表为空，按 `"[METHOD] /path"` + fnmatch 放行，记录 `blocked`）、`RequestCapture`（只记 `/internal_api/` XHR/fetch，`dump()` 写盘前脱敏）、`Redactor`（字段名、URL 签名参数和 `.env` 里实际凭证值三层替换）。
- 只读示例 `python -m circle_client_skill.probe --path ... --out data/probe`：截图、导出可见表单控件（跳过 hidden/password）、导出脱敏请求日志。没有放行写请求的参数。
- 不加活动写命令，也不加 list-events 命令；活动写操作按 events 参考里的原则走浏览器 UI。
- Live 只读 smoke：headless 打开社区首页，落到 feed、无 401、无登录链接，判定已登录；guard 拦下的都是 analytics、Cloudflare beacon 和 `community_switchers/invalidate_cache` 这类页面自带的 POST，页面照常可用。输出没有写进仓库。
- 新增 `tests/test_probe.py`（23 个离线测试）。

### 2026-10-03 Events reference (docs only)

- 新增 `skills/references/events.md`，记录以 admin 身份观察到的活动流程：Create event 对话框的 Save 发 `POST /internal_api/spaces/<id>/events`，`status` 写死 `"draft"`；发布要进草稿编辑页（"…" → Edit event）点 Publish。字段、Location 五种类型、时区解释、六个 tab、通知默认值、Publish 确认框、只读和写 endpoint 都在里面。
- 确立执行原则并写进 root skill：活动相关脚本只做 probe，活动写操作走浏览器 UI，Publish 永远由人点；CLI 不加活动写命令。往真实 space 写需要主会话里用户的明确授权。
- 观察到的副作用：打开 space 会 `POST .../reset_unread_count`；上传封面会经 `direct_uploads` 建 blob；成员搜索是 `POST /internal_api/search/community_members`。

### 2026-09-27 Single notification mark-as-read

- 新 mutation `mark-notification-read <notification_id>`：`PATCH /internal_api/notifications/<id>/mark_as_read`，cookie + X-CSRF-Token，200/204 均视为成功。默认 dry-run，live 必须 `--execute --confirm MARK-NOTIFICATION-READ`。URL 由 `notifications_url` 派生，不需要新 config 字段。
- 已读是服务端状态：`read_at` 落库后该通知从 unread-only fetch 中消失、`count` 下降。在课程页/讨论页读 comment 不会写 `read_at`，只有从 inbox 点开通知或本命令才会。
- 与 `reset-count`（badge 重置）和未来的 mark-all-read 是三个不同的 mutation；本命令只做单条。

### 2026-09-27 Threads are always fetched

- `lesson-comments` 去掉 `--with-threads`。对 `replies_count > 0` 的根消息一律再拉一页回复，N+1 是固有成本。JSON 固定为 `roots` + `threads`，不再回退到 `records`，也没有 `with_threads` 字段。
- `--focus <id>`：root id 命中则只留该 root 并只抓它的 replies；未命中则在已抓 replies 里找，命中留其 root 和全部 replies；都不中报 `message <id> not found among roots or fetched replies`。不在本次 window 里视为未找到。
- `mention-sgids` 去掉 `--no-threads`。`mention_sgids_in_room` 同步删掉 `include_threads`，恒抓 thread 回复。

### 2026-09-27 Paragraph-aware message text and mention-sgids

- `circle_ios_fallback_text` 把所有 tiptap 段落压成一整段，段落间空行丢失。mention 节点没有 `text`，旧 `_plain` 会渲染成空字符串，表格里 @ 直接消失。读消息正文改走 `rich_text_body.body.content`：非空 paragraph 用空行连接，段内 `hardBreak` 保留换行，mention 用同条消息 `community_members` 的 sgid→name 解析成 `@Name`，解析不到用 `@…`。空 paragraph block 是视觉间距，不产生文本。没有可解析段落时，`rich_text_message_text` 才回退到 strip 后的 fallback。表格预览仍由 `_truncate` 压空白，换行不会撑破列对齐；卡片正文保留段落。`format_lesson_card` 仍优先 fallback，未改。
- 一条消息的 `community_members` / `sgids_to_object_map` 只包含这条消息里被 mention 的人，不含作者本人的 sgid。要 @ 作者，不能从他自己的消息里取 sgid。
- 新只读命令 `mention-sgids`：从 room 当前 window 的根消息聚合被 mention 过的人，并对 `replies_count > 0` 的根再拉一页回复（没有跳过开关）。按 sgid 去重，输出 name / community_member_id / user_id / sgid；name 缺失时后续消息可补全。room 解析与 `update-chat-message` 相同（`--room-uuid`、`--space-id`，或 space + section + lesson）。空 window 提示改用 `search-mentions --query <name>`。
- 回复并 mention：先 `mention-sgids` 拿 sgid，再 `chat-send --mention-sgid <sgid> --parent-message-id <root-id>`。不知道名字用本命令；知道名字仍用 `search-mentions`。

### 2026-09-27 Chat message edit, mentions, and lesson comment focus

- 新增 mutation `update-chat-message`（默认 dry-run，live 需 `--execute --confirm UPDATE-CHAT-MESSAGE`）。契约是 `PATCH /internal_api/chat_rooms/{uuid}/messages/{id}`，body 为 `{"chat_room_message": {"rich_text_body": <object>, "attachments": []}}`。服务端从 session 识别作者，**不传** `chat_room_participant_id`。接受 200/202/204（实测 chat mutation 会返回 202）。sgid 是 mention 凭证，绑定当前 session，不是独立 token，但 `--json` 输出仍属敏感数据，不要进公开渠道。
- 确认已有发送契约：`POST .../messages`，body `{"chat_room_message": {"chat_room_participant_id", "rich_text_body", "parent_message_id"(可选), "unfurl_urls": {}}}`。`mention_sgids` 省略时 rich_text_body 与改前逐字段一致（整段文本仍是一个 paragraph，不按行拆）。
- mention 节点是 `{"type":"mention","attrs":{"sgid":"<server-signed>"}}`，后面紧跟一个以空格开头的 text 节点。sgid 不能客户端构造。合法来源：`GET /users/mentions.json?query=&per_page=`（返回 JSON 数组，不在 `/internal_api/` 下；字段含 `id`、`just_name`、`sgid`），或已有消息的 `rich_text_body.sgids_to_object_map` / `community_members[].sgid`。新只读命令 `search-mentions`。
- `chat-send` 增加可重复的 `--mention-sgid`，dry-run preflight 增加 mentions 数量。room 三选一：`--room-uuid`、`--space-id`，或 `--space-id` + `--section-id` + `--lesson-id`（后者走 lesson 的 `chat_room_uuid`）。`update-chat-message` 用同一套 room 解析。lesson/space 解析在 dry-run 时仍会发只读 GET，因为 preflight 要打印解析后的 uuid；只给 `--room-uuid` 时不发请求。
- `lesson-comments --focus <id>` 在现有 window 截断之后过滤。root id 命中则只留该 root 及其 replies。未命中时在已抓 replies 里找，命中则留其 root 和全部 replies。都不中则报错。不在本次请求 window 里的消息视为未找到。JSON 是单线程的 `roots` + `threads`。
- 新增离线测试 `tests/test_chat_edit.py`，以及 `tests/test_course.py` 的 focus 用例。fixture 只用合成 id、uuid 和 `example.test`。
- `--env-file` 和 `--json` 一样，可以写在子命令后面。父 parser 上的 `--env-file` 原先只在子命令前生效。

### 2026-09-27 Course content and lesson comments (read-only)

- 新增三个只读命令：`course-lessons`（列 section/lesson id）、`course-lesson`（lesson 正文、附件和 `chat_room_uuid`）、`lesson-comments`（读该 lesson 的讨论）。
- lesson 讨论存在 per-lesson chat room，不是 post comment。lesson endpoint 必须走带 section 的路径 `GET /internal_api/courses/<space_id>/sections/<section_id>/lessons/<lesson_id>`；不带 section 的 variant 返回 404。
- `lesson-comments` 根消息 newest-first，pagination 元数据（`first_id`/`last_id`/`has_*`）保留 ascending 原页。对 `replies_count > 0` 的根消息一律再拉一页回复，N+1 是固有成本。JSON 用 `roots` + `threads`，没有 `with_threads` 字段。
- 实测 lesson 讨论 room：服务端忽略 `previous_per_page`/`next_per_page`（0/2/15 重复测量都一次返回全部根消息，`total_count` 含 thread replies 而 feed 只列根消息）。`lesson-comments` 因此在输出层按请求的 window 截断（previous 取最新 N 条），flag 语义才成立；`list-chat-messages` 保持原契约未动。
- `course_comment` 通知的 `action_inbox_path` 形如 `/settings/inbox/course-comments/<room-uuid>`，可直接 `list-chat-messages --room-uuid <uuid>`；`action_web_url` 里 `#message_<id>` 是根消息 id。
- 这些 endpoint 是通过 Playwright 注入 cookies，再用 CDP `page.on` 监听 internal_api XHR 发现的，不是猜的。
- 新增离线测试 `tests/test_course.py`：sectioned URL、formatter、`course_sections` 为 null、lesson 无 `chat_room_uuid`、newest-first 且 pagination 元数据保留、`replies_count` 为 0 不发 N+1、三个命令的 `--json` 放在子命令后仍生效。

### 2026-08-06 list-posts 新增 --with-counts (replies count)

- `list-posts --with-counts`：对每个 post 调 `list_comments per_page=1` 拿 `count`，注入 `comments_count`，formatter 在 `comments_count` 存在时显示 REPLIES 列。N+1 请求，opt-in。
- 确认 Circle member-session API 的 post-list / post-detail endpoint 都不返回 post 级别 `likes_count`，也无 `/internal_api/posts/<id>/likes` endpoint。comment 对象带 `likes_count`，post 不带。likes 列不加，skill 文档已写明这一限制。
- 新增测试：`test_list_posts_with_counts_injects_comment_count`、`test_list_posts_without_counts_does_not_probe_comments`、`test_format_posts_table_replies_column_only_when_counts_present`。

### 2026-08-06 Chat room feed 默认倒序 + skill 文档补"获取最新内容" workflow

- `cmd_list_chat_messages` 在输出层 reverse records，让 room-level feed 默认 newest-first；`list-chat-replies` 保持 ascending（thread 自上而下阅读）。Circle chat API 本身永远返回 ascending，所以 reversal 放在 CLI 输出层，不动 client 层契约、不动 pagination 元数据（`first_id`/`last_id`/`has_*` 仍对应 ascending 原页，用于推导下一页 cursor）。`scan_chat_roots`/`unreplied` 直接调 client，不受影响。
- 新增测试 `test_list_chat_messages_renders_newest_first` 覆盖 reverse 行为和 cursor 元数据保留。
- canonical skill 和 workspace 私有 skill 新增"获取最新内容"workflow：`get-space` 判 `type` → `list-posts`（post space）或 `list-chat-messages --direction previous`（chat space），两路默认 newest-first。同时写明 page 内 ordering 与 cursor 翻页方向是两个维度，不耦合。
- `list-posts` 本来就按 `published_at` 倒序（置顶钉顶），不改代码，只在文档里把契约写明。

### 2026-08-06

- 完成 CLI 输出改版：默认输出紧凑纯文本表格/卡片，`--json` 保留 JSON 通道；新增独立 `formatters.py` 和 TipTap plain-text 提取。
- 新增 `get-space` 与 `unreplied` 命令；三个 chat 命令都支持 `--space-id` 自动解析 `chat_room_uuid`。
- 修复 chat 分页 contract：删除无效的 `before_creation_uuid`，改用数字 `id` cursor、`first_id`/`last_id` 和 previous/next 方向。
- 新增 `scan_chat_roots`，处理 cursor anchor overlap、message ID 去重、cursor 前进检查、`max_pages` 上限和 `total_count` 一致性验证。
- 新增 formatter、CLI unreplied 和完整 root scan 的离线测试。

- 通过 Playwright CDP 拦截 Circle 前端 fetch 调用，逆向出 posts/spaces/comments/chat/image upload 的 internal API endpoint。
- 所有 endpoint 已用 plain `requests` + cookie + CSRF 验证通过（test posts space + test chat room）。
- 新增 `CircleSettings.base_url` property，从 notifications_url 推导 community host。
- 新增 `CircleClient._request` 通用 HTTP 方法，支持 GET/POST/PATCH/DELETE，透传 status code 和 response body 片段到错误信息。
- 新增 14 个 client 方法：list_spaces, get_space, list_space_topics, list_posts, get_post, create_post, update_post, delete_post, get_post_details, list_comments, create_comment, upload_image, list_chat_messages, fetch_chat_replies, send_chat_message。
- 新增 11 个 CLI 子命令：spaces, list-posts, create-post, update-post, delete-post, reply-post, upload-image, chat-send, list-chat-messages, list-chat-replies。所有 mutation 默认 dry-run，live 执行需 `--execute --confirm <ACTION>`。
- 新增 `tests/test_posts_chat.py` 覆盖所有新 endpoint 的 method、URL、payload schema 和错误处理。
- 更新 PRD（V1 目标）、RFC（endpoint contract 表、base_url 推导、V1 mutation 边界、chat 分页机制）。

### 2026-08-06 Thread Reply Debug

- Thread reply 的 `parent_message_id` 实现确认正确——之前的 "失败" 是 verify 脚本的 bug：脚本用 `r.json().get("id")` 获取 parent message id，但 chat message POST 返回的 response 只有 `creation_uuid`，没有 `id`，所以 `parent_message_id` 变成 None，消息变成了独立消息而非 thread reply。
- 修复后用正确的 parent message id 测试，API 返回 202 且 `parent_message_id` 正确回显，浏览器端 thread 视图也确认消息进入了 thread。
- 新增 `fetch_chat_replies` 方法，用 `GET /internal_api/chat_rooms/{uuid}/messages?parent_message_id={id}` 读取 thread 回复。
- 修复 `list_chat_messages` 参数：从 `page+per_page` 改为 `previous_per_page+next_per_page+before_creation_uuid`（Circle chat 用 cursor-based pagination，不是 page numbers），参考 translation bot 的实现。
- 新增 `list-chat-replies` CLI 命令。

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
- Chat thread reply 的 `parent_message_id` 实际工作正常。之前的 "失败" 是 verify 脚本 bug——用 `response.id`（不存在，response 只有 `creation_uuid`）作为 parent_message_id，导致 None。
- `csrf_token` cookie 可能在页面 reload 后变化；`.env` 里的 CSRF 值需要定期更新。
- Circle chat 用 cursor-based pagination（`id` + `previous_per_page` + `next_per_page`），不是 page numbers。历史方向以 `first_id` 为 cursor，未来方向以 `last_id` 为 cursor；相邻页含 anchor overlap，必须按 message ID 去重。
- 编辑聊天消息的 PATCH 不带 participant id；发送的 POST 仍然要带。mention sgid 是服务端签名，`/users/mentions.json` 返回的是 JSON 数组，不是 `{records: ...}` envelope。
- chat 消息只携带被 mention 者的 sgid，不携带作者 sgid。`circle_ios_fallback_text` 会压平段落并丢掉 mention，读正文要用 `rich_text_body.body.content`。
- 打开任何社区页面都会触发前端自己的写请求（analytics、Cloudflare beacon、cache invalidation、space 的 `reset_unread_count`）。probe 的 `guard.blocked` 里出现这些是正常的，判断有没有意外写入要看具体 endpoint。
- 通过 `connect_over_cdp` 连接的浏览器不接受 Playwright `set_input_files` 传大于 50 MB 的文件；CDP `DOM.setFileInputFiles` 传本地路径没有这个限制。Circle 的 Add cover 不触发 file chooser，而是打开带独立 file input 的对话框。
- 往 tiptap 编辑器里放长文，合成粘贴受光标位置影响（起始 H2 会丢），对话框里键盘全选清空也不可靠；直接用 `el.editor.commands.setContent` / `insertContentAt` 组装，再用 `editor.getJSON()` 回读。
- Circle 视频的自动转写会认错语言（英文讲座被转成中文）。英文讲座上传自制双语 WebVTT；Zoom 的 `transcript.vtt` 比 `cc.vtt` 的时间戳准。剪辑过的视频，字幕时间轴要和章节时间戳一样按剪辑映射。
- Circle 的视频播放器在 shadow DOM 里，内部还有一个 role=dialog 的 media-error-dialog；找 video 要递归 `shadowRoot`，找对话框要按 accessible name。
- 可见 Chrome 的窗口全部关掉后，session cookie 丢失，`connect_over_cdp` 报 "Browser context management is not supported"；先 `PUT /json/new?<url>` 开 tab 再连并重新注入 cookie。
- 活动的「建」和「发通知」是两个动作：Save 只建草稿，发布邮件只在 Publish 那一刻发且不能重发。通知开关默认全开，而且只在草稿编辑页出现，Create 对话框里看不到。只有 admin 能看到的 test space 若有非 admin 成员，Publish 也会通知他们。
