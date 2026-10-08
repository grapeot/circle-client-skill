# 在可见浏览器里回复（thread reply / chat message）

面向「对真实读者可见的回复」：lesson 讨论回复、给成员回帖、chat room 发言。目标不是让 agent 悄悄打一个 API 然后声称成功，而是让用户当场看到消息发没发出去、能点进去核对，同时这个可见窗口本身就是回读和兜底的入口。

> 本文的选择器、按钮 aria-label 和 endpoint 是 2026-10 实测所得（live capture），不是稳定公开 contract；界面改版后可能变化，动手前先重新核对。

## 为什么走浏览器而不是 CLI

- **可见性**：用户在窗口里能立刻看到发布结果，能点进 thread 看内容，不必等 agent 转述。
- **回读途径**：同一个窗口可以刷新后确认新消息在 thread 里，是 CLI 之外的独立核验。
- **兜底**：CLI 的隐藏参数（尤其 per-room 的 `chat_room_participant_id`）一旦填错，Circle 仍返回 202，CLI 打印 OK，消息却被静默丢弃。浏览器 UI 由页面自己带上正确的 participant 身份，不存在这个坑。
- **隐私**：浏览器只把内容投进社区编辑器，不要求 agent 在本地拼装 `participant_id` / `sgid` 之类的服务端签名参数。

CLI 的 `chat-send` 保留给 test space 和脚本化场景；对真实读者的回复优先走浏览器 UI。若确实用 CLI live 发送，发送后必须回读核验（见下）。

## 打开目标页面

用 `open-browser` 开一个**人类可见**的 Chrome（独立 profile、独立调试端口，不是 headless），并带上要回复的那条消息锚点：

```bash
.venv/bin/circle-client open-browser --url "https://<community>/c/<space>/sections/<sid>/lessons/<lid>#message_<root-id>"
```

`open-browser` 输出 `cdp_endpoint`（默认 `http://127.0.0.1:9333`）、`port`、`profile_dir`、`pid`、`cookie_count`。后续脚本用 `chromium.connect_over_cdp(cdp_endpoint)` 连接；退出时只 `disconnect`，**不调用 `browser.close()`**，不关闭/刷新用户正在用的窗口。

## 在浏览器里回复一条 thread（真实操作路径）

1. **点根消息展开 thread**。含目标正文的叶子节点点击后会展开该消息的回复面板。（也可以从 `action_web_url` 的 `#message_<root-id>` 锚点直接进入。）
2. **找到回复编辑器**。thread 展开后，页面底部/消息下方出现 `[contenteditable=true]` 的 tiptap 编辑器（class 含 `tiptap ProseMirror tiptap-editor`）。取 DOM 里最后一个可见的 `[contenteditable=true]` 通常就是当前回复框。
3. **输入正文**。直接 `keyboard.type`。多段文本用换行分隔。
4. **@ 某人**。在编辑器里输入 `@` 触发 mention 补全，打字筛出目标成员后从下拉里点选。补全项由服务端签发 sgid，人不需要手拼。
5. **发送**。点 `aria-label="Send message"` 的按钮（发送前可读 `disabled` 判断内容是否为空）。**只有用户明确授权时才点发送。**
6. **回读**。用 `list-chat-replies` 或 `list-chat-messages` 确认新消息 id 出现；或在窗口里刷新看 thread。

只读观察用的选择器速查：

```python
# 当前回复编辑器（可见的最后一个 contenteditable）
eds = pg.query_selector_all("[contenteditable=true]")
editor = [e for e in eds if e.is_visible()][-1]

# 发送按钮
send = pg.query_selector("button[aria-label='Send message']")
```

## 回读核验（CLI 或窗口）

判断消息是否真的落到 thread 上，只看回读结果，不看发送命令的返回值：

```bash
# thread 回复（root -> replies）
.venv/bin/circle-client list-chat-replies --room-uuid <uuid> --parent-message-id <root-id>

# room 级 feed
.venv/bin/circle-client list-chat-messages --room-uuid <uuid> --direction previous --previous-per-page 50
```

输出里出现刚发那条的新 message id 才算成功。**发送命令返回 HTTP 202 / `creation_uuid` / "OK: sent" 都不是送达证据**——participant id 用错时 Circle 一样返回 202，但消息被静默丢弃，thread 里什么都不会有。

## participant id 是 per-room 的（CLI 发送必读）

`chat_room_participant_id` 不是账号级常量，是**每个 chat room 各自一套**。同一个账号在不同 lesson 讨论 room 里的 id 不同（实测：拿另一个 room 的 id 去发，静默失败；换成本 room 的 id 才落帖）。用 CLI `chat-send` 之前，必须先从目标 room 的 participants 列表里认领自己的那一条：

```
GET /internal_api/chat_rooms/<room-uuid>/participants?page=N   # 按 community_member_id 匹配自己
```

不要把某个 room 的 id 当默认值写进脚本或 skill，也不要把这个值复制进公开文件。浏览器 UI 不需要这一步，这也是对外回复优先走浏览器的原因之一。

## 边界

- 发送是对外可见动作，**需要用户在主会话里明确授权**；授权前可以开好浏览器、填好草稿、截图给用户看。
- 不连接用户正在使用的浏览器；用 `open-browser` 的独立 profile。
- 内容里不放凭证、cookie、sgid 原文；这些不进任何公开文件。
- 交付后不对该窗口跑破坏性脚本，不关闭用户窗口。
