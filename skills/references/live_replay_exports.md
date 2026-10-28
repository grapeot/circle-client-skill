# Circle Live 回放、聊天导出与活动附件

本参考整理 Circle Live 活动回放定位、原始聊天与 Q&A 导出、独立 JSON 归档对账、脱敏附件生成及活动描述挂载。活动字段、回放帖与编辑器操作分别见 [events.md](./events.md)、[recording_posts.md](./recording_posts.md) 与 [browser_post_composer.md](./browser_post_composer.md)。

## 目标与能力边界

- **目标**：定位真实回放归属，完整保留私有原始导出与可选 JSON 归档，仅在获得显式授权后通过可见浏览器向既有活动挂载脱敏附件。页面回读、设置比对及重新下载附件的字节数与 SHA-256 校验是完成证据。
- **能力边界**：复用现有只读 CLI 与受控浏览器会话，不新增运行时 CLI 写命令或直接 API 写入能力。
- **观测基线**：下文界面入口、弹窗行为与内部接口路径基于 2026-10 浏览器端实测；操作前复核当前 DOM 与网络请求，不将它们当作稳定公开 API。

## 1. 定位回放与目标直播间

- **优先核查原活动页**：自动发布的直播回放可能直接挂在原活动页面（如 `https://community.example.com/c/<space-slug>/<slug>`），而非单独新建回放帖。先用只读 `get-post` 检查原活动及 `event_setting_attributes.live_stream_room_setting_attributes.recording_attributes`，不要未核查就新建帖子。
- **通过 Live Dashboard 识别房间**：`/settings/live_streams` 可定位目标直播记录，并从页面或网络载荷中获取 `<room-id>` 与 `chat_room_uuid`（即 `<uuid>`）。
- **核对身份与时间语义**：结合标题、日期与回放标识确认目标场次。墙钟时间戳不等于视频内偏移秒数，单凭房间的 `live_at` 字段也不足以推断录像零点。未对齐录像时，保留原始墙钟时刻并写明时区。

## 2. 聊天与 Q&A 原始导出及可选 JSON 归档

### 后台邮件导出与请求副作用

`/settings/live_streams` 目标行的 `More actions` 菜单包含 `Download chat log` 与 `Download Q&A log`。点击入口会打开确认弹窗；确认后触发的是**后台邮件导出**，不是浏览器直接下载。成功响应提示邮件可能在 5 分钟内送达。

- **不要因下载超时重复触发**：Playwright `expect_download` 超时后，应先检查响应、界面提示及获授权邮箱中的 ZIP 附件，不重复点击或重放请求。
- **观测请求形态**：聊天导出为 `GET /internal_api/live_streams/rooms/<room-id>/transcripts?`；Q&A 导出为 `POST /internal_api/live_streams/rooms/<room-id>/qa/export`。前者虽然能通过默认 `RouteGuard`，仍会触发邮件，**GET 或通过路由守卫不代表无副作用**。
- 上述路径仅作观测记录，不是直接重放指令。通过 UI 触发并观测一次，按响应指定的投递位置查收；不默认指定邮箱服务商，也不把这些邮件触发端点混入普通 GET 回读。

### 原始 ZIP / CSV 保真与解压校验

- 邮件附件为 ZIP，内含 CSV：Chat 列为 `Date, First Name, Last Name, Email, Message`；Q&A 列为 `Date, Type, First Name, Last Name, Email, Content, Upvotes`。
- **私有原件不改动**：原始 ZIP 与解压后的 CSV 保存在本地私有目录（如 `data/example/raw/`），保持字节原样，纳入 gitignore。
- 解压前校验 ZIP 完整性与成员路径，拒绝路径穿越或绝对路径；不得覆盖内容不同的同名文件。Q&A 为 0 行可能是真实情况，报告实际行数，不将其误判为下载失败。

### 可选独立只读 JSON 归档与对账

除邮件 CSV 外，可用 `list-chat-messages --room-uuid <uuid>` 建立 JSON 归档：

