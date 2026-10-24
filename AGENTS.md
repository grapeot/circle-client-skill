# Circle Client Skill

## 项目定位

这是一个面向 Circle 普通成员的非官方客户端 Skill。当前稳定范围只有：从浏览器 Copy as cURL 导入临时登录凭证、读取 new notification count、分页抓取个人未读通知（存为 JSON artifact），以及 one-stop 通知 dashboard（人用的交互面，0.2.0 起取代已移除的静态 render/serve）。

## 结构

- `src/circle_client_skill/`：CLI、认证导入、只读客户端和渲染逻辑。
- `src/circle_client_skill/reactions.py`：reaction 契约常量（chat unicode 集、comment named 类型、glyph 映射）。
- `src/circle_client_skill/dashboard.py` / `dashboard_ui.py`：one-stop 通知 dashboard（分组/enrichment/缓存纯逻辑 + 127.0.0.1 本地服务 + 单页 UI）。
- `src/circle_client_skill/subtitles.py`：录像双语字幕的离线工具（WebVTT 解析、按剪辑映射时间轴、按比例切分、双语组装、`&`/`<`/`>` 转义、校验），不联网。
- `src/circle_client_skill/probe/`：可见窗口观察工具（默认 `headless=False`；cookie 注入 session、route guard、脱敏抓包），Playwright 是 optional extra，测试全部 mock。`headless=True` 仅在用户明确要求或无 GUI 时 opt-in。
- `skills/circle_client.md`：唯一 canonical root skill。
- `docs/`：PRD、RFC、测试策略和持续工作记录。
- `tests/`：默认完全离线；live test 必须显式启用。
- `scripts/run_cli.sh`：本地稳定入口。

## 环境

使用项目自己的 uv 环境：

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e '.[dev]'
```

## 不可破坏的边界

- 这是 public-ready repo。tracked 文件只能包含 fake domain、fake token 和 synthetic fixture。
- `.env`、浏览器 cURL、原始通知、渲染后的私人通知和 live test 输出不得提交。
- cURL importer 只能解析文本，绝不能执行用户提供的 shell 命令。
- 发送认证信息前必须验证 HTTPS 和 `/internal_api/notifications` 路径。
- 默认能力保持只读。所有 mutation 命令（reset-count、mark-notification-read 及 post/chat 写操作）必须 dry-run first，live 执行需同时 `--execute --confirm <ACTION>` 且用户对该次动作明确授权；mark-all-read 尚未实现（`mark-notification-read` 只做单条）。
- `open-notifications` 是本地只读动作（读 fetch artifact、调 OS opener），不联网、不改 Circle 状态、默认 dry-run，live 需 `--execute --confirm OPEN-NOTIFICATIONS`；只打开落在 artifact `source.host` 上的 http(s) URL。打开不等于标记已读。
- `react`（chat 消息反应）默认 dry-run，live 需 `--execute --confirm REACT` 且用户当次授权；只加不减，不做 un-react。reaction target 类型由 `dashboard.VERIFIED_REACTION_KINDS` 门控：未经验证回读的类型（现验证了 chat unicode 与 comment named like）页面不出现反应按钮。
- `dashboard` 是人用的交互面：服务只绑 127.0.0.1、校验 Origin；页面上每次点击视为用户本人的明确授权动作（对应「人亲手点 Publish」），server 绝不自动或批量 mutation；动作日志留 gitignored `data/dashboard_log.jsonl`。页面内不做发消息回复；需要回复时引导用户打开 Circle 页面。`/api/verify` 是只读回读端点（反应后重拉单 context 确认落地，供页面原地更新）：无 mutation、不进动作日志，失败响应用固定错误消息（上游错误串可能含正文片段，不得透传）；操作后页面不整页自动刷新，行以 done 样式原地保留，手动刷新才从列表移除。
- probe 工具的 route guard 默认放行列表必须为空；只有人授权了某次具体写操作，才在调用处放行那一个 endpoint。probe 输出只进 gitignored `data/`。
- 活动（event）相关脚本只做 probe（观察、截图、回读）。活动的创建/编辑/发布走浏览器 UI，Publish 由人点；不要给 CLI 加活动写命令。详见 `skills/references/events.md`。
- 帖子的写操作（发帖、编辑帖子）走人类可见的浏览器：agent 用 `open-browser` 开独立 profile 的 Chrome 填好编辑器后停住，不点 Publish、不点 Save draft，由人发布。`open-browser` 不得附着到已有浏览器（端口被占或 profile 被锁就拒绝）。编辑器的通用操作（全屏展开、插图与竖图半宽、视频、正文重建、Topic）见 `skills/references/browser_post_composer.md`，回放帖特有的惯例见 `skills/references/recording_posts.md`。唯一例外是批量把课程 lesson 迁成帖子：用户对这次迁移明确授权 API 建帖、帖子先落在只有管理员可见的 Secret 暂存 space、由人审阅后决定开放 space（相当于人点 Publish），且每批原始请求先打印方法、路径和 payload 作为 dry-run 再发，见 `skills/references/public_posts_migration.md`。
- 对真实读者可见的回复/发送（lesson 讨论回复、给成员回帖、chat 发言）先 `open-browser` 打开目标页面，让用户能看到发送结果并点进去核对；这个窗口兼作回读和兜底。CLI 的 `chat-send` 留给 test space 和脚本化场景，live 发送后必须回读（`list-chat-replies` / `list-chat-messages` 里出现新 message id）才算成功，202/`creation_uuid`/"OK: sent" 不是送达证据。`chat_room_participant_id` 是 per-room 值，不是账号常量，填错会静默丢消息。详见 `skills/references/reply_in_browser.md`。
- 已发布帖子的视频设置（Customize media：字幕、章节、封面帧）是写操作：只有用户对这一次修改明确授权后，agent 才点 Save（或跑 `post-media-settings --execute --confirm POST-MEDIA-SETTINGS`），并立刻回读 `video.textTracks`。帖子和复用了其 `signed_id` 的 lesson 共用媒体，改一边另一边跟着变。
- 所有输出和错误必须遮罩 Authorization、Cookie 与 CSRF 等凭证。
- Circle internal API 没有稳定公开 contract。保留底层 HTTP status 和脱敏错误，但不要把响应中的私人通知全文打印到错误信息。
- 行为、CLI contract 或安全边界变化后更新 `docs/working.md`。
- 只有用户明确要求时才 commit、push 或创建 GitHub repo。

## 验证

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
```

公开前还必须扫描真实域名、JWT、cookies、邮箱、内部路径和 secret-manager reference。
