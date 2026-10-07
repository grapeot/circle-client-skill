# 活动回放帖：惯例归纳、可见浏览器填写、字幕与章节

本文记录一次完整的「活动回放帖」工作流：先从回放空间里归纳惯例，再写正文、处理录像，然后在一个人类可见的浏览器窗口里把 Circle 的发帖编辑器填好，停在 Publish 之前交给人；帖子发布后，再给视频补双语字幕和章节（第六节）。所有 id、slug、域名、路径都是占位符（`community.example.com`、space `1111`、slug `example-recordings`）。Circle 前端随时可能改版，下文的选择器、按钮文案和节点结构只代表 2026-10 观察到的状态，动手前先用 probe 工具或在可见窗口里重新确认。

## 执行原则（先读这一节）

- **写操作（发帖、编辑帖子）不走 CLI。** 做法是开一个人类可见的浏览器窗口（不是 headless），注入已保存的 Circle 会话，由 agent 通过浏览器自动化把标题、封面、正文、视频填进编辑器，然后停住。CLI 里的 `create-post` / `update-post` 只作为底层能力保留，不用来发给真实读者看的帖子。
- **不点 Publish，也不点 Save draft。** 编辑器填好后留在原地，由人继续修改，并亲手发布。Topic 也留给人选。
- **往真实社区写数据需要用户在主会话里明确授权**，即使只是填编辑器（上传封面和视频会在服务端建 blob）。转述给 sub-agent 的授权可能被 agent 权限系统拦下，这是预期行为。
- **发布后的视频设置（字幕、章节）是对已发布帖子的修改。** 执行前要用户对这一次修改明确授权；授权后由 agent 点 Customize media 对话框里的 Save，点完立刻回读（第六节第 5 步）。
- **不要连接人正在用的浏览器。** 用 `circle-client open-browser` 开一个独立 profile、独立调试端口的 Chrome。端口已被占用、或 profile 已被另一个 Chrome 锁住时，命令会拒绝启动，而不是附着上去。人正在审核的那个窗口不能关、不能刷新、不能再注入脚本。

## 一、从空间里归纳惯例

回放帖没有统一模板，惯例要从空间里现有的帖子归纳，而不是凭印象。做法：

1. `list-posts -s <space_id> --full --per-page 50` 拿最近的帖子，`get-post --slug` 拿全文。原始 JSON 放 gitignored 的 `data/`。
2. 先读置顶的空间说明帖。它通常写明收录标准（例如「已经公开、并获得授权的活动回放」）和期望的互动方式。
3. 取最近十几帖，逐项统计：作者与人称、语言、标题形态、封面（有无、比例、风格）、视频托管方式与位置、时间戳格式、正文形态与长度、资源链接、收尾方式、有没有课程推销或优惠码。用「n/15」这样的计数写结论，区分「普遍做法」「常见但不固定」「从没出现过」。
4. Topic 是空间级的分类，CLI 读不到单帖的 topic 字段，要在网页上看空间顶部的筛选项。

## 二、回放帖的结构

一次实践里归纳出、并由用户确认的结构如下。具体社区以自己的统计为准。

- **语言与人称**：中文，作者第一人称的整理文。它是有观点的文章，不是逐字稿，也不是「摘要 + 时间戳」清单。英文活动也用中文写，在正文里注明「英文讲授」。
- **标题**：`<公开课/活动标题>｜<系列名>回放`，用全角竖线。系列名随场合变化（例如「XX 公开课回放」「XX 访谈回放」「线下活动回放」），不要写死在模板或脚本里，每次和用户确认。
- **封面**：Circle post cover 用 2.8:1，2100×750。用品牌模板出图；这个比例在 Choose cover image 的裁切框里能完整显示。
- **视频**：原生上传到帖子（tiptap `file` 节点，Circle 会自动生成转写）。放在导语之后或正文开头。不要用 Zoom 分享链接，链接会过期。
- **观看导航**：一节章节列表，每行 `MM:SS｜标题`，超过一小时写 `1:13:32｜标题`。时间戳对应的是**上传的那个视频**，不是原始录像。
- **资源链接**：课件、代码、模型、相关文章。
- **结尾**：一个具体的问题，邀请读者在评论里回答。
- **不放优惠码。** 课程入口最多一行链接。

## 三、录像里有他人发言

学员误开麦、现场提问的人都没有为公开回放授过权。处理顺序：

