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

这里的「Save 只建草稿」指 **Create event** 对话框；编辑已发布活动的 Save 会直接更新该活动，必须有针对这次修改的明确授权。直播回放定位、邮件导出 chat/Q&A、去邮箱附件及保存后下载回读，见 [`live_replay_exports.md`](live_replay_exports.md)。不要将直播导出里的 GET 请求误当成无副作用的查询。

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

Live room / Live stream 的 Visibility 涉及直播范围与通知受众：Community（社区范围）、Event attendees（受邀或已报名的人）、Public（全社区成员可收到开播通知，未登录访客拿到链接也能进直播；活动页本身仍只对 space 成员可见）。不要把它仅当成邮件开关；具体发送仍受通知设置等条件约束。发布邮件与 RSVP 的关系见下文。

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
- 修改已发布活动的 Visibility 不会重放首次发布邮件。补发需要另外安排，不能把保存设置当成补发成功。
- **Email all space members**、**Message all space members** 或活动菜单 **Share via broadcast** 的入口不代表免付费、已经发送或相同的通知通道。先确认实际跳转与套餐：当前 Broadcasts 与 workflow 的 **Send an email** 动作属于 Email Hub，可能需要额外订阅；不要自行激活、购买、发测试信或执行群发。DM 不是 email，系统活动通知也不是 marketing broadcast。
- **只对 admin 可见的 secret/test space 不等于零通知。** 只要 space 里有非 admin 成员，在那里 Publish 一样会给他们发邮件。在 test space 里只建草稿是安全的；要测发布，先确认成员列表。

### Announcement audience, RSVP eligibility, and membership CTA (verified 2026-10-23)

These controls answer different questions; verify them separately before the human publishes:

| Control | What to verify |
| --- | --- |
| **Basic info → Visibility** | Choose the intended community-wide or attendee-only scope. A support investigation confirmed that **Event attendees** limited the initial announcement to members already RSVP'd at publication; the publisher was excluded. This can leave no recipients even with **Send email notification to space members** enabled. |
| **Advanced → Access group** | Sets who can RSVP, not a targeted announcement audience. Selecting eligible groups does not mean only those groups receive the publication email. Keep actual group IDs and community-specific policy in a private overlay. |
| **Advanced → Members without access** | Verify **Restricted access message**, **Button label**, and **Button link**. When an event is intentionally promoted to the broader community, provide an approved membership CTA, e.g. `View membership` → `https://membership.example.com/`. Read back `rsvp_restriction_message`, `rsvp_cta_text`, and `rsvp_cta_url`; verify the actual membership destination rather than guessing it. |
| Publish, confirmation, and reminder settings | Publication announces the event; confirmations and reminders serve attendees. An enabled toggle does not prove delivery or override member preferences. |

For an explicitly approved membership-discovery/upsell event, **Community** visibility plus restricted RSVP groups and an appropriate non-eligible-member CTA can express broad promotion with narrower registration eligibility. This is not a universal default: a confidential attendee-only event may need **Event attendees** instead. Community-specific defaults belong in the private overlay. Verify the space audience and notification preferences as well; do not promise every community member an email.

Visibility and RSVP eligibility are separate controls, so restricted RSVP alone does not prove that an ineligible member cannot open a direct live-stream URL under Community visibility. Report that boundary unless an authorized non-eligible-member test has established the desired access behavior. Do not substitute Public visibility or loosen unrelated restrictions just to obtain announcements.

Before publishing, read back visibility (including the corresponding `live_stream_room_setting_attributes.access_type`), RSVP group IDs, non-member RSVP, hidden location, CTA, and notification settings. In one observed Live stream form, **Community** read back as `access_type: open` and **Event attendees** as `secret`; confirm the deployed UI mapping rather than assuming that API enum applies to every event type. After publication, retain existing registrations while investigating any missing notification; duplication/migration is a separate authorized operation with its own notification consequences.

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

### Draft completion and reliable UI editing (verified 2026-10-21)

Treat an event draft as a complete handoff, not just a title and description. Unless the user explicitly narrows the task, complete and verify these fields before handing it back:

