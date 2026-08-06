# CLI 输出设计：默认人类/AI 友好，`--json` 完整原始

## 问题陈述

当前所有 CLI 子命令统一 `json.dumps(..., indent=2)` 输出。这带来三层摩擦：

1. **信封噪声**：业务内容被包在 `{"success": true, "count": N, "page": 1, "per_page": 24, "has_next_page": false, "posts": [...]}` 里。AI 和人类都要先在元字段里翻找真正关心的部分。
2. **完整记录成本**：`list-posts` 默认输出 id/name/slug/published_at/community_member_id 的子集 JSON，但 `spaces`、`list-chat-messages` 仍输出完整或近完整记录。各命令的"默认精简"标准不一致。
3. **两步渲染割裂**：`render` 命令已经证明项目认可"派生视图"（MD/CSV/HTML），但它只服务 notifications，且必须先 `fetch` 落盘再 render。即时性命令（spaces、list-posts、count）没有同等的派生视图。

成功标准：默认输出让 AI agent 和人类都能一眼读到业务内容、字段稳定可 grep、token 效率高于 JSON；`--json` 一键切回完整无损原始响应，供下游 pipeline 使用；不破坏现有安全边界、dry-run 契约和 `render` 命令。

## 设计原则

**默认 = 紧凑可读文本**，**`--json` = 完整原始 API 响应**。具体形态按命令类型分流：

| 命令类型 | 默认形态 | `--json` 形态 |
|---|---|---|
| 列表（spaces, list-posts, list-chat-messages, list-chat-replies） | 对齐表格，关键列 | 完整 API 响应（含 records 原始对象） |
| 单条详情（get-post） | 结构化卡片（标题行 + key: value 块 + body 纯文本） | 完整 post 原始对象 |
| 状态/计数（count, auth-status） | 一行或两行简洁 | 当前 JSON |
| Fetch（落盘类） | 人类可读 summary 到 stdout，文件仍写完整 JSON | 当前 JSON summary |
| Mutation dry-run preflight | "DRY-RUN: ..." 块 + 关键参数 + 执行提示 | 当前 preflight JSON |
| Mutation live 结果 | 一行确认 + 资源标识 | 当前 JSON |
| 错误（stderr） | 人类可读一行 + status/request_id | 当前 JSON |

六条不变量：

1. `--json` 是**全局 flag**，挂在主 parser 上，所有子命令继承；不带 `--json` 时走默认文本格式器。
2. `--json` 输出**完整原始 API 响应**（client 方法返回值的原始结构），不做字段裁剪。这是给下游 pipeline 的无损通道。
3. 默认输出**字段稳定、行式或表格式**，AI 可靠正则/行解析，人类可 grep。不输出"信封"元字段（success/count/page 等），除非它本身就是业务内容（如 `count` 的数字）。
4. 现有细化 flag 保留：`list-posts --full`、`get-post --extract-text`。在非 JSON 模式下它们控制默认表格/卡片的列与 body 展示；JSON 模式下 `--full` 仍控制是否含完整 records（向后兼容）。
5. `render` 命令**不动**：它本来就是"保存到文件供后续用"的工具，不是即时输出。新设计是"即时输出"的默认视图，两者职责不重叠。
6. 错误也走同一 flag：默认 stderr 人类可读一行，`--json` 时 stderr JSON（保留 `success/error/error_type/status_code` 结构，供程序化退出码判断）。

## 每命令默认输出示例

### `spaces`

默认（表格）：

```
ID        NAME                          SLUG                    TYPE   POSTS  MEMBERS  GROUP                       VIS
1420182   Test posts                    test-posts              basic  12     30       Test Group                  open
1349332   社区客服                       customer-service        chat   0      30       公共区·市政厅                open
1391815   Q&A                           q-a                     chat   0      4737     会员区·俱乐部               priv
2413136   Knowledge Bank - English       ai-resources-en         basic  50     4499     Superlinear AI (English)    open
```

列：ID, NAME（截断到 30 char）, SLUG, TYPE（post_type 前 5 char）, POSTS（posts_count）, MEMBERS（space_members_count）, GROUP（space_group_name 截断到 25 char）, VIS（visibility: open/priv/hidden 三态）。

`--json`：当前 `{"success": true, "count": N, "spaces": [...]}` 完整结构。

### `list-posts`

默认（表格）：

```
ID         NAME                          SLUG                    PUBLISHED_AT           REPLIES  LIKES
12345      Build with AI intro           build-with-ai-intro     2026-01-01 00:00 UTC  3        12
12346      Context engineering basics    context-engineering     2026-01-03 12:30 UTC  0        5
```

`--full` 在默认模式下展开 AUTHOR_ID、TOPICS、BODY_PREVIEW（前 80 char 纯文本）三列；在 JSON 模式下展开完整 records（当前行为）。

`--json`：当前完整结构（`--full` 控制是否完整 records）。

### `get-post`

默认（卡片）：

