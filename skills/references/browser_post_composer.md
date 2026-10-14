# 在可见浏览器里填好发帖编辑器（通用）

本文是所有「agent 替人把帖子填进 Circle 编辑器、停在 Publish 之前」场景的通用操作：开窗口、展开编辑器、标题、封面、正文插图与图片宽度、视频、多媒体正文组装、Topic、交付前核对。活动回放帖在此基础上的额外惯例（空间统计、他人发言处理、章节、双语字幕）见 [`recording_posts.md`](recording_posts.md)。

所有 id、slug、域名、路径都是占位符（`community.example.com`、slug `example-projects`）。Circle 前端随时可能改版，下文的选择器、按钮文案和节点结构只代表 2026-10 观察到的状态，动手前在可见窗口里重新确认。

## 执行原则

- **写操作走人类可见的浏览器，不走 CLI。** `create-post` / `update-post` 只作为底层能力保留，不用来发给真实读者看的帖子。
- **不点 Publish，也不点 Save draft。** 编辑器填好后留在原地，由人通读、修改并亲手发布。
- **往真实社区填编辑器需要用户在主会话里明确授权。** 上传图片、封面和视频都会在服务端建 blob，即使最后没有发布。
- **不要连接人正在用的浏览器。** 用 `circle-client open-browser` 开独立 profile、独立调试端口的 Chrome；端口或 profile 被占用时换一个，不要附着。
- **交付后不要再对那个窗口跑脚本。** 不关、不刷新；人要求修改时再动，动完同样回读。

## 1. 打开窗口

```bash
.venv/bin/circle-client open-browser --path /c/example-projects --port 9333 \
  --profile-dir data/visible_browser/profile
```

命令启动一个可见的 Chrome（独立 `--user-data-dir`、只监听 127.0.0.1 的 `--remote-debugging-port`），注入 `.env` 里的 cookie，打开目标页后断开，输出 `cdp_endpoint`。后续脚本这样连接：

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9333")
    page = next(pg for pg in browser.contexts[0].pages if "community.example.com" in pg.url)
    ...