- Title, description, host, space, relevant Topic, stable descriptive slug, dates and times.
- Location type, visibility, RSVP access groups and restriction message; hiding the location from non-attendees is a separate control from RSVP eligibility. Copy access rules only from a relevant, verified precedent. Community-specific group IDs and defaults belong in a private overlay.
- Recording: inspect **Record this live** and read back `live_stream_room_setting_attributes.recording_enabled`. Automatic replay posting is a separate setting, `auto_post_recording_enabled`; do not infer it from recording being enabled.
- SEO: fill **Meta title**, **Meta description**, **Open Graph title**, **Open Graph description**, and a dedicated **Open Graph cover** (1200×630). The event cover is a different field (approximately 2.8:1); do not assume it populates the social preview. Keep visible title, event cover, SEO and Open Graph wording synchronized when the title changes. Describe the approved format rather than promising unconfirmed demos or results.
- Inspect publish notifications and reminders, report the defaults, and stop before **Publish**. A draft Save is not publication. Post-composer rules about not saving drafts should not be confused with this event-specific Save flow.

Keep the human-visible Chrome open for handoff. Use `open-browser`, connect to its returned CDP endpoint, and disconnect the automation when finished; do not close the user's working window or its browser/context. Reuse the current editor state carefully: a person may have changed Topic or other fields between tool calls. Do not discard unsaved user work by navigating or reloading without checking.

Observed UI traps and recovery:

1. **Adjacent-month dates share the same day number.** A calendar grid headed October can contain September 27 and October 27. Match the full day button `aria-label` (weekday, month, day, year), then verify the hidden date values. Never select the first button whose text is just `27`.
2. **Time segments are interdependent.** Editing the start can move the end; editing minutes can reset hours. Segment text alone is insufficient. Verify both final `input[type=time]` values after all edits, then verify saved UTC instants and the profile timezone. A tested recovery was start hours/minutes/meridiem, followed by end minutes/hours/meridiem; this is an observation, not a universal order or a reason to blindly repeat key presses.
3. **Synthetic paste can append despite Select All.** Do not repeatedly paste into an uncertain selection. When available on the visible TipTap element, use its editor transaction, ensuring it emits an update. In the observed editor, `el.editor.commands.setContent(html, true)` plus `el.editor.emit('update', {editor: el.editor, transaction: el.editor.state.tr})` updated the parent form. A bare `setContent(html)` changed the visible editor but did not persist the new body on Save. Check the deployed TipTap version's emit-update signature; assigning `innerHTML` is not an editor transaction. Before saving, assert the expected opening paragraph, appended section and links each occur exactly once; verify list structure and the final paragraph. Then independently reload the saved page and repeat those checks: a correct DOM before Save does not prove persistence. If an assertion fails, fix the local editor before Save.
4. **Hidden editor instances and dynamic IDs mislead selectors.** Scope to the active visible dialog/tab/editor. Do not hardcode generated `base-ui` IDs. An empty multiselect input is not proof that no groups are selected: chips may be sibling elements. Confirm selected labels and saved IDs. Access-group GET results are paginated in `records` with `has_next_page`.
5. **Accessible button names may include helper text.** The Open Graph upload button can include the recommended dimensions in its accessible name; exact-name matching for only “Add Open Graph image” may fail. Inspect the live DOM and use a scoped visible locator. Do not force-click through an unexplained overlay or keep retrying a stale selector.
6. **Upload preview is not completion.** After selecting a file, wait for the preview and enabled crop-modal **Save changes**. After clicking it, wait until the parent form shows the uploaded image/Change cover control, then click the event's **Save**. Saving the parent too early can leave `opengraph_image` null even though a local preview appeared. Do not re-upload blindly: inspect pending upload/form state first.
7. **Save must be verified, not assumed.** Check the matching successful PATCH response and independently re-open/read the saved draft. Verify `status: draft`, empty `published_at`, UTC start/end, title, Topic, group IDs, location, recording, one-copy description, valid links, nonempty cover and SEO/OG fields. Capture a final preview and leave Chrome available to the user. Never print cookies, CSRF fields or whole form input dumps while diagnosing.

Keep experiments bounded: after a failed selector or unexpected value, inspect the current DOM and stop repeating the same fill/paste sequence. Preserve a local baseline and an authoritative desired body so recovery cannot accumulate duplicate paragraphs. Uploads already create blobs; a “dry run” that uploads is not side-effect-free.

1. 用 `circle_client_skill.probe`（装了 route guard 的浏览器，默认可见窗口，不是 headless）在 test space 里观察表单和默认值，截图和请求日志留在 gitignored 的 `data/`。
2. 在浏览器里由人建草稿；如果用户明确授权一个浏览器 session 代为填写，也只放行 `POST .../events` 这一个 endpoint。
3. 用只读 GET 回读草稿，核对 UTC 时间、`location_type`、通知开关。
4. 由人在草稿编辑页检查 Notifications / Reminders，然后亲手点 Publish。
