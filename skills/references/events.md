# Circle 活动（event）参考

本文记录 2026-10-03 以 community admin 身份在 Circle 网页上观察到的活动创建、编辑和发布流程。所有 id、slug、域名都是占位符（`community.example.com`、space `1111`、slug `example-event`）。Circle 前端随时可能改版，下面的字段名、按钮文案和 endpoint 只代表当天观察到的状态，使用前先用 probe 工具重新确认。

## 执行原则（先读这一节）

**本 skill 里与活动相关的脚本只用于 probe：** 观察表单、记录默认值、截图、抓请求、回读已保存的状态。

- **活动的写操作（创建、编辑、发布）走浏览器 UI。** 由人在浏览器里操作，或者由用户明确授权的浏览器 session 操作，不通过 CLI 或 API 命令。本 CLI 不提供、也不计划提供 `create-event` / `update-event` / `publish-event` 一类命令。
- **Publish 永远由人亲手点。** 发布会给 space 成员发邮件，而且这一下无法撤回（见下文「发布与通知」）。
- 已有的通知类命令（`fetch`、`count`、`mark-notification-read` 等）照旧走 CLI，不受这条原则影响。
- **往真实社区的 space 写数据，必须由用户在主会话里明确授权。** 主 agent 转述给 sub-agent 的授权，可能会被 agent 的权限系统拦下，这是预期行为，不要绕过。先在 test space 里试。
- probe 脚本必须装 route guard：发往 community host 的非 GET 请求一律拦截，只有调用方显式列出的 endpoint 才放行；默认放行列表为空，也就是纯观察。`circle_client_skill.probe` 提供现成的 session、guard 和脱敏抓包，用法见 `skills/circle_client.md` 的「Probe 工具」一节。

## 创建流程：两步走

1. 在 event 类 space 里点 **New event**，弹出 "Create event" 对话框。
2. 填完点 **Save**。前端发 `POST /internal_api/spaces/<space_id>/events`，body 里的 `event.status` 写死为 `"draft"`。**Save 永远只建草稿，不会发布。**
3. 发布要进草稿的编辑页（见下文）点 **Publish**。

所以「建活动」和「发通知」是两个分开的动作。只建草稿不会给任何人发通知。

### Create event 对话框字段

| 字段 | 说明 |
|---|---|
| Cover | 可选。对话框建议 1024×366；已有活动封面大多约 2.8:1（例如 2100×750）。支持 jpg/png/gif/webp，也可以从 Unsplash 选或贴链接。上传会先建一个 blob（见「浏览即有副作用」）。 |
| Title* | 必填，`input[name=name]`。 |
| Description | tiptap 富文本编辑器（`[contenteditable=true]`）。用合成的 `ClipboardEvent('paste')` 粘贴 HTML（`DataTransfer` 里同时放 `text/html` 和 `text/plain`），段落和标题都能保留。 |
| Topics | 最多 5 个。 |
| Host | 默认是当前用户。 |
| Space | 所属 space。 |
| Custom URL | `input[name=slug]`，即活动 slug，前面显示 `<community host>/<space slug>/`。 |
| Start / End | 日期用 base-ui 日期选择器：点 `button[id^=date-input-trigger]` 打开，日期按钮在 `role=grid` 里。时间是三个分段输入：`aria-label` 分别为 `Hours`、`Minutes`、`AM or PM`。 |
| Repeat | 默认 "Does not repeat"，可选重复规则。 |
| Location* | 必填，五种类型，见下表。 |
| Hide location from non-attendees | 开关。开启后只有报名者能看到地点。 |
| Paywall / Accept payment | 默认关闭。开启后可设价格，非受邀者需付费报名。 |

Location 类型：

| UI 选项 | 观察到的额外字段 |
|---|---|
| Live room | Default view（默认 Gallery）、Visibility、Host controls（录制、入场静音、隐藏参与者列表、禁用聊天、禁用链接分享） |
| Live stream | 同上；Visibility 多一个 Public 选项 |
| URL | 一个 `placeholder="https://"` 的输入框；API 里的 `location_type` 是 `"virtual"` |
| In person | Location address*（必填） |
| To be announced | 无额外字段；API 里是 `"tbd"` |

Live room / Live stream 的 Visibility 决定开播时谁收到通知：Community（全社区成员）、Event attendees（只有受邀或已报名的人）、Public（全社区成员收到通知，未登录访客拿到链接也能进直播；活动页本身仍只对 space 成员可见）。

### 时区

