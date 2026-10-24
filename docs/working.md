# Working

## Changelog

### 2026-10-23 Video thumbnail reruns click Replace

- `lesson-media-settings` / `post-media-settings` `--video-thumbnail` failed with a 30 s timeout on any video that already had a custom thumbnail: the Custom thumbnail slot shows Add image only while empty and Replace (plus Remove) afterwards. New `open_thumbnail_chooser` clicks Add image, else Replace, else raises before anything is saved. Found while replacing thumbnails on five already-configured lessons; tests cover both labels, the preference order and the missing-button error.

### 2026-10-23 Public posts-space migration; post-media-settings; VTT escaping

- New reference `skills/references/public_posts_migration.md`: covers why course lessons cannot be opened logged out, which posts spaces can; why renamed space slugs are never freed (the old slug 302s and drops the query string; Redirects only cover Website-builder pages); and how to migrate a lesson to a post by reusing `featured_media.signed_id` in a TipTap `file` node. Captions, chapters and the cover hang off the blob, so they carry over and stay shared with the lesson. The reference also covers `published_at` backfill, per-post and space-level Hide from featured areas, ~20 s pacing after an HTTP 429, staging in a Secret space and then opening it, native-video posts via `direct_uploads`, safely prepending a pointer to published lessons (backup, intercept the editor Save, restore settings fields the editor rewrote, read back), and a verification checklist.
- New `post-media-settings` command (dry-run by default; live needs `--execute --confirm POST-MEDIA-SETTINGS`): it drives the same Customize media flow as `lesson-media-settings` from a post page. `set_media_settings` gained `target="post"`, `open_post` and a player-centred hover.
- Bug fix: a bare `&` in WebVTT cue text makes Circle's Customize media Save silently do nothing (no request, no error). `build_bilingual_vtt` now escapes `&`, `<` and `>` while keeping WebVTT tags and character references (`escape_cue_text`); `validate_vtt` reports unescaped characters; both media-settings commands refuse such a transcript before opening a browser (`check_transcript`).
- Independent review fixes: BOM-prefixed VTT files are accepted (`utf-8-sig`, `validate_vtt`, `parse_vtt`); any named/decimal/hex character reference is kept (`&quot;`, `&#X26;`); forbidden-word checks run on unescaped text; the post player is scrolled into view before hovering, and a missing Customize media button raises a clear error; the doc states the API-post exception to the browser rule and the raw-request dry-run requirement.
- Tests: escaping, idempotence, references, BOM, validation, post target routing, URL validation and normalization, the host check, the confirmation gate and the transcript pre-check. All offline.

### 2026-10-23 Event announcement audience and RSVP controls

- Documented visibility versus registration eligibility, the attendee-only publication-email pitfall, and the separate membership CTA fields for members without access.
- Added an explicitly chosen community-promotion pattern without making it a universal default or promising delivery or direct-stream access enforcement.
- Corrected the resend guidance: saving visibility does not resend an announcement, and broadcast/workflow email entry points can require Email Hub. No live writes or billing activation are introduced; community-specific policy and communication records stay private.

### 2026-10-21 Reusable chat watch-diff

- GET-only chat scanning, root pagination with progress/page bounds, dirty-thread
  reads and actual-author participation. No notification or automatic checkpoint writes.
- Silent missing-file baseline; corrupt/identity-mismatched state fails closed.
  Delivery consumer commits via digest-checked atomic 0600 checkpoints.
- Offline tests cover baseline, events, self/other-thread suppression, pagination
  failure, timestamp-only change, stale commit and privacy of state permissions.
- Public contract: `skills/references/watch.md`; runtime targets and mail runner
  remain outside tracked files.

### 2026-10-21 Verify read-back uses the thread anchor; spinner self-terminates (0.2.3)

- Code review（grok）两处 must-fix：
  1. **anchor 缺失 + 缓存污染**：verify 回读调 `build_room_rows` 时没传 anchor，线程根在默认窗口外时回退 scan/bounded-walk 失败，目标被建成 missing 标记行（空 reactions）并写进 context 缓存；之后 `/api/state` 刷新用 `rows_for` 的 target_ids 子集命中该缓存条目，**永远不再走 anchor 真回读**。修法：抽出 `_room_anchors()` helper（`_enrich_context` 与 verify 共用同一逻辑），verify 从 `notifications_by_id` 重建通知列表取 anchor，回读参数与刷新路径完全一致，缓存条目互相兼容。新增 `test_verify_refetch_uses_thread_anchor`（窗口外线程断言 anchor 路径被走、行非 missing、verify 后 build_state 命中缓存不再重拉）。
  2. **spinner 悬挂**：标已读去掉收尾自动刷新后，`markRead` / `markGroup` 循环结束不再有人关 spinner（原来由 `refresh()` 的 finally 关），页面停留在「已读 N/N…」。修法：两个循环收尾 `spinner(false); render(); return;`。新增 `test_page_terminates_spinner_after_mark_read` 模板级守卫（JS 无离线执行环境，行为验证靠手动 smoke）。