- **主消息有界游标翻页**：单页 `per-page` 不代表全量；沿 `has_previous_page` 与 `first_id` 翻页。锚点可能重叠，按消息 `id` 去重，并将去重后的顶层消息数与房间 `total_count` 比对。达到页数上限、游标不前进或无新增进度时应报未完成，不把截断归档当作成功。
- **拉齐非空线程**：对每条 `replies_count > 0` 的顶层消息调用 `list-chat-replies`。`--direction next` 从父消息 `id` 起算，沿 `has_next_page` 与 `last_id` 翻完，剔除父消息锚点，对真实回复按 `id` 去重，并与各自父消息的 `replies_count` 核对。也应有页数与进度边界。
- **口径差异与多重集比对**：CSV 可能将顶层消息与回复合并计数，而房间 `total_count` 只统计顶层消息。文本对账仅归一化 HTML 实体与 CRLF 换行，按**多重集（multiset）**而非普通集合比对，保留重复发言次数。将 CSV 姓名映射到 JSON 父消息 ID 时，同时核对时间戳与消息身份，不合并相同文本的不同发言。
- **顺序与身份不能只靠文本对账**：CLI 根消息 `records` 是最新在前，不能直接拼接分页结果作为阅读顺序。统一时区后按原始时刻及稳定消息 ID 排序，单独保留父 ID，并核对作者、时间与线程归属；文本多重集相同不证明这些字段正确。
- 在私有目录记录来源、顶层消息数、回复数、Q&A 数和文件 SHA-256。

## 3. 脱敏共享稿与授权边界

- **保留获批字段，剔除邮箱**：生成独立共享文件（如 `data/example/cleaned/chat_and_qa_cleaned.txt`），保留获批展示的姓名、正文、时间戳、顺序、回复关系及 Q&A 内容。从输出结构中移除 `Email` 列，并扫描最终全文及文件元数据，排查正文夹带的邮箱地址。
- CSV 没有消息或父消息 ID，不能仅凭它可靠还原回复关系。需要展示回复关系时取得完整 JSON 并核实映射；无法映射则明确标注未知，不根据相同姓名或正文猜测。
- **残余地址与格式**：按授权范围替换残余邮箱，不静默改动其余正文；脱敏后按同一替换规则与原件核对条数与内容完整性。UTF-8 `TXT` 即可，`PDF` 可作衍生版；显式注明原始时区及 UTC 偏移，不把墙钟时间标成录像时间。
- **归档不等于发布授权**：内部归档请求不自动授权社区或网站发布；用户当次已明确要求发布时按该授权执行，不重复请示。只展示获批的姓名等字段，未经授权不扩大受众。
- 社区可见活动或受限 RSVP 不证明附件仅参会者可访问。不要把含邮箱的原始 ZIP/CSV 上传为共享附件，也不要将不可猜的签名资产链接当成访问控制。公开网站托管属于另外的发布决定。

## 4. 活动描述附件挂载与保存

### 挂载位置

既有活动 `Basic info` 的描述编辑器支持 `Attach files`。活动评论区也有附件按钮，但本次观测的活动评论菜单没有置顶入口。活动的 `Pin to space` 置顶整场活动，课程评论支持 Pin 也不证明活动评论可置顶。按目标页面实测判断，不断言所有空间或未来版本都不支持。获得更新活动授权时，可直接把附件加到描述末尾。

### 可见浏览器与受控上传