表单里的时间按**当前成员资料里的时区**解释，表单本身不显示时区。保存后要核对两处：API 回读的 UTC `starts_at` / `ends_at`，以及活动页上的时区标签（例如 PST/PDT）。不要假设表单时间就是 UTC 或浏览器本地时区。

## 草稿编辑页

Save 之后打开活动页，在 **Share** 旁边的 "…" 菜单里选 **Edit event**，进入草稿编辑对话框。顶部有 **Publish** 按钮，以及六个 tab：Overview、People、Basic info、Notifications、Reminders、Advanced。

**通知开关只在这里出现，Create event 对话框里没有，而且默认全部开启：**

- Notifications tab
  - Publish：**Send email notification to space members**（默认开）
  - Confirmation：Send email notifications、Send in-app notifications（默认开）
  - Customize thank you message（默认关）
- Reminders tab
  - Send in-app reminder an hour before the event（默认开）
  - Send email reminders（默认开），默认一封，发给 Going 状态的报名者，活动前 1 小时
- Advanced tab
  - Permissions：Hide meta info、Disable comments、Disable likes、Hide from featured areas
  - Attendees：Allow non-members to RSVP、Disable RSVP、Hide attendees、Limit RSVPs、Access group
  - SEO：Meta title/description、Open Graph title/description/image（建议 1200×630，1.91:1）
- People tab：邀请成员、Auto RSVP invited members（默认关）

在编辑页点 Save 发的是 `PATCH /internal_api/spaces/<space_id>/events/<slug>`。

## 发布与通知

- 点 **Publish** 会弹确认框，提示可能发送邀请邮件。草稿状态不发任何东西。
- 「发邮件通知 space 成员」只在**发布那一刻**触发。发布后无法再次触发这封邮件；关掉开关发布、事后想补发也不行。
- 发布后要补发通知，只能用 space 层面的 **Email all space members** 或 **Message all space members**。这两个 UI 文案观察到了，但没有测试过实际效果。
- **只对 admin 可见的 secret/test space 不等于零通知。** 只要 space 里有非 admin 成员，在那里 Publish 一样会给他们发邮件。在 test space 里只建草稿是安全的；要测发布，先确认成员列表。

## 浏览即有副作用

即使只是打开页面、不点任何按钮，前端也会写一些服务端状态：

- 进入 space 时会发 `POST /internal_api/spaces/<space_id>/reset_unread_count`，清掉该 space 的未读计数。
- 在 Cover 里上传图片会发 `POST /internal_api/direct_uploads` 创建 blob，即使最后没 Save。
- 成员搜索框用的是 `POST /internal_api/search/community_members`，虽然是读操作，但方法是 POST。

所以 route guard 默认会拦下这些请求。需要它们时，调用方要显式放行对应 endpoint。

## 观察到的 endpoint

只读：

| Method | Endpoint | 说明 |
|---|---|---|
| GET | `/internal_api/spaces/<space_id>/posts?past_events=true&per_page=50` | 活动以 post 形式返回。每条记录带 `event_setting_attributes`：`starts_at`/`ends_at`（UTC）、`time_zone`、`location_type`、`send_publish_email`、`send_email_confirmation`、`send_email_reminder`、`send_in_app_notification_*`、`hide_location_from_non_attendees`、`rsvp_access_group_ids`、报名人数等 |
| GET | `/internal_api/spaces/<space_id>/events/<slug>/event_attendees?role=participant` | 报名者列表 |
| GET | `/internal_api/events/access_groups` | RSVP 可选的 access group |

写（只记录契约，本 skill 不提供对应命令）：

| Method | Endpoint | 说明 |
|---|---|---|
| POST | `/internal_api/spaces/<space_id>/events` | Create event 对话框的 Save。`{"event": {"status": "draft", "name", "slug", "space_id", "user_id", "event_type": "single", "event_setting_attributes": {...}, ...}}` |
| PATCH | `/internal_api/spaces/<space_id>/events/<slug>` | 草稿编辑页的 Save |

`location_type` 已观察到的取值：`"tbd"`（To be announced）、`"virtual"`（URL）、`"live_stream"`。其余类型的 API 取值未确认。

## 推荐做法

1. 用 `circle_client_skill.probe`（装了 route guard 的 headless 浏览器）在 test space 里观察表单和默认值，截图和请求日志留在 gitignored 的 `data/`。
2. 在浏览器里由人建草稿；如果用户明确授权一个浏览器 session 代为填写，也只放行 `POST .../events` 这一个 endpoint。
3. 用只读 GET 回读草稿，核对 UTC 时间、`location_type`、通知开关。
4. 由人在草稿编辑页检查 Notifications / Reminders，然后亲手点 Publish。