- 版本 0.2.3；文档同步（README / public skill / working.md）。

### 2026-10-21 Verify failure responses use a fixed message (0.2.2)

- Privacy review（gpt_6_sol）must-fix：`/api/verify` 的回读重拉若上游返回非 2xx，client 的 `CircleClientError` 消息里带 `response.text[:200]` 正文片段（凭证正则遮罩不删普通正文），`_run_action` 会把 `str(exc)` 原样放进错误 JSON——成功响应的字段白名单管不到失败分支。
- 修法：`verify()` 把 enrichment 调用包进 `try/except CircleClientError`，统一抛固定消息「回读失败；请点刷新重试」（502），上游错误串只进本地 traceback，不出现在响应面。新增 `test_verify_error_response_is_fixed_message`（合成 body 片段断言不出现在 ActionError 消息）。
- 边界说明：`/api/state` 的 per-context `error` 字段与 `/api/react` 的失败响应仍有同一透传模式（0.2.0 前既有行为，本 PR 不扩大也不收缩该面）；verify 作为新端点按「只读端点响应面无内容」标准修。

### 2026-10-21 In-place reaction update with targeted read-back (0.2.1)

- 行为变化（用户拍板）：dashboard 上点反应/标已读后不再整页自动刷新——原来的 400ms 防抖刷新会重拉未读，刚标已读的行立刻从页面消失。现在行原地保留为 done 样式（半透明 + 「✓ 处理过」），到下一次手动刷新才从列表移除。
- 新增只读端点 `POST /api/verify`：payload 与 `/api/react` 同形；复用 kind 门控与 `_locate` 约束（只能回读当前页面上看得见的那一行），只重新 enrich 目标 context（react 已失效其缓存，在场的行是对 Circle 的真回读；窗口外 missing 行短路无额外请求），返回该行的 `id` / `is_target` / `reactions` / `missing`（前端据此区分「无反应」与「回读不到」）。无 mutation、不写 `dashboard_log.jsonl`。
- 前端：`react()` 重写为 react → done set → verify → 把回读到的 reactions 写回 row → 本地 `render()`（零网络，非整页 reload）；verify 失败只红条提示「回读确认失败：点刷新核对」，不删行、不自动刷新。`markRead` / `markGroup` 收尾同样改为本地 `render()`。删除 `act()` / `scheduleRefresh()` 死代码。
- 版本 0.2.0 → 0.2.1（pyproject、`__init__`、README 版本变更）。文档同步：public skill dashboard 节与本地服务边界、rfc endpoint 描述、design_dashboard 状态注记与 §7 动作表、项目 AGENTS.md dashboard 边界行。

### 2026-10-21 Retired the static render/serve workflow (0.2.0)

- CLI contract 变化：移除 `render`（md/csv/html）与 `serve` 两个命令，`dashboard` 成为通知可视化的唯一交互面；「看通知」首要工作流从 `fetch → render → open index.html` 翻转为 `dashboard`。
- `render.py` 删除；被 `opener.py`（open-notifications 分类）依赖的 `normalize_notification` / `category_for_notification` 移入新模块 `src/circle_client_skill/normalize.py`，行为不变，测试迁到 `tests/test_normalize.py`。
- 全 workspace 无 render 产物下游消费者；fetch 的 JSON artifact 仍是规范存储，`open-notifications` / `react` 不受影响。
- 文档同步：public skill 首要工作流与命令参考、私有 overlay 默认工作流、rfc 命令列表与输出哲学、design_dashboard 状态注记、README 版本变更、项目 AGENTS.md 定位段。

### 2026-10-21 Lesson media settings wait for a processing video

