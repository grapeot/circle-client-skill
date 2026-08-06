# 测试策略

## Offline Tests

- cURL parser：正确提取必要字段；拒绝非 HTTPS、错误 endpoint、缺失 Bearer token 和跨 origin Referer。
- `.env`：特殊字符 round-trip、权限为 `0600`、不保存原始 cURL。
- Pagination：显式 `has_next_page`、页码更新、最大页数和重复页保护。
- Render：Markdown table escaping、CSV 固定列、空数据。
- CLI：错误输出不得含 Authorization 或 Cookie。
- Formatters：空列表输出表头、长字段截断、tiptap 纯文本提取（嵌套 content、缺失 text node、非 dict 节点）。
- `unreplied`：mock `scan_chat_roots` + `get_space`，验证 `thread_participants_preview` 匹配逻辑、分页遍历和 dedup。
- Chat 分页：`--cursor`（数字 id）参数传递、`--direction` previous/next 方向切换、anchor overlap 去重。

默认测试必须完全离线，不读取 `.env`，不访问 Circle。

## Live Read Validation

Live 验证只允许 GET：

```bash
circle-client auth-status
circle-client fetch --group inbox --per-page 100 --output data/live_notifications.json
circle-client render --input data/live_notifications.json --format md
```

验收时记录状态码、实际 pages/count、服务端是否接受 `per_page=100` 和字段结构；不要把通知内容或凭证写进 tracked 文档。

## Mutation Validation

`reset-count` 默认 dry-run，离线测试必须证明默认路径没有 POST。Live reset 需要 `--execute --confirm RESET-COUNT` 和用户针对当次动作的明确授权。未来 mark-all-read 必须独立建模和测试。

## 2026-07-31 验证

- Ruff lint passed。
- 13 个 offline tests passed。
- 用户授权的 live `count`、unread frontier fetch、Markdown/CSV/HTML render passed。
- Live fetch 只执行 GET；没有调用任何 reset 或 mark-as-read endpoint。
- 静态 HTML 通过本地 HTTP server 返回 `200 text/html`。
- `reset-count` dry-run 未发送 POST；用户授权的 live execute 返回 HTTP 200，执行前后 count 均为 0。
