# Dashboard 设计：通知 one-stop shop（2026-10-15）

> 状态（2026-10-15 更新）：P0 已实现并通过离线测试 + live 验证；重要内容已收编进 `docs/prd.md`（V2 目标）与 `docs/rfc.md`（Dashboard V2 节 + endpoint 表）。本文档保留为设计依据。
> 与设计的差异/遗留：①讨论区排序由用户拍板为 room → post → post_link（lesson 讨论置顶，对齐旧 render 分组）；②「全部已读」加了二次确认步（按设计）；③首刷实测 ~35s（设计预算 <15s，原因是 51 个 context 的参与者/评论分页；增量走缓存为秒级，达标）；④post 本体反应与 ⭐ unicode 未验证（chat 反应按钮的 ⭐ 与已验证的 ❤️ 走同一 endpoint，未单独往返验证）；⑤live 清单第 3 项（react+mark-read 后 fetch 消失）未单独执行——react 与 mark_as_read→fetch-diff 两半各有独立 live 证据（2026-10-15 / 2026-09-27），组合路径由离线测试覆盖；未再消费真实通知。
> 交付物：`src/circle_client_skill/dashboard.py`、`dashboard_ui.py`、`reactions.py`，CLI `dashboard` / `react`，测试 `tests/test_dashboard.py` + `tests/test_reactions.py`。

## 1. 结论

形式 = **一个 CLI 命令拉起本地交互页面**。`circle-client dashboard` 在 127.0.0.1 起一个小服务：浏览器里是通知 triage 页面（能直接看内容和一键反应），CLI 是能力底座（新命令 `react`，沿用现有 dry-run-first 契约），skill 文档加一节指路。不做 MCP、不引前端框架。

为什么必须带本地服务而不能继续用 `file://` 打开的静态 HTML：静态页面无法带上 Circle 的 cookie 发 mutation（SameSite + CSRF 限制），现有 `render` 只能"看+跳转"。凡是页面里能点「❤️」「已读」的，都得经 localhost 服务端代理。这是一个交互面的问题，不是可视化问题。

## 2. 现状盘点（能直接复用的现成 CLI / client 能力）

| 能力 | 现状 |
|---|---|
| 抓未读通知 | `fetch`（只存 unread，lossless JSON，直接复用） |
| 通知 → 内容的 enrichment | `list_comments(post_id)`（client 层已验证）、`list-chat-messages --room-uuid` + `list-chat-replies`（course_comment 通知的 `action_inbox_path` 直接给 room uuid） |
| 标已读 | `mark-notification-read <id>`（单条 PATCH，已验证） |
| 徽标数 | `count`（GET） |
| 静态页 | `render --format html` + `serve`（保留为快速只读视图，不动） |
| 反应（emoji） | **缺**。POST 契约本次已捕获（见 §4）；CLI 无命令 |

当前 217 条未读的构成（决定 UI 分组和加载预算）：Comment 121 条聚到 **31 个 post**；ChatRoomMessage 45 条聚到 **21 个 lesson 讨论 room**；Post 39 条（36 点赞 + 3 提及）；FlaggedContent 11；Live::Room 1。聚合后真正要拉内容的只有 ~52 个 context。

## 3. 信息组织（"按一定顺序看"）

页面按「需要回应的讨论 → 纯点赞/提及 → 其他」排三个区。核心思路：**通知只是引子，上下文才是正文**。同一条讨论里的多条通知合并进同一个 context 卡片。

**区一：要回应的讨论。** 每个 post / lesson 讨论一张 context 卡（按最新活动时间倒序）：

```
┌ Space A · 某篇帖子的标题…            [打开原帖] ┐
│ Alice · 评论了你的帖子 · 3 小时前                        │
│ <评论正文，线程内按时间顺序，触发消息高亮>                     │
│ （是回复时，带父评论上下文；已有反应显示在右侧）               │
│ ❤️  👍  ⭐     ✓ 已读                                         │
└──────────────────────────────────────────────────────────────┘
```

- 线程内按时间正序读，最新未读的那条高亮；同一 context 有多条新评论时全部展开。
- 区内排序：course/lesson 讨论和帖子评论混排，按「最新未读时间」倒序；也可以按 space 再分组，实现时看默认效果拍板。
- 评论正文从 tiptap 提取纯文本（复用 `formatters._body_text` 的段落规则，mention 渲染为 `@Name`）。