1. 先列出所有他人出声的片段（时间区间 + 内容摘要），和用户确认每一段是剪掉、截断、匿名化还是保留。
2. 按决定剪辑。常见做法是剪掉误开麦片段，并在问答开始处截断；正文里提到提问时只写「一位同学问」，不写名字。
3. **剪辑后章节时间戳要整体平移。** 剪掉中段的 N 秒，之后所有章节都减 N；截断处之后的章节删掉。改完用剪辑后视频的时长核对最后一个章节，并抽查几个章节点实际画面。

## 四、正文写作流水线

1. AI 起草（外部写作 agent 或主 agent）。输入是空间惯例、讲稿/课件的权威数字和剪辑后的章节表。
2. 事实核对：所有数字以课件或讲稿为准，现场口误不采用；链接逐个打开确认。
3. 作者文风改写（voice rewrite）：如果作者有文风改写模型，起草稿必须过一遍。调用方不按自己的语感回改它的输出。
4. 改写之后只做 surgical fix：事实漂移（数字、归属、方向、遗漏）必改；格式破坏（列表被拆、标题层级丢失）按原稿恢复结构，不动措辞。文风问题记录下来交给人，不自己改。
5. 用 pandoc 把定稿分成两段 HTML：视频之前的部分（part1）和之后的部分（part2）。用 `pandoc --wrap=none`，否则长段落里会插入换行。

## 五、可见浏览器填写编辑器

### 1. 打开窗口

```bash
.venv/bin/circle-client open-browser --path /c/example-recordings --port 9333 \
  --profile-dir data/visible_browser/profile
```

它会启动一个可见的 Chrome（独立 `--user-data-dir`、只监听 127.0.0.1 的 `--remote-debugging-port`），通过 CDP 注入 `.env` 里的 cookie，打开目标页后断开。Chrome 进程留着，命令输出 `cdp_endpoint`，之后的脚本都用它连接。命令本身不写任何 Circle 数据，但打开空间页时前端自己会发 `reset_unread_count` 之类的请求，这和人浏览时一样。

为什么不用 Playwright 的 `launch(headless=False)`：Playwright 拥有的浏览器会在脚本退出时关掉，人接不了手，后续脚本也连不回同一个窗口。为什么不 `connect_over_cdp` 到人日常用的 Chrome：那会把 agent 的操作混进人的会话，也可能碰到人正在编辑的页面。新版 Chrome 也只允许非默认 profile 开远程调试。

后续脚本的连接方式：

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9333")
    ctx = browser.contexts[0]
    page = next(pg for pg in ctx.pages if "community.example.com" in pg.url)
    ...