- 一次真实课程发布：featured 视频（约 100 MB、17:50）上传到 100% 后立刻跑 `lesson-media-settings`，章节循环报 `seek failed: button says 'Add at 00:10', wanted 03:49`。日志里已打印封面和字幕步骤，但 Save 在函数末尾，什么都没存；约 3 分钟后整步重跑成功。判断是 Circle 还在处理视频，预览只能 seek 到已处理的部分。
- `set_media_settings` 给了章节时，先等对话框预览的 `duration` / `seekable` 覆盖最后一个章节，再碰封面和字幕；每次 seek 失败后重新执行 `SEEK_JS` 重试。两者共享 5 分钟等待上限，超时抛 `MediaNotReadyError`，说明视频可能还在处理、什么都没存、几分钟后重跑。等待逻辑拆成 `retry_until` / `player_ready` 纯函数，离线测试用假页面覆盖了等待后成功、就绪超时不动对话框、seek 重试有界三种情况。
- 文档：`course_lessons.md` 和 root skill 写明等视频处理完再跑、失败时整步重跑；lesson 的 Publish 流程里没有通知学员选项（2026-10-21 观察一次），交付清单不再让人决定发布时是否通知。

### 2026-10-20 Verified Post moderation

- Added `get-flagged-content`, offline-default `approve-post` and `reject-post`, with explicit CLI confirmation and expected Post/space identifiers.
- Live calls verify the target, execute one PATCH and verify the resulting moderation state. Same-action serial repeats skip the mutation; uncertain responses trigger readback instead of blind PATCH retries. No cross-process lock or platform exactly-once guarantee.
 - Captured web contracts and controlled tests informed the adapter; only synthetic fixtures enter this repository. Offline tests cover wrong targets, opposite states, retained reject pending timestamps, uncertain writes, and failed readback. Ruff and the full offline suite passed.

### 2026-10-19 Paywall trial reschedule playbook

- 新增 `skills/references/paywall_subscriptions.md`。这是可见浏览器加官方 Admin API v2 的操作手册，不是新 CLI，也不执行 live 写操作。
- 一次自有 genuine trial 上已验证：GUI Extend trial、`extend_trial`、`ends_at: now` 取消、归档后 paywall `inactive`。只保证选中的 calendar day，不保证秒级增量。
- `change_billing_date`、付费后退款并保留订阅、`at_period_end`、checkout 在绑卡前展示个人首扣日、到期非零扣款，均未由这次实验验证。
- root skill 和 README 只加路由。`/paywalls/{id}` 在公开 spec 里是 DELETE，读回走 search，不能当成 GET。

### 2026-10-18 Visible browser is the probe default

- `ProbeSession` 默认 `headless=False`，打开人类可见窗口。`headless=True` 只在调用方显式传入时生效，skill 约定仅用于用户明确要求 headless 或环境没有 GUI。
- `python -m circle_client_skill.probe` 没有写死 headless，也没有 `--headless` 开关，跟随 `ProbeSession` 的可见默认。
- root skill、README、events 参考改为同一原则：浏览器观察和交互默认 `open-browser` + CDP 的可见 Chrome，不把 headless 当常规路径。

### 2026-10-15 Rows slimmed to target threads + anchor-directed thread jump

- 用户反馈：只 care 未读评论，room 卡片不该把整个默认窗口（一两天内所有 root）都铺上，评论也不该把没用的分页拉完。
- room rows 收窄到「只渲染目标所在的 thread」：含目标线程的 root + 全部 replies 才进卡片，无关 root 不再渲染；评论分页加 `chains_resolved()` 提前停（全部目标与其祖先链都解析即停，不再机械翻满 5 页）。
- 老 thread 命中走通知自带的锚点直达：`action_web_url` 的 `#message_<root>` 就是 thread 根 id——对不在窗口的目标直接 `fetch_chat_replies(root)`（一次请求、不需要 root 记录），去掉常见的全量向后扫描；backward walk 降级为无锚点时的最后手段（有界 12 页，每页 200 roots，捡回即解析+扫 replies）。
- 缩进加强：按 depth 缩进 36px/层 + reply 行左侧 rail 线（`.row.reply` 边框）。
- 两个收尾修复：①`_enrich_context` 的目标 annotation（actor/target/notification_ids）之前只写在被丢弃的拷贝里，卡片行拿不到——已在 annotated 列表上回填（这也意味着此前 UI 的行内反应走的是 react-only 路径、从未挂 mark-read；修复后未读目标行的反应恢复「反应+已读」语义）；②reply 行的父 root 记录不在 pool 时 depth 仍为 1（parent_id 恒定已知）；③reply_to 二遍扫描：父行若是未读 target，借用通知解析出的名字（实测 Andy Lee 的「同感同感」正确显示 ↩ Huang Shengxin）。

### 2026-10-15 Thread organization for room rows and comments

