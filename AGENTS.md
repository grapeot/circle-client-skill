# Circle Client Skill

## 项目定位

这是一个面向 Circle 普通成员的非官方客户端 Skill。当前稳定范围只有：从浏览器 Copy as cURL 导入临时登录凭证、读取 new notification count、分页抓取个人未读通知，以及把抓取结果渲染为 Markdown、CSV 或响应式 HTML。

## 结构

- `src/circle_client_skill/`：CLI、认证导入、只读客户端和渲染逻辑。
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
- 默认能力保持只读。`reset-count` 必须 dry-run first，并要求用户对该次 live mutation 明确授权；mark-all-read 尚未实现。
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
