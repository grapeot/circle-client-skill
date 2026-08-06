# Circle Client Skill

Circle Client Skill 是一个非官方、local-first 的 Circle 成员客户端。它通过普通成员的浏览器 session（cookie + CSRF）操作 Circle 社区——不需要 Admin API token。支持通知导出、帖子/评论/聊天/图片的完整 CRUD，所有写操作默认 dry-run。

## 安装

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e '.[dev,browser]'
python -m playwright install chromium
```

`browser` extra 安装 Playwright，用于 `configure-browser` 命令。如果你只用 `configure`（从 Copy as cURL 导入），可以省略 `browser` 和 chromium 安装。

## 配置

有两种方式导入凭证，效果相同：

### 方式一：浏览器自动导入（推荐）

```bash
circle-client configure-browser --url https://your-community.circle.so
```

会打开一个可见的浏览器窗口。登录你的 Circle 社区，登录成功后脚本自动提取 cookie 和 CSRF token，保存到 `.env`。

### 方式二：从浏览器 Copy as cURL 导入

1. 在浏览器 DevTools 的 Network 面板中打开 Circle 通知页
2. 找到返回通知 JSON 的请求，右键选择 **Copy as cURL**
3. 让 CLI 从剪贴板读取：

```bash
circle-client configure --from-clipboard
```

也可以通过标准输入：`circle-client configure --stdin`

完整 cURL 含有可复用的登录凭证。不要把它粘贴到聊天、issue、日志或 tracked 文件中。CLI 只保存后续请求需要的字段到本地 `.env`，不会保存原始 cURL。

### 检查凭证状态

```bash
circle-client auth-status
```

凭证过期后重新运行 `configure-browser` 或 `configure` 即可。

## Agent Skill

完整 CLI 命令文档位于 `skills/circle_client.md`。AI agent（Codex、Claude Code、Cursor、OpenCode 等）读取该 skill 文件即可了解所有可用命令和参数。

可以把本仓库 URL 交给 coding agent，让它先读取 `AGENTS.md` 和 skill 文件，再把 skill 加入当地的 skill discovery chain。

## 稳定性说明

本工具调用 Circle 网页使用的 internal API，而不是 Circle 官方公开 API。Circle 可能调整 endpoint、字段或认证方式；浏览器 cookies 和 Cloudflare clearance 也会过期。认证失效时，重新运行 `configure-browser` 即可。