- 用户示例：lesson 讨论里「同感同感」其实是一条对别人 root 的 reply，但平铺渲染看不出来。
- rows 组装改为 thread 组织：每行带 `parent_id` / `reply_to` / `depth`；room 行按「thread root 时间」排序、root 先于其 replies（单层 thread，回复缩进在 root 下），帖子评论按 root 时间序做完整 DFS（支持更深嵌套），missing 行垫底。
- room 现在读作 feed：默认窗口里的全部 root 都渲染（保序），只有含目标/含 fetched replies 的 thread 展开；bare root 带 `hidden_replies` 计数提示（UI 显示「＋N 条回复未展示」）。
- 作者名边界实测：课程 room 的 participants 列表覆盖全体成员（2400+ 人、per_page 钉死 100、SPA 也是懒加载）；`thread_participants_preview` 只带 mention 对象、没有作者。**名字按 best effort**：participants 前 3 页 + 通知自带 actor_name；取不到就只渲染 "?" chip（含缩进与 ↩ 结构表达回复关系，不阻塞可读性）。
- 一次性探查脚本：`data/probe_rxn/discover_names.py`（课程页 participants 观察，结论 = 无按消息作者的便宜 endpoint）。

### 2026-10-15 Reaction confirmation from real state (no optimistic painting)

- 用户反馈：点完红心要在页面上看到真实的 ❤️×1，不接受本地画假状态（"不希望这是个 UI UX trick"）。
- 机制：react 成功后失效该 context 的 enrichment 缓存，前端在动作后做 400ms 防抖刷新（连续点击合并成一次），行上的反应数从 Circle 回读的真实 state 渲染；本地 done 灰显只作为已读消失前的过渡标记，不承担反应生效的证明。
- context 增加 `context_id`（room uuid / post id），react 按 target kind 映射回缓存 key 做 `DashboardCache.invalidate`。

### 2026-10-15 Reactions on every thread row

- 用户澄清用法：想在线程里浏览学员作业（含旧的、非未读行）时直接给个心，不点进 Circle。
- react API 支持无 notification_id 的 react-only 路径（server 校验该消息/评论存在于当前页面上下文，不标已读）；未读目标行保持反应 + mark_as_read。UI 给每个非 missing 行渲染反应按钮。
- 测试：react-only 路径（create_reaction 调用、无 mark_read、未知行 404）。

### 2026-10-15 Room window misses (targets outside the default feed window)

- 实测发现 lesson 讨论 room 的 messages endpoint 默认窗口只回最近 21 个 root，而 2025-02 的老 thread 仍会有 2026-10 的新 reply 未读（`#message_138871287` 老 root + 两条新 reply 都在窗口外）。此前把它们渲染成「该消息不在最近窗口内」+ 未知成员。
- 修复：`build_room_rows` 在目标缺失时向后 cursor 翻页（`previous_per_page=200`，最多 12 页；无新 id/到底即停），随后扫描所有已知 root 的 replies 拾回目标线程。真实数据复测两个 context 全部解析、全页 0 missing。
- missing 行 UI 只渲染提示 + 打开链接，不再渲染「未知成员」头像条（无内容时不给反应/已读按钮，避免没读内容就下手）。

### 2026-10-15 Dashboard 排序与样式微调（用户反馈）

- 讨论区排序改为 room → post → post_link 分层（lesson 讨论置顶，对齐旧 render 的分组顺序），同层内按最新活动倒序；stable sort 两步实现，补排序测试。
- UI 微调：头像 chip 与用户名 flex 对齐（去掉 vertical-align hack）；页面/卡片/margin 全面放宽；「全部已读」加二次确认步（6 秒内再点一次才执行）。
- 加新 emoji 不改代码：`data/emotes.json`（`{"名字": "unicode码"}`）增量扩展 chat 消息的快捷 emoji，无效条目跳过并在 state 带 warning；post 评论保持 Circle 固定的六种 named 类型。
- 设计文档补实施状态注记（含与设计的差异清单）；V2 结论收编进 prd.md/rfc.md。

### 2026-10-15 One-stop dashboard + reactions