**区二：点赞与提及。** 只有一个动作：已读。点赞按目标 post 折叠：「36 人赞了《一篇项目分享帖》：A、B、C 等 N 人」+「✓ 全部已读」（点一次展开确认，再点执行）。提及（comment mention / post mention）和普通评论一起进区一，因为它们可能值得回。

**区三：其他。** 成员加入（折叠）、FlaggedContent（给 moderation 链接，**不给一键已读**——没审就标已读会藏掉待审内容）、Live 链接。

## 4. Reaction 契约（已捕获 + 待验证）

已实测（从真实写请求捕获，凭证不入库）：

| 操作 | Method | Endpoint | Body | Auth |
|---|---|---|---|---|
| 加反应（chat 消息） | POST | `/internal_api/reactions` | `{"unicode":"2764-fe0f","chat_room_message":9000001}` | cookie+CSRF |

GET 侧状态已有现成来源：chat message 记录自带 `reactions: [{emoji, unicode, count, community_member_ids}]`（unicode 格式 `2764-fe0f`，POST 回显同格式）；comment 记录有 `reaction_summary` + `is_liked`。

**待验证（实现期做，每项一次 live 动作，先在测试空间对账号主人自己的消息做回读验证，不惊动真实读者）：**

1. post comment 的 target key 形态：假设 `{"unicode":…, "comment": <id>}`。验证手段：先对某条真实 comment 发一次（dashboard UI 里点一次即可），然后拉该 post 的 comments 看 `is_liked` / `reaction_summary` 是否变化。
2. post 本体作为 target（`{"post": <id>}`）和 ⭐ 的 unicode 值（`2b50`）：按需验证，区一 v1 可先只覆盖 comment/chat 两类目标。
3. 取消反应（un-react / toggle off）：endpoint 未知，v1 **只加不减**；误点了去 Circle 网页手动取消。
4. 反应是否会像 202 静默失败那样有坑（成功响应形态待确认）：dashboard 客户端必须做「反应后回读」——重拉该目标或从响应校验 reaction count，失败在 UI 上红条提示，不静默。

**渐进启用闸门**：dashboard 里反应按钮按 target 类型开/关，开关条件是「该类型的 POST 形态已被一次回读验证」。未验证的类型只显示 ✓已读 + 打开。这防止靠猜测的 payload 真出去。

## 5. 新增 CLI / 代码

```bash
# 能力命令（agent / 脚本用，继承现有 mutation 契约）
circle-client react --room-uuid <uuid> --message-id <id> --emoji heart          # dry-run: 打印 POST target + payload
circle-client react --room-uuid <uuid> --message-id <id> --emoji heart --execute --confirm REACT
circle-client react --comment <post_comment_id> ...   # 待 §4-1 验证后开放

# 交互面（人用）
circle-client dashboard            # 起 localhost 服务，自动开浏览器；Ctrl-C 停
circle-client dashboard --port 8780 --no-open
```

- `react`：`--emoji` 收语义名（heart/thumb_up/star），CLI 内映射 unicode；`--unicode` 直填绕过映射。dry-run 照现有 preflight 格式。
- client 新方法：`create_reaction(kind, target_id, unicode)` + `mark_notification_read` 已有。
- 新模块 `dashboard.py`：分组/排序/enrichment 缓存是纯函数（离线可测），HTTP 路由是薄壳。
- 端口默认 8780，避开现有 `serve` 的 8765。

## 6. 状态构建流程（server 侧）

```
GET /api/state
  → fetch 未读（1-2 个 GET）
  → 分组：post comment → post_id；chat → room uuid；like → 目标 post；others
  → enrichment，带两级缓存 + 并行：
      cache key = (kind, context_id, 该 context 最新 notifiable_id)
      未命中才拉内容；ThreadPool(6) 并发
  → 组装 dashboard state（裁到渲染所需字段），落 data/dashboard.json
```

首刷 ~52 个 context × 1-3 个请求，估 5-15s（页面显示进度）；增量刷新只拉新出现的 context，<3s。enrichment 全部是只读 GET，刷新本身不产生任何写。