- 启动专用 `open-browser` / CDP 可见会话。`RouteGuard` 默认拦截社区 host 非 GET/HEAD/OPTIONS 请求；动手前保存最新 `get-post` 与实时编辑器 JSON 到私有目录 `data/example/backup/`。
- 点击描述编辑器的 `Attach files` 打开 **Circle 自身弹窗**，不是系统文件选择器。将 `input[type=file][accept="*/*"]` 限定在该弹窗中，只传已核验的共享文件。等待携带 `signed_id` 的真实 `file` 节点，不得残留 `file-loader` 或 `Upload failed`。
- 文件名可能只在界面及 `tiptap_body.inline_attachments` 元数据中出现，编辑器的 `file` 节点本身只有 `signed_id`。不要因节点不含文件名反复上传。
- 在描述末尾追加附件，核对无重复、原文与设置未变。文件名能说明内容时无需额外引导段落；不得删除无关附件。
- 上传观测链路为 `POST /internal_api/direct_uploads`、`POST /s3/multipart` 与 `POST /s3/multipart/<upload-id>/complete`；保存为目标单例 `PATCH /internal_api/spaces/<space-id>/events/<slug>`。仅在本次获授权的浏览器操作中放行实际需要的请求；能取得本次 `<upload-id>` 时使用精确 complete 路径。
- 拦截 multipart complete 会让极小 TXT 也显示 `Upload failed`。检查被拦请求再恢复，不开放 `/internal_api/*`、所有写方法或删除路由。`RouteGuard` 对其他 host 的上传不设限，不应据此宣称阻止了全部出站流量。
- 保留私有诊断日志，在 `finally` 中用 `ctx.unroute('**/*', guard.handle)` 卸下本次 guard；这会移除整个守卫，不只是写放行。若 agent 继续复用会话进行自动化，先安装空 allowlist 的默认 `RouteGuard`；若本次自动化已结束则断开控制。`RouteGuard` 实例本身不可调用。
- 文件节点就绪后，**当次明确授权修改已发布活动**才点击 `Save` 更新描述。这不是创建草稿或发布新活动的授权，不点 `Publish` 或 `Share via broadcast`。

## 5. 保存后回读与媒体核验

- **先读后判，不盲目重发**：HTTP 200、未捕获某条 toast 或超时，都不能单独证明成功或失败。Save 可能已经执行时先回读真实状态，不为追求某条 toast 字符串再次保存。
- **正文与附件**：重新打开目标活动，核对只有预期附件新增，原正文前缀与备份一致。只可忽略服务端 `circle_ios_fallback_text` 注解及两项已知空值等价：省略 `orderedList.attrs.type=null`、增加 `link.attrs.title=null`。其余属性与正文差异不能统一忽略。
- **设置与媒体**：比对活动可见性、RSVP、通知、回放标识、字幕和章节 URL 等。仅排除本次观测到随读取更新的 `recording_attributes.preview_thumbnails_url` 与 `recording_attributes.video_variants.hls` 短期签名 URL；不要整体跳过媒体或活动设置。
- **重新下载**：从保存后页面的附件卡或其下载 URL 下载，字节数与 SHA-256 必须等于本地已核验共享文件；仅凭 UI 文件名、`is_downloadable` 或保存响应不能结案。
- **私有留证**：现场截图、网络载荷、私人文件名、上传 ID、邮件与校验记录留在 gitignored 私有目录。公开示例只用 `community.example.com`、`<room-id>`、`<slug>` 等占位符。

媒体操作详见 [recording_posts.md](./recording_posts.md)：先滚动正确视频再 hover，将 seek 限于 `Customize media` 预览；SRT 须转 WebVTT 并转义 cue 文本，核对转换前后条数与时间。超过一小时的 Add at 可显示累计分钟（如 `82:30`），比对时解析为秒。保存后刷新并逐条核对字幕和章节文本、时间；轨道 `mode=disabled` 时先设为 `hidden` 再读 cues，`selected_file=user` 本身不足以证明字幕已生效。审阅报告如实说明核查范围，不为听不清的词编造确定答案。

## 完成度验收

- 原活动与直播间、回放身份已核对；没有误建新帖。
- ZIP/CSV 私有原件未变，行数与 hash 已记录；若做 JSON 对账，分页和回复均完整，重复发言没有丢失。
- 共享稿仅含获批字段，邮箱扫描通过，时区明确，消息与回复关系无遗漏。
- 附件通过当次授权的可见 UI 保存；原正文及非目标设置与备份一致，临时路由已清理。
- 线上重新下载的字节数和 SHA-256 与本地共享稿相同；私有留证未进入公开仓库。