- 按 `docs/design_dashboard.md` 落地 V2：`dashboard` 命令（127.0.0.1:8780，自动开浏览器、`--no-open` 可关）+ `dashboard.py` / `dashboard_ui.py` + `tests/test_reactions.py` / `tests/test_dashboard.py`（全部离线）。
- 新命令 `react`（chat 消息反应，dry-run-first + `--confirm REACT`）；client 新方法 `create_reaction`、`create_comment_like`、`list_room_participants`。
- Reaction 双契约（都经 live round-trip 验证后开放）：chat 消息 `POST /internal_api/reactions` body `{"unicode","chat_room_message"}`（响应回显 `{"success","message","reaction"}`，消息记录的 `reactions` 数组可回读）；post 评论 `POST /user_likes` body `{"user_likeable_type":"Comment","user_likeable_id","reaction_type"}`（named 类型；comment 记录 `is_liked`/`reaction_summary.counts`/`current_user_reaction_type` 回读，counts like 5→6 实证）。验证都在账号主人自己的消息/评论上做，未触碰他人内容。
- dashboard 页面三区：要回应的讨论（帖子评论按 post 聚合 31 个 context、lesson 讨论 21 个 room、线程时间正序 + 目标高亮）、点赞折叠组（一键已读逐条循环）、其他（FlaggedContent 不给一键已读）。真实数据首刷实测 ~35s（51 个 context 并行拉取），增量走缓存秒级；badge 用 count envelope 的 `count` 字段（client 层 `{"count", "raw"}`，raw 里才是 `new_notifications_count`）。
- 交互语义按设计默认拍板：点 reaction = 反应 + 自动 mark_as_read；✓ 已读单独一条；回复不进 dashboard（可见浏览器原则）。
- ruff 新增 per-file-ignores：dashboard*.py 的 RUF001（中文 UI 文案的全角标点是有意的）。

### 2026-10-13 Generic composer doc: inline images, portrait half-width, full screen, topics

- 新增 `skills/references/browser_post_composer.md`：把「可见浏览器填写发帖编辑器」从回放帖文档里抽成通用流程，适用于任何空间的帖子。这次在一个项目分享空间里发图文加视频的普通帖，新摸清并写进去的：
  - 打开 Create post 后先点 Full screen：小对话框里工具栏、图片气泡菜单和下拉列表会被遮挡。
  - 编辑时页面上有多个 dialog（AI summary 浮层、Attach image / Attach video、播放器的 media-error-dialog），编辑器用「包含 `.tiptap.ProseMirror` 的 dialog」定位。
  - 正文插图：Add image 打开 "Attach image" 对话框（不弹系统文件选择框），对对话框里的输入框设文件再点 Save，插入带 `signed_id` 的 `image` 节点；对话框外那个 `accept="image/*"` 的输入框不插正文图。image 节点没有文件名，每次上传前后对比 `getJSON()` 记录新增的 `signed_id`。
  - 图片宽度：`width_ratio: null, alignment: "center"` 为满宽；气泡菜单第一个选项对应 `width_ratio: 0.5, alignment: "left"`，即半宽。竖图（手机截图）用半宽，横图满宽；代码里用 `updateAttributes('image', ...)` 或组装时直接写进节点，改完把选区移出媒体节点。
  - 正文组装从「前半段 + 一个视频 + 后半段」推广到 N 个媒体：markdown 在图片位置切开、每段转 HTML，与媒体节点交替 `insertContentAt`。
  - Topic 选择框的 "Choose up to 5 topics" 是 placeholder（用 `get_by_placeholder`）；没选 Topic 时 Publish 是灰的。默认留给人选，用户要求时可代选并回读，仍不点 Publish。
  - 发帖编辑器里没有字幕入口；视频已烧录字幕时不要再上传软字幕。
- `recording_posts.md` 第五节改为引用通用文档，只保留回放帖特有的两点（视频位置、2.8:1 封面）；编辑器相关的坑移到通用文档的坑表。root skill「写帖子」一节和 AGENTS.md 的边界说明改为先指向通用文档。
- 待验证：CLI 的 `upload-image` 拿到的 `signed_id` 能否直接组成 image 节点插入编辑器（可绕开 Attach image 对话框）。

### 2026-10-08 Visible-browser replies and participant-id lesson

- 确立新原则并写进 root skill：**对真实读者可见的回复/发送（lesson 讨论回复、给成员回帖）先 `open-browser` 打开目标页面**，用户在可见窗口里能当场看到发没发出去、能点进去看；同一窗口兼作回读和兜底路径。CLI 的 `chat-send` 保留给 test space 和脚本化场景，且 live 发送后必须回读核验。
- 记录 participant-id 教训：`chat_room_participant_id` 是 per-room 值，不是账号常量；用错 id 时 Circle 仍返回 202 + `creation_uuid`，CLI 打印 OK，但消息被静默丢弃。送达证据只能来自回读（`list-chat-replies` / `list-chat-messages` 能看到新消息 id）。
- 记录可见浏览器里回复 thread 的真实操作路径（`skills/references/reply_in_browser.md`）：打开 lesson 页 → 点根消息展开 thread → 在 `[contenteditable=true]` 的 tiptap 编辑器里输入 → `@` 触发 mention 选人 → 点 aria-label 为 `Send message` 的按钮 → 用 `list-chat-replies` 回读新消息 id。