## 7. 交互流程（页面动作 → server 动作）

| 页面动作 | server 做什么 | 完成语义 |
|---|---|---|
| 点 ❤️/👍/⭐ | POST reaction → 回读校验 → PATCH mark_as_read | 一击拉倒；卡片变 done 灰显 |
| 点 ✓ 已读 | PATCH mark_as_read（单条） | 卡片变 done |
| 点「全部已读」(折叠组) | 展开确认 → 逐条 PATCH（间隔小 sleep） | 组收起 |
| 点「打开」 | 纯 `<a>` 跳 Circle（要回话/回复时用） | 已读不动（页面读 ≠ read_at，见 working.md） |
| 右上「刷新」 | 重跑 §6 | 新出现内容高亮 |

每页动作一次 HTTP 请求 = 一个动作；UI 乐观置 done 后台确认，失败回滚显示并红条。所有动作追加写 gitignored `data/dashboard_log.jsonl`（时间、动作、目标 id）作审计。

## 8. 安全与边界（proportional，不叠沙箱）

- 服务只绑 127.0.0.1（不提供 0.0.0.0 选项）；校验请求 Origin 必须是 dashboard 自身 origin，JSON Content-Type 必填——其他网站的 form post 打不进来。
- 响应永不包含 cookie/CSRF/凭证；错误信息按现有 masking 规则。
- **dashboard 的每次点击就是用户本人的一次明确授权动作**（对应「人亲手点 Publish」原则在本地 UI 的延伸），server 不自动、不批量、不排队。CLI 的 `react` 命令仍走 dry-run + `--execute --confirm REACT` 两步，这是给 agent 用的路径，契约不变。
- 保留既有边界：不 delete（包括不 un-react）、无 mark-all-read 端点滥用、对真实读者的回复仍走可见浏览器（dashboard 只做「打开」，不做输入框发消息）。

## 9. 测试计划

离线（`pytest -q` 全绿为准，不联网）：
- `test_dashboard.py`：分组与 dedupe（同消息的 course_comment/comment_mention 折叠进同一 context）、线程排序、context 缓存失效、react 的 notification→target 映射（含 notification 不够格反应时返回 4xx）、路由安全（Origin 拒绝、无凭证泄漏）、日志追加。
- `test_reactions.py`：POST payload 形态与捕获 fixture 对齐（synthetic 数据）、emoji 语义名→unicode 映射、dry-run preflight / confirm token、失败透传 status。
- UI 本轮靠手动 smoke checklist（写进 `docs/test.md`）：首刷进度、刷新增量、反应回读失败显示、done 灰显。

Live 验证清单（每项一次动作、有回读、当次授权）：
1. 测试空间对账号主人自己的 chat 消息 add reaction → 回读 `reactions` count=1；顺带验证响应体形态。
2. 对一条 post comment（可先选自己的）react → 回读 `list_comments` 的 `is_liked`/`reaction_summary`（把 §4-1 的假设变成 contract）。
3. react 后 mark_as_read → 再 fetch 该通知消失。

## 10. 分期

- **P0（先做）**：`react`（chat 消息目标）+ `dashboard` 命令 + state/enrichment + 区一上下文渲染 + ❤️/✓已读 + 手动刷新。上线标准：对 217 条真实 backlog，能在一页里读完内容、点掉 80% 不用去 Circle。
- **P1**：点赞折叠组与全部已读、comment/post 反应 target 验证后开启、自动刷新（60s，默认关）、⭐ 与更多 emoji、space 分组视图。
- **不做/后议**：un-react、bookmark（comment/message 记录里有 `bookmark_id` 字段，endpoint 未探）、dashboard 内回复、MCP 暴露。

## 11. 已按默认拍板、可否决的决策

1. 点 emoji = 反应 + 标已读，一次点击（拉倒语义）。
2. 快捷 emoji 集：❤️(2764-fe0f)、👍(1f44d)、⭐(2b50)。
3. 回复不在 dashboard 里做（保留「对真实读者可见回复走可见浏览器」原则）。
4. 服务只绑 localhost；dashboard 启动时自动开浏览器（`--no-open` 关）。
5. 数据流：dashboard 自己 refresh + 落 artifact（`data/dashboard.json`），旧 `fetch/render` 工作流原样保留。