# 退出 with 只断开 CDP；不要调用 browser.close() / page.close()
```

## 2. 打开编辑器并展开成全屏

空间页点 **New post**，弹出 "Create post" 对话框。**先点对话框右上角的 Full screen 按钮**（`aria-label="Full screen"`）。默认的小对话框里，正文工具栏、图片气泡菜单和下拉列表会被对话框边缘或页面其他元素挡住，点击容易落空；全屏后编辑区、工具栏和底部的 Topic 选择都完整可见，人接手时也更容易通读。

**定位对话框不要用裸的 `[role=dialog]`。** 编辑时页面上会同时出现多个 dialog：AI summary 浮层、Attach image / Attach video 对话框、播放器内部的 media-error-dialog。编辑器对话框用「包含编辑器的那个 dialog」定位：

```python
dlg = page.locator("[role=dialog]").filter(has=page.locator(".tiptap.ProseMirror"))
```

- 标题：`dlg.locator("textarea[name=name]").fill(title)`。
- 正文：tiptap 编辑器 `.tiptap.ProseMirror`，DOM 元素上挂着 `editor` 实例（`el.editor`），可以直接调用 tiptap commands。

## 3. 封面

**Add cover** 打开 "Choose cover image" 对话框，里面有独立的 `input[type=file]`。对它 `set_input_files(<cover>)`，再点 **Save changes**。成功后封面区出现 Replace / Remove。封面是否需要、用什么比例，按目标空间的惯例决定（回放帖的规格见 `recording_posts.md` 第二节）。

## 4. 正文插图

工具栏 **Add image** 不会触发系统文件选择框（`expect_file_chooser` 会超时），而是打开 "Attach image" 对话框（Upload / Find online 两个 tab）。对这个对话框里的文件输入框设文件，再点 **Save**：

```python
dlg.get_by_role("button", name="Add image").click()
att = page.locator("[role=dialog]").filter(has_text="Attach image")
att.locator("input[type=file]").first.set_input_files("/abs/path/to/figure.jpg")
att.get_by_role("button", name="Save").click()
```

成功后正文里多出一个 `image` 节点，`attrs.signed_id` 有值，`url` 为 null。

- **对话框外面原本就有一个 `accept="image/*"` 的输入框。** 对它设文件不会往正文插图。一定要先点 Add image，再对 Attach image 对话框里的输入框操作。
- **记录「文件 → 节点」的对应关系。** image 节点里没有文件名。每上传一个文件，就在上传前后各读一次 `editor.getJSON()`，记下新增节点的 `signed_id`。不要事后靠尺寸或顺序去猜。
- 图片小于 50 MB 时 `set_input_files` 直接可用；更大的文件见第 6 节的 CDP 做法。

## 5. 图片宽度：横图满宽，竖图半宽

image 节点的显示宽度由两个属性控制：

| 显示 | `width_ratio` | `alignment` |
|---|---|---|
| 满宽（默认） | `null` | `"center"` |
| 半宽 | `0.5` | `"left"` |

手机截图、竖版海报这类竖图用满宽会占掉一整屏，应该设成半宽；横图（架构图、截图、照片）保持满宽。UI 里的做法是点一下图片，在弹出的气泡菜单里选第一个选项。代码里有两种做法：

- 组装正文时（第 7 节）直接把 `width_ratio: 0.5, alignment: "left"` 写进竖图节点的 `attrs`。
- 事后修改已有节点：

```js
// page.evaluate(js, index)：index 是该节点在 doc.content 里的序号
(index) => {
  const ed = document.querySelector('[role=dialog] .tiptap.ProseMirror').editor;
  let pos = null;
  ed.state.doc.forEach((node, offset, i) => { if (i === index && node.type.name === 'image') pos = offset; });
  if (pos === null) throw new Error('image node not found');
  const ok = ed.chain().setNodeSelection(pos).updateAttributes('image', {width_ratio: 0.5, alignment: 'left'}).run();
  ed.commands.setTextSelection(ed.state.doc.content.size - 1);  // 把选区移走，避免人接手时误删选中的图片
  return ok;
}
```

改完回读每个 image 节点的 `width_ratio` / `alignment`，并看渲染宽度（`img.getBoundingClientRect().width`，半宽约为满宽的一半）。

## 6. 视频

工具栏 **Attach video** 打开对话框（Upload / Embed link 两个 tab，上传上限 4096 MB），里面有 `input[type=file][accept*=video]`。

通过 `connect_over_cdp` 连接时，Playwright 的 `set_input_files` 拒绝大于 50 MB 的文件（"Cannot transfer files larger than 50Mb to a browser not co-located"）。改用 CDP 的 `DOM.setFileInputFiles` 直接传本地路径：

```python
cdp = browser.contexts[0].new_cdp_session(page)
root = cdp.send("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
node = cdp.send("DOM.querySelector", {
    "nodeId": root, "selector": 'input[type=file][accept*="video"]'})["nodeId"]
cdp.send("DOM.setFileInputFiles", {"nodeId": node, "files": ["/abs/path/to/video.mp4"]})
```

上传完成的判据：正文里出现 tiptap `file` 节点（`attrs.signed_id` 有值），对应的 `<video>` 元素 `src` 指向 `/rails/active_storage/blobs/...`，且 `duration` 等于本地文件时长。大文件要轮询几分钟。`<video>` 可能在 shadow DOM 里，查找时递归 `shadowRoot`。

## 7. 正文组装：媒体节点与正文交替插入

合成粘贴（`ClipboardEvent('paste')`）能转出标题、加粗、列表和链接，但起始 H2 落在某些光标位置会丢，对话框里 Meta+A / Backspace 清空也不可靠，多次上传还会留下多余的媒体节点。最稳的做法：**先把所有图片和视频各上传一次，收集节点，再整篇重建。**

1. 正文 markdown 在每个图片位置切开，得到 N+1 段文字和 N 个图片名；每段转成 HTML（Python 用 `markdown-it-py` 即可；用 pandoc 时加 `--wrap=none`，否则会在段落里折行）。HTML 里不要留 `<img>`，图片一律用上传得到的节点。
2. 按第 4、6 节上传，得到「文件 → 节点」映射；竖图节点按第 5 节写好宽度属性。
3. 一次性重建：

```js
// page.evaluate(js, {htmls, names, media, video})
({htmls, names, media, video}) => {
  const ed = document.querySelector('[role=dialog] .tiptap.ProseMirror').editor;
  const end = () => ed.state.doc.content.size;
  ed.commands.setContent('');                       // 清掉一切，包括多余的媒体节点
  if (video) ed.commands.insertContentAt(0, video);  // 视频放在开头时
  htmls.forEach((html, i) => {
    ed.commands.insertContentAt(end(), html);
    if (i < names.length) ed.commands.insertContentAt(end(), media[names[i]]);
  });
  return ed.getJSON().content.map(n => n.type + (n.attrs?.level ?? ''));
}
```

最后一行回读节点顺序，确认视频、标题和每张图都在预期的位置，`file` 节点只有一个，image 节点数等于图片数。只有一段正文加一个视频时，这就退化成「前半段 → file → 后半段」。

## 8. Topic

底部的 Topic 选择是一个输入框，"Choose up to 5 topics" 是它的 placeholder，不是普通文本，`get_by_text` 找不到，要用 `get_by_placeholder`。**没选 Topic 时 Publish 按钮是灰的**（`is_enabled()` 为 False），选了至少一个才变成可点。

- 默认把 Topic 留给人选，交付时列出空间里可选的 Topic 供参考。
- 用户要求 agent 代选时：

```python
page.get_by_placeholder("Choose up to 5 topics").first.click()
print(page.get_by_role("option").all_inner_texts())   # 空间的全部可选 Topic
page.get_by_role("option", name="<topic>").first.click()
page.keyboard.press("Escape")
```

  选完回读对话框里显示的 Topic 文字，并确认 Publish 已变成可点，**但不要点它**。

## 9. 字幕不在编辑器里

发帖编辑器里没有字幕入口。视频字幕、章节和封面帧只能在帖子发布后，从帖子页视频右上角的 Customize media 对话框里改（流程见 `recording_posts.md` 第六节），这是对已发布帖子的写操作，要用户对这次修改单独授权。视频画面里已经烧录了字幕时不要再上传软字幕，否则开启后画面上会出现两行字幕。

## 10. 交付前核对，然后停住

逐项回读，不凭「刚才填过」：

- 标题：`textarea[name=name]` 的 value 等于确认过的标题。
- 封面：需要封面时，封面区出现 Replace / Remove。
- 正文：`editor.getJSON()` 的节点顺序；所有链接的 `href`（从 DOM 里收集 `a[href]`，逐个和定稿比对）。
- 图片：image 节点数等于图片数；竖图是半宽（`width_ratio: 0.5`），横图是满宽。
- 视频：只有一个 `file` 节点，`<video>` 的 `duration` 等于本地视频时长。
- Topic：留给人选，或按用户要求代选并回读；Publish 可点但没有点。
- 选区：没有停在某个媒体节点上（停在节点上时，人按一下删除键就会删掉它）。

然后断开 CDP，告诉人窗口在哪、填了什么、还剩什么要人做（选 Topic、通读、Publish）。**不点 Publish，不点 Save draft，不关对话框。**

## 直传媒体再拼节点

CLI 的 `upload-image` 把文件直传成 blob，返回 `signed_id` 和 `url`；只带这两个属性（加宽度属性）的 image 节点在课程 lesson 编辑器里已实测能正常渲染、保存和显示，做法见 [`course_lessons.md`](course_lessons.md) 第 4 节。发帖编辑器里用之前，先在 test space 确认一次。

## 坑

| 现象 | 原因 / 对策 |
|---|---|
| Playwright 连到了人自己的 Chrome | 默认 `connect_over_cdp` 连的就是给定端口上的那个浏览器。用 `open-browser` 开独立 `--user-data-dir` + `--remote-debugging-port`。端口和 profile 被占用时换一个，不要附着。 |
| 工具栏按钮、气泡菜单点不到，或点击落到了别的元素上 | 小对话框里控件被遮挡。先点 Full screen 展开编辑器。 |
| `[role=dialog]` 匹配到 AI summary 或别的浮层 | 页面上同时有多个 dialog。编辑器用 `filter(has=.tiptap.ProseMirror)`，图片对话框用 `filter(has_text="Attach image")`。 |
| Add cover 点了没有 file chooser | 它打开的是 "Choose cover image" 对话框，里面有自己的 `input[type=file]`；设文件后要点 Save changes。 |
| Add image 后 `expect_file_chooser` 超时，或设了文件正文里没出现图片 | Add image 打开的是 "Attach image" 对话框；要对对话框里的输入框设文件并点 Save。对话框外那个 `accept="image/*"` 的输入框不插正文图。 |
| 不知道哪个 image 节点对应哪个文件 | 节点里没有文件名。每次上传前后各读一次 `getJSON()`，记录新增节点的 `signed_id`。 |
| 竖图占满一整屏 | 默认满宽。竖图设 `width_ratio: 0.5, alignment: "left"`。 |
| 视频 `set_input_files` 报 50 MB 限制 | 远程连接的浏览器不接受大文件传输。用 CDP `DOM.setFileInputFiles` 传本地路径。 |
| 粘贴后第一个 H2 不见了 | 合成粘贴受光标位置影响。改用 `setContent` / `insertContentAt` 重建。 |
| 正文里有两三个视频或重复的图 | 每次上传都插一个媒体节点。收集一次节点后用 `setContent('')` 整篇重建。 |
| Meta+A 清空后还有残留 | 对话框里键盘全选不可靠。同上，用 `setContent`。 |
| 段落里出现奇怪的换行 | pandoc 默认按 72 列折行。加 `--wrap=none`，或改用 markdown-it。 |
| `get_by_text("Choose up to 5 topics")` 找不到 | 那是 placeholder。用 `get_by_placeholder`。 |
| Publish 一直是灰的 | 还没选 Topic。选至少一个后才可点。 |
| 交付后人的窗口被刷新了，或图片被误删 | 交付后不要再对那个窗口跑脚本；交付前把选区移出媒体节点。 |
| 关掉窗口后变成未登录，`connect_over_cdp` 报 "Browser context management is not supported" | 浏览器没有任何 tab 了。`PUT http://127.0.0.1:<port>/json/new?<url>` 开一个 tab 再连，重新注入 cookie。 |
