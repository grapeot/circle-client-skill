# Circle Client Skill PRD

## 问题

Circle 普通成员可能积累大量未读通知，但 Circle Admin API 和官方 MCP 面向社区管理，Headless API 又要求更高套餐和应用级认证。用户需要一个不依赖管理员权限的本地工具，把自己在 Circle 网页中已经能看到的通知导出成适合阅读和 AI 后处理的结构化文件。

同样的问题也出现在帖子和聊天操作上：发帖、改帖、删帖、回复和发聊天消息都依赖 Admin API token，而 Admin token 权限过大、误操作风险高。普通成员在浏览器里已经能做这些操作，internal API 的鉴权只靠 cookie + CSRF，不需要 Admin 身份。用 member session 替代 Admin token 可以把破坏面降到最小。

## 用户与场景

- 已经能在浏览器正常登录任意 Circle community 的普通成员。
- 想批量阅读、归档或交给 AI 筛选通知的人。
- 不希望向 AI 对话或云端服务长期提交 Circle session 凭证的人。
- 想发帖、改帖、删帖、回复帖子或发聊天消息但不想用 Admin API token 的人。

## V0 目标

- 从浏览器 Copy as cURL 安全导入通知请求，不执行 cURL 文本。
- 把必要的临时认证字段写入 gitignored `.env`。
- 按页抓取指定 notification group 的全部通知。
- 只把 `read_at = null` 的未读通知写入 artifact；已读通知不进入任何输出或可视化。
- 默认在连续 100 条已读记录后停止扫描，避免为了极旧的孤立状态遍历整个历史库。
- 支持调整 `per_page`，默认尝试 100。
- 保存完整 JSON artifact，避免 render 丢失未来筛选需要的字段。
- 把 JSON artifact 渲染为 Markdown 表格或 CSV。
- 查询当前 new notification badge count；它与全部 unread 数量是两个独立口径。
- 通过 dry-run-first、精确确认的命令重置 new notification badge count。
- 把通知按 lesson comments、普通 comments、likes、new members 和 other 分类，生成 mobile-friendly 静态 HTML。
- CLI 输出稳定的机器可读摘要，不打印通知正文或凭证。
- 默认输出紧凑纯文本（表格/卡片），`--json` flag 输出完整原始 API 响应供下游 pipeline 消费。

## V1 目标：帖子、聊天与图片

- 列出社区所有可见 space 及其 metadata。
- 列出指定 space 下的帖子（分页）。
- 获取单个帖子的完整内容（按 slug）。
- 创建帖子：提交 title + TipTap JSON body，dry-run-first。
- 更新帖子：PATCH 已有帖子的 title/body，dry-run-first。
- 删除帖子：DELETE 按 slug，dry-run-first。
- 回复帖子：POST comment 到 `/internal_api/posts/{id}/comments`，dry-run-first。
- 上传图片：两步直传（create blob + PUT to S3），dry-run-first。
- 列出聊天室消息（分页）。
- 获取单个 space 的完整 metadata（含 chat room UUID），供 chat 操作使用。
- 查找目标成员未参与的 chat root 消息（unreplied），用于社区运营回复追踪。
- 发送聊天消息：POST 到 `/internal_api/chat_rooms/{uuid}/messages`，dry-run-first。
- 聊天 thread 回复：在 send message 请求中带 `parent_message_id`，已验证消息进入 thread 视图。
- 读取 thread 回复：GET `/internal_api/chat_rooms/{uuid}/messages?parent_message_id={id}` 返回 thread 内的全部回复。
- 所有 mutation 默认 dry-run，live 执行需要 `--execute --confirm <ACTION>` 且用户当次明确授权。
- 读操作和 mutation 的错误信息透传 HTTP status code 和 response body 片段，不封装成笼统的 "something went wrong"。

## 后续目标

- 把所有未读通知标记为已读。

Mark-all-read 必须来自新的真实浏览器请求。不能因为 reset-count 的内部路径名包含 `mark_all_as_read` 就推断两者语义相同。

## 非目标

- 不替代 Circle Admin API、Headless API 或官方 MCP。
- 不管理成员、space 设置、课程或 community 设置（space 读取可以，但不在 CLI 里做 space 创建/删除/配置）。
- 不在 CLI 内实现 AI filter；AI 直接读取 JSON、Markdown 或 CSV artifact 后按任务筛选。
- 不保证 Circle internal API 长期稳定。
- 不承诺永久保存浏览器凭证；过期后重新导入是正常工作流。
- 不做 Markdown → TipTap JSON 的转换（那是 circle_post 的职责）；本 CLI 的 create/update-post 接受已有的 TipTap JSON 或简单纯文本 body。

## 成功标准

- Synthetic cURL 能离线导入，并只产生最小 `.env` 字段。
- 分页 fixture 能完整抓取，重复页不会导致无限循环。
- Markdown 与 CSV 输出保留通知 ID、状态、时间、类型、actor、摘要和链接。
- Live GET 能用用户当前浏览器凭证抓取 inbox，且 `per_page=100` 的实际行为有记录。
- 默认测试不访问 Circle，也不需要真实凭证。
- CLI 输出格式器（formatters.py）有独立离线单测，覆盖空列表、长字段截断和 tiptap 纯文本提取。
- 帖子/聊天/图片的 offline test 覆盖所有 endpoint 的 method、URL、payload schema 和错误处理。
- Live mutation 的 dry-run 不加载 `.env`、不碰网络；live 执行前必须有 dry-run preflight。
- Mutation 的错误信息包含 HTTP status code 和 response body 片段。