### 2026-10-07 open-notifications

- 新增 `open-notifications`（`src/circle_client_skill/opener.py` + `cli.py`）：读 fetch artifact，按 category 过滤、按 `source.host` 校验 URL、去重、排序，然后逐条交给 OS opener（macOS `open` / Linux `xdg-open`），间隔默认 3 秒。纯本地、只读、不联网、不加载 `.env`、不改 Circle 状态；打开不等于标记已读。默认 dry-run，live 需 `--execute --confirm OPEN-NOTIFICATIONS`。
- 设计理由（写进 root skill 和 rfc）：页面 JS 用 `window.open` 连续开多标签会被弹窗拦截器挡下，OS opener 由系统派发不受限，所以能力归 CLI。`--category/--interval/--order/--dedupe/--background/--opener` 可调；URL 白名单只放行 artifact host 上的 http(s)。
- 新增 `tests/test_opener.py`（离线，monkeypatch sleep/run）：分类去重、顺序、off-host 拒绝、opener 调用次数、`-g` 映射、失败继续。`tests/test_cli.py` 补 parser 默认、默认 dry-run、confirm 校验、execute 路径；`tests/test_formatters.py` 补 plan/result 格式器。

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

- Visibility, RSVP groups, and notification toggles are not interchangeable audience filters. Record publication-time eligibility and verify saved settings independently; a membership CTA and a successful save are not proof of delivery or direct-stream access enforcement.

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
- `chat_room_participant_id` 是 **per-room** 的，不是账号级常量。同一个账号在不同 lesson 讨论 room 里有不同的 participant id（实测：拿另一个 room 的 id 去发，静默失败；换成本 room 的 id 才落帖）。用错 id 发 `chat-send` 时，Circle 仍返回 HTTP 202 和 `creation_uuid`，CLI 打印 "OK: sent"，但消息被静默丢弃，thread 里什么都没有——**202/creation_uuid 不能当作送达证据**。`--participant-id` 只能填目标 room 里本人的 id，从该 room 的 `GET /internal_api/chat_rooms/<uuid>/participants` 列表里按 `community_member_id` 认领自己的那一条。
- 判断一条消息到底发出去没有，唯一可靠办法是**回读**：`list-chat-replies --room-uuid <uuid> --parent-message-id <root-id>`（或 `list-chat-messages`）里能看到新消息的 id 才算成功。只发不读、只看 CLI 的 OK，就会在失败时误报成功。
- 对真实读者可见的发送（lesson 讨论回复、给成员回帖）要先 `open-browser` 打开目标页面：用户能当场看到发没发出去、能点进去看，同一个窗口也是回读和兜底路径。CLI 的 `chat-send` 保留给 test space 和脚本化场景，live 发送后仍必须回读核验。
- 抓写请求要「guard 拦截 + CDP 层监听」组合：RouteGuard 只记 blocked URL 不记 body，所以要抓 payload 得另挂 `context.on("request")` 读 `request.post_data`（仍然全程 abort，零副作用）。评论 Like 的 endpoint 是 `POST /user_likes`，不在 `/internal_api/` 前缀下。
- Playwright 无头探查时，JS `el.click()` 的事件 `isTrusted=false`，React 没反应（只出 analytics 噪音）；要用 Playwright locator 的真实点击。定位 UI 元素时 Circle 用的是 `data-testid`（不是 `testid`），评论文本锚点比猜测的 id 选择器稳。
- 一个进程里嵌套两个 `sync_playwright()`（外面自己开一个再进 ProbeSession）会报 "Sync API inside the asyncio loop" 误报；用 ProbeSession 就别再包自己的 playwright。
- 反应是两套系统：chat 消息走 unicode `/internal_api/reactions`，post 评论走 named 类型 `/user_likes`——同一个「红心」在不同内容上是不同 payload，不要归一成一个 endpoint。
- `get_notification_count` 的 client 层返回是 `{"count": ..., "raw": {...}}` envelope；raw 里才有 `new_notifications_count`。dashboard 直接取 envelope 的 `count`。