```
# Build with AI intro  (id=12345)
space: AI Architect (1420182)   slug: build-with-ai-intro
published: 2026-01-01T00:00:00Z   author_id: 21622670
replies: 3   likes: 12

---
Welcome to the Forge. In our first course, Build with AI, you learned
the mindset and habits required to exist in the age of Artificial
Intelligence. You learned how to use the tools. Now, it is time to
master them.
---
```

body 默认从 tiptap 提取纯文本（等价当前 `--extract-text`）；`--raw-body` 反向 flag 保留原始 tiptap JSON 块（仅非 JSON 模式）。`--json` 输出完整原始 post 对象。

### `list-chat-messages`

默认（表格）：

```
ID         CREATED_AT             AUTHOR_ID     REPLIES  BODY_PREVIEW
90123      2026-01-01 00:00 UTC   21622670      3        Hello everyone, I have a question about...
90124      2026-01-01 00:05 UTC   1133006966    0        Same here, following
```

`--json`：当前精简 JSON 升级为完整 records（统一原则：JSON 模式 = 无损）。

### `list-chat-replies`

默认：同 `list-chat-messages` 表格。`--json`：完整 reply records。

### `count`

默认：`5`（纯数字，最 pipe 友好）。

`--json`：`{"success": true, "count": 5}`。

### `auth-status`

默认：

```
configured: yes   host: www.superlinear.academy
cookie: yes   csrf: yes   jwt: no
```

`--json`：当前完整 JSON。

### `fetch`

默认（stdout summary，文件仍写完整 JSON）：

```
Fetched 123 unread notifications from www.superlinear.academy
pages: 2   per_page: 500   stop: consecutive_read_threshold
saved: data/notifications.json
```

`--json`：当前 JSON summary。

### `reset-count` 及所有 mutation dry-run

默认：

```
DRY-RUN: reset-count
  url: https://www.superlinear.academy/internal_api/notifications/mark_all_as_read
  csrf: present   cookie: present
Run with --execute --confirm RESET-COUNT to perform.
```

`--json`：当前 preflight JSON。

### mutation live 结果

默认（一行确认）：

```
OK: reset-count executed (HTTP 200)
OK: created post #12345 "Test" in space 1420182
OK: replied to post 12345 (comment id=67890)
OK: sent chat message (creation_uuid=abc-123) to room 65e2669a-...
OK: uploaded image signed_id=xyz987 -> https://...
```

`--json`：当前完整结果 JSON。

### 错误

默认（stderr）：

```
Error: Circle returned HTTP 401 [request_id=a26f8b665fa8e2d7-SEA]
  You cannot perform this action.
```

`--json`（stderr）：

```
{"success": false, "error": "Circle returned HTTP 401; ...", "error_type": "CircleClientError", "status_code": 401}
```

## 实现路径

新增 `src/circle_client_skill/formatters.py`，承载所有默认文本格式器。每个 `cmd_*` 函数改成：

```python
def cmd_spaces(args):
    settings = load_settings(Path(args.env_file))
    result = CircleClient(settings, timeout=args.timeout).list_spaces()
    spaces = result.get("records", result) if isinstance(result, dict) else result
    if args.json:
        print(json.dumps({"success": True, "count": len(spaces), "spaces": spaces}, ensure_ascii=False, indent=2))
        return
    print(format_spaces_table(spaces))
```

主 parser 加全局 `--json` flag：

```python
parser.add_argument("--json", action="store_true", help="Output complete raw JSON instead of compact human/AI-friendly text")
```

`main()` 的错误处理分叉：

```python
except (...) as exc:
    if args.json:
        payload = {"success": False, ...}
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    else:
        print(f"Error: {exc}", file=sys.stderr)
        if isinstance(exc, CircleClientError) and exc.status_code:
            print(f"  (HTTP {exc.status_code})", file=sys.stderr)
    raise SystemExit(1) from exc
```

迁移影响清单：

- 现有依赖 JSON stdout 的脚本（workspace 里目前只有 AI agent 直接读，无 shell pipeline 依赖）需要加 `--json`。
- `render`、`serve`、`configure`、`configure-browser` 不受影响（它们的输出本质是元信息，保留 JSON 或转人类可读都可，低优先级）。
- 测试：现有 `tests/` 走 client 层不涉及 CLI stdout，不受影响；新增 CLI 层 formatter 单测。

## 取舍记录

- **为什么不默认 Markdown 表格**：MD 表格对 AI 解析友好但人类在终端里 grep 体验差（`|` 管道符噪声），且复杂字段塞不进。对齐纯文本表格两者兼顾。
- **为什么 `--json` 是原始响应而不是"完整精简 JSON"**：JSON 模式的存在意义就是无损下游通道。如果再裁剪就失去 opt-in 价值。默认模式负责"精简"，JSON 模式负责"完整"，职责清晰。
- **为什么 `get-post` 默认提取纯文本 body**：tiptap JSON 对人类不可读、对 AI 也是噪声。`--raw-body` 保留 escape hatch。
- **为什么错误也分叉**：脚本靠 exit code 判断成败已经足够；错误信息给人看。`--json` 时保留结构化错误供程序化提取 status_code。