# 退出 with 只断开 CDP；不要调用 browser.close() / page.close()
```

### 2. 打开 Create post

空间页点 **New post**，弹出 "Create post" 对话框（`[role=dialog]`）。后续选择器都限定在对话框内。

- 标题：`textarea[name=name]`，用 `fill()`。
- 正文：tiptap 编辑器 `[role=dialog] .tiptap.ProseMirror`。这个 DOM 元素上挂着 `editor` 实例（`el.editor`），可以直接调用 tiptap commands。

### 3. 封面

**Add cover** 不会触发 file chooser，而是打开 "Choose cover image" 对话框，里面有独立的 `input[type=file]`（accept 含 `image/jpeg,image/png,image/gif,image/webp`）。对它 `set_input_files(<cover.png>)`，再点 **Save changes**。成功后封面区出现 Replace / Remove。

### 4. 视频

工具栏 **Attach video** 打开对话框（Upload / Embed link 两个 tab，上传上限 4096 MB），里面有 `input[type=file][accept*=video]`。

通过 `connect_over_cdp` 连接时，Playwright 的 `set_input_files` 拒绝大于 50 MB 的文件（"Cannot transfer files larger than 50Mb to a browser not co-located"）。改用 CDP 的 `DOM.setFileInputFiles` 直接传本地路径，浏览器在本机读文件：

```python
cdp = ctx.new_cdp_session(page)
root = cdp.send("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
node = cdp.send("DOM.querySelector", {
    "nodeId": root, "selector": 'input[type=file][accept*="video"]'})["nodeId"]
cdp.send("DOM.setFileInputFiles", {"nodeId": node, "files": ["/abs/path/to/video.mp4"]})
```

上传完成的判据：正文里出现 tiptap `file` 节点（`attrs.signed_id` 有值），对应的 `<video>` 元素 `src` 指向 `/rails/active_storage/blobs/...`，且 `duration` 等于本地文件时长。大文件要轮询几分钟。

### 5. 正文：用 tiptap commands 组装，不靠粘贴

合成粘贴（`ClipboardEvent('paste')` + `DataTransfer` 里放 `text/html` 和 `text/plain`）能把 pandoc HTML 正确转成标题、加粗、列表、链接。但它有三个问题：粘贴的起始 H2 落到某些光标位置会丢；在对话框里用 Meta+A / Backspace 清空不可靠；多次尝试上传会在正文里留下多余的 `file` 节点。

最稳的做法是先上传一次视频，从 `editor.getJSON()` 里取出那个 `file` 节点，然后整篇重建：

```js
// page.evaluate(js, {part1, part2})
({part1, part2}) => {
  const ed = document.querySelector('[role=dialog] .tiptap.ProseMirror').editor;
  const fileNode = ed.getJSON().content.find(n => n.type === 'file' && n.attrs?.signed_id);
  if (!fileNode) throw new Error('video not uploaded yet');
  ed.commands.setContent(part1);                                   // 清掉一切，包括多余的 file 节点
  ed.commands.insertContentAt(ed.state.doc.content.size, fileNode); // 视频
  ed.commands.insertContentAt(ed.state.doc.content.size, part2);   // 视频之后的正文
  return ed.getJSON().content.map(n => n.type + (n.attrs?.level ? n.attrs.level : ''));
}
```

最后一行回读节点顺序，确认是「导语段落 → file → H2 …」，而且只有一个 `file` 节点。

### 6. 交付前核对，然后停住

逐项回读，不凭「刚才填过」：

- 标题：`textarea[name=name]` 的 value 等于确认过的标题。
- 封面：封面区出现 Replace / Remove。
- 正文：`editor.getJSON()` 的节点顺序；所有链接的 `href`（从 DOM 里收集 `a[href]`，逐个和定稿比对）。
- 视频：只有一个 `file` 节点，`<video>` 的 `duration` 等于剪辑后视频时长。
- Topic：不选，留给人（只列出空间里可选的 Topic 供人参考）。

然后断开 CDP，告诉人窗口在哪、填了什么、还剩什么要人做（选 Topic、通读、Publish）。**不点 Publish，不点 Save draft，不关对话框。**

## 六、视频字幕与章节（帖子发布后）

视频的字幕、章节和封面帧不在发帖编辑器里，要等帖子发布后在帖子页上改。这一步是对已发布帖子的写操作：执行前需要用户对这一次修改明确授权，Save 之后立刻按第 5 步回读。

### 1. 入口：Customize media 对话框

在帖子页把鼠标移到视频上，右上角出现一个 `aria-label="Customize media"` 的按钮，点开是同名对话框，有 Edit / Analytics 两个 tab。Edit tab 里：

- **Custom thumbnail**：上传封面帧。
- **Settings**：Make downloadable、Enable transcription 两个开关。打开转写后下面有两个 radio：Auto-generated transcript（`value=ai`，旁边有 Download .vtt）和 Upload a custom transcript（`value=user`，选中后出现 Upload .vtt，对应 `input[type=file][name="transcript.user_webvtt_file"]`，`accept=.vtt`）。
- 右侧是视频预览和 **Chapters** 区。
- 底部 **Save**。保存成功会出现 toast "Video settings saved successfully"。

定位对话框用 `page.get_by_role("dialog", name="Customize media")`。不要用 `[role=dialog]`：播放器内部的 media-error-dialog 也带这个 role，会匹配到错的节点。

### 2. 为什么要自制字幕

Circle 的自动转写对英文讲座不可靠。一次实测里，它把英文讲课识别成了中文，预览里某个时间点只显示一个「不」字。中文社区里的英文讲座，应该上传自制的中英双语 WebVTT，选 Upload a custom transcript。

### 3. 自制双语字幕

`circle_client_skill.subtitles` 是一组纯离线函数，覆盖这条流水线里所有和时间轴有关的部分。翻译和纠错由 agent 做，不在代码里。

1. **取 cue。** 用会议软件导出的转写。Zoom 用 `transcript.vtt`，它带说话人、句子级时间戳，比 `cc.vtt` 准。`parse_vtt(text, speakers=True)` 把 `Name: ` 前缀拆进 `speaker` 字段。
2. **按剪辑映射时间轴。** `remap_cues(cues, cuts=[(cut_start, cut_end)], end_at=<截断点>, duration=<剪辑后视频时长>)`：开始时间落在剪掉区间里的 cue 丢掉，之后的 cue 整体前移剪掉的时长，截断点之后的 cue 丢掉，最后一条的结束时间夹到视频时长。所有参数都用原始录像的时间，`duration` 除外，用 `ffprobe` 量剪辑后的文件。
3. **纠错和翻译（agent）。** 对每条 cue 输出 `[{"zh": ..., "en": ...}, ...]`：
   - 英文只做最小 ASR 纠错：修听错的词、专名、数字，保留口语原话和口误。对照讲稿和已知的转写错误表（例如把专名听成了近音词）。
   - 长 cue 按句子边界切成每段不超过约 90 个英文字符，每段中文不超过约 28 个字。
   - 输出和 cue 一一对应，数量不能变。
4. **组装。** `build_bilingual_vtt(cues, segments)` 在每条 cue 原来的时间范围内按英文长度比例分配各段时间，相邻 cue 之间留 0.05 秒不重叠；每个 cue 两行，第一行中文，第二行英文。
5. **校验。** `validate_vtt(vtt, expected_count=..., duration=..., forbidden=[<已知错误拼写>])` 返回问题列表，空列表才算通过。它查时间单调、无负时长、无重叠、cue 数正确、没有残留的错误拼写。

```python
from pathlib import Path
from circle_client_skill.subtitles import (
    build_bilingual_vtt, parse_vtt, remap_cues, validate_vtt)

src = parse_vtt(Path("transcript.vtt").read_text(), speakers=True)
cues = remap_cues(src, cuts=[(1200.0, 1225.0)], end_at=1700.0, duration=1675.0)
# ... agent 生成 segments（list[list[{"zh","en"}]]，与 cues 一一对应）...
vtt = build_bilingual_vtt(cues, segments)
n = sum(len(s) for s in segments)
assert validate_vtt(vtt, expected_count=n, duration=1675.0, forbidden=["<misheard-term>"]) == []
Path("subtitles_zh_en.vtt").write_text(vtt)
```

中间产物（映射后的 cue、agent 输出的 segments、最终 .vtt）都放在本地素材目录或 gitignored 的 `data/`，不进仓库。

### 4. 在对话框里上传字幕、加章节

**上传字幕。** 打开 Enable transcription，选 Upload a custom transcript，对 `input[type=file][name="transcript.user_webvtt_file"]` 用 `set_input_files`。.vtt 文件很小，Playwright 直接传即可；只有超过 50 MB 才需要第五节里的 CDP `DOM.setFileInputFiles`。

**加章节。** Chapters 区第一次点 **Add chapter** 会在 00:00 生成第一行；之后的按钮文字是 **Add at MM:SS**，时间取预览视频的播放头位置。所以每加一个章节都是：把预览视频暂停并 seek 到章节时间 → 点 Add at → 在 `input[name=title]` 填标题 → 回车确认。章节标题和帖子正文里的观看导航保持一致。

预览视频在 shadow DOM 里，`document.querySelector('video')` 找不到，要递归 `shadowRoot` 查找；页面上可能有多个 video，对话框里的预览是最宽的那个：

```js
// page.evaluate(SEEK, seconds)
(s) => {
  const vs = [];
  const walk = r => r.querySelectorAll('*').forEach(e => {
    if (e.tagName === 'VIDEO') vs.push(e);
    if (e.shadowRoot) walk(e.shadowRoot);
  });
  walk(document);
  const v = vs.sort((a, b) => b.getBoundingClientRect().width - a.getBoundingClientRect().width)[0];
  v.pause();
  v.currentTime = s;
  return v.currentTime;
}
```

```python
dlg = page.get_by_role("dialog", name="Customize media")
dlg.get_by_role("button", name="Add chapter").click()   # 生成 00:00 的第一行
first = dlg.locator("input[name=title]").last
first.fill(chapters[0][1])
first.press("Enter")
for seconds, title in chapters[1:]:
    page.evaluate(SEEK, seconds)
    page.wait_for_timeout(1000)
    dlg.locator('button:has-text("Add at")').first.click()
    box = dlg.locator("input[name=title]").last
    box.fill(title)
    box.press("Enter")
```

每加一个章节，打印一下按钮上的 `Add at MM:SS`，确认 seek 生效了再继续。全部填完后核对 Chapters 区的文字，再点 Save，等 toast "Video settings saved successfully"。

### 5. 回读验证

Save 之后刷新帖子页，从页面上的 `video.textTracks` 读回（同样要递归 shadow DOM 找到 video）：

- **字幕轨**：`kind` 为 captions 的轨（实测 label 是 "Default"，language 是 en），cue 数等于上传的 cue 数。轨道 `mode` 是 disabled 时浏览器不暴露 `cues`（为 null），读之前先设成 `hidden`。
- **章节轨**：`kind` 为 chapters 的轨，cue 数和标题与章节表一致。
- **时间对齐**：seek 到几个时间点（尤其是剪辑点之后），读 `activeCues` 的文本，和原声对照。
- **截图**：看字幕渲染是不是双行、中文在上英文在下，进度条上是否出现章节分段。

一次实测：410 条字幕、10 个章节全部读回正确，剪辑点之后时间对齐。

### 6. 会话丢失

可见 Chrome 的所有窗口都被关掉后，session cookie 会丢（页面显示 Log in / Join），而这时 `connect_over_cdp` 会报 "Browser context management is not supported"。先用 `PUT http://127.0.0.1:<port>/json/new?<url>` 开一个新 tab，再连接，然后重新注入 cookie。

## 坑

| 现象 | 原因 / 对策 |
|---|---|
| Playwright 连到了人自己的 Chrome | 默认 `connect_over_cdp` 连的就是给定端口上的那个浏览器。用 `open-browser` 开独立 `--user-data-dir` + `--remote-debugging-port`，cookie 用 `probe.session.cookies_for_browser` 注入。端口和 profile 被占用时换一个，不要附着。 |
| Add cover 点了没有 file chooser | 它打开的是 "Choose cover image" 对话框，里面有自己的 `input[type=file]`；设文件后要点 Save changes。 |
| 视频 `set_input_files` 报 50 MB 限制 | 远程连接的浏览器不接受大文件传输。用 CDP `DOM.setFileInputFiles` 传本地路径。 |
| 粘贴后第一个 H2 不见了 | 合成粘贴受光标位置影响。改用 `editor.commands.setContent` / `insertContentAt`。 |
| 正文里有两三个视频 | 每次上传都插一个 `file` 节点。只保留一个 `signed_id`，用 `setContent` 整篇重建。 |
| Meta+A 清空后还有残留 | 对话框里键盘全选不可靠。同上，用 `setContent`。 |
| 段落里出现奇怪的换行 | pandoc 默认按 72 列折行。加 `--wrap=none`。 |
| 章节时间戳对不上视频 | 剪辑后没有整体平移。按剪掉的时长重算，最后一个章节用视频时长核对。 |
| 交付后人的窗口被刷新了 | 交付后不要再对那个窗口跑任何脚本；需要改动时先问人。 |
| Circle 自动字幕把英文讲座转成了中文 | 自动转写不可靠。上传自制双语 .vtt（Upload a custom transcript）。 |
| 字幕在剪辑点之后错位 | cue 没按剪辑映射。用 `remap_cues` 按剪掉区间前移、按截断点丢弃，回读时 seek 到剪辑点之后核对。 |
| 字幕一闪而过或互相重叠 | 长 cue 没切分，或切分后时间没按比例分配、相邻 cue 重叠。用 `build_bilingual_vtt` 组装，`validate_vtt` 校验。 |
| `[role=dialog]` 定位到了奇怪的节点 | 播放器内部的 media-error-dialog 也是 dialog。用 `get_by_role("dialog", name="Customize media")`。 |
| `document.querySelector('video')` 找不到预览视频 | 视频在 shadow DOM 里。递归 `shadowRoot` 查找，取最宽的那个。 |
| 章节时间不对 | Add at 取的是预览视频的播放头位置。每次先 pause 再设 `currentTime`，等一会儿，确认按钮上的 `Add at MM:SS` 是目标时间再点。 |
| `textTracks` 里 cues 是 null | 轨道 `mode` 是 disabled。先设成 `hidden` 再读。 |
| 关掉窗口后变成未登录，`connect_over_cdp` 报 "Browser context management is not supported" | 浏览器没有任何 tab 了。`PUT /json/new?<url>` 开一个 tab 再连，重新注入 cookie。 |
