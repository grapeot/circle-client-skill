# Working

## Changelog

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
