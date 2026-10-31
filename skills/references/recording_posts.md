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

回放帖写成什么样，是各个社区自己的编辑决定：语言、人称、文章还是摘要、整场伴读还是挑几段、放不放课程入口，都按第一节归纳出的惯例和用户的要求来，本文不替社区做主。同一个社区里，不同活动系列也可能不一样（例如一个系列整场视频配全文整理，另一个系列整场视频只配几个精选片段的文字）。社区自己的惯例应当写在它的私有 runbook 或 overlay 里。

下面是一篇回放帖通常要决定的要素，当作检查清单，不是默认值：

- **语言、人称与文体**：谁的口吻，是有观点的文章、逐段整理，还是精选片段。
- **标题**：通常是「活动标题 + 系列名 + 回放」，系列名每次和用户确认，不要写死在模板或脚本里。
- **封面**：Circle post cover 用 2.8:1（例如 2100×750），这个比例在 Choose cover image 的裁切框里能完整显示。但空间列表卡片可能按另一个比例居中裁切（一次实测约 2:1），所以 logo、标题、人物照片都放在画面中间的安全区里，帖子页和列表页各截图看一遍。
- **视频**：原生上传到帖子（tiptap `file` 节点，Circle 会自动生成转写），放在导语之后或正文开头；不要用 Zoom 分享链接，链接会过期。活动页已有录像时，可以在编辑器里复用那份录像的 `signed_id`，不必重新上传；代价是两处共用同一份媒体设置，活动录像上的字幕和章节会带过来，在一处改字幕或章节，另一处也会变，删除任一处可能连带清掉媒体。
- **观看导航**：每行 `MM:SS｜标题`，超过一小时写 `1:13:32｜标题`。时间戳对应的是**上传的那个视频**，不是原始录像。
- **资源链接**：课件、代码、模型、相关文章。
- **结尾**：例如一个具体的问题，邀请读者在评论里回答。
- **推广内容**：放不放课程入口、优惠码，按社区惯例。

## 三、录像里有他人发言

学员误开麦、现场提问的人都没有为公开回放授过权。处理顺序：

1. 先列出所有他人出声的片段（时间区间 + 内容摘要），和用户确认每一段是剪掉、截断、匿名化还是保留。
2. 按决定剪辑。常见做法是剪掉误开麦片段，并在问答开始处截断；正文里提到提问时只写「一位同学问」，不写名字。
3. **剪辑后章节时间戳要整体平移。** 剪掉中段的 N 秒，之后所有章节都减 N；截断处之后的章节删掉。改完用剪辑后视频的时长核对最后一个章节，并抽查几个章节点实际画面。

## 四、正文写作流水线

社区或作者有自己的写作流水线时按它来。下面是一种做过的流程：

1. AI 起草（外部写作 agent 或主 agent）。输入是空间惯例、讲稿/课件的权威数字和剪辑后的章节表。
2. 事实核对：所有数字以课件或讲稿为准，现场口误不采用；链接逐个打开确认。
3. 作者文风改写（voice rewrite）：如果作者有文风改写模型，起草稿必须过一遍。调用方不按自己的语感回改它的输出。
4. 改写之后只做 surgical fix：事实漂移（数字、归属、方向、遗漏）必改；格式破坏（列表被拆、标题层级丢失）按原稿恢复结构，不动措辞。文风问题记录下来交给人，不自己改。
5. 用 pandoc 把定稿分成两段 HTML：视频之前的部分（part1）和之后的部分（part2）。用 `pandoc --wrap=none`，否则长段落里会插入换行。

## 五、可见浏览器填写编辑器

编辑器操作对所有帖子都一样，写在 [`browser_post_composer.md`](browser_post_composer.md)：开窗口、先点 Full screen 展开、对话框定位、标题、封面、正文插图与图片宽度（横图满宽、竖图半宽）、大视频用 CDP `DOM.setFileInputFiles` 上传、用 tiptap commands 重建正文、Topic、交付前核对，以及停在 Publish 之前。

回放帖在此基础上只多两点：

- 视频放在导语之后或正文开头（第二节），正文里只有一个 `file` 节点，`<video>` 的 `duration` 等于剪辑后的视频时长。
- 封面用第二节的 2.8:1 规格。

## 六、视频字幕与章节（帖子发布后）

视频的字幕、章节和封面帧不在发帖编辑器里，要等帖子发布后在帖子页上改。这一步是对已发布帖子的写操作：执行前需要用户对这一次修改明确授权，Save 之后立刻按第 5 步回读。

### 1. 入口：Customize media 对话框

先将目标视频滚动到视口内，再把鼠标移到视频上，右上角出现一个 `aria-label="Customize media"` 的按钮，点开是同名对话框，有 Edit / Analytics 两个 tab。自动回放可能就在原活动页，无需另建回放帖；定位及 chat/Q&A 导出见 [`live_replay_exports.md`](live_replay_exports.md)。Edit tab 里：

- **Custom thumbnail**：上传封面帧。
- **Settings**：Make downloadable、Enable transcription 两个开关。打开转写后下面有两个 radio：Auto-generated transcript（`value=ai`，旁边有 Download .vtt）和 Upload a custom transcript（`value=user`，选中后出现 Upload .vtt，对应 `input[type=file][name="transcript.user_webvtt_file"]`，`accept=.vtt`）。
- 右侧是视频预览和 **Chapters** 区。
- 底部 **Save**。保存成功会出现 toast "Video settings saved successfully"。

toast 文案可能变化。Save 可能已发出时，先回读设置与播放器轨道，再决定是否重试，不因等不到精确 toast 而再次保存。已有精校 SRT 时，上传前转为 WebVTT（时间戳毫秒分隔符改为 `.`、加 `WEBVTT` 头、转义 cue 文本），并验证转换前后的文本、cue 数与起止时间一致；不因转换另行翻译或润色。

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
5. **校验。** `validate_vtt(vtt, expected_count=..., duration=..., forbidden=[<已知错误拼写>])` 返回问题列表，空列表才算通过。它查时间单调、无负时长、无重叠、cue 数正确、没有残留的错误拼写，以及 cue 文本里没有未转义的 `&`、`<`、`>`。`build_bilingual_vtt` 会用 `escape_cue_text` 自动转义（"Q&A" 写成 `Q&amp;A`，播放器里仍显示 Q&A）；别的来源的 .vtt 要自己转义：Circle 的 Customize media 遇到裸 `&` 时点 Save 毫无反应，不发请求也不报错。

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

已发布帖子的视频可以直接用命令（同一个对话框，等待、seek 重试、回读都与 `lesson-media-settings` 共用）：

```bash
.venv/bin/circle-client post-media-settings --url https://community.example.com/c/example-recordings/<post-slug> \
  --vtt subtitles_zh_en.vtt --chapters chapters.txt --video-thumbnail cover.jpg --execute --confirm POST-MEDIA-SETTINGS
```

下面是它背后的手工步骤，命令失灵时按这里排查。

**上传字幕。** 打开 Enable transcription，选 Upload a custom transcript，对 `input[type=file][name="transcript.user_webvtt_file"]` 用 `set_input_files`。.vtt 文件很小，Playwright 直接传即可；只有超过 50 MB 才需要 `browser_post_composer.md` 第 6 节里的 CDP `DOM.setFileInputFiles`。

**加章节。** Chapters 区第一次点 **Add chapter** 会在 00:00 生成第一行；之后的按钮文字是 **Add at MM:SS**，时间取预览视频的播放头位置。所以每加一个章节都是：把预览视频暂停并 seek 到章节时间 → 点 Add at → 在 `input[name=title]` 填标题 → 回车确认。章节标题和帖子正文里的观看导航保持一致。

预览视频可能在 shadow DOM 里，需递归 `shadowRoot` 查找。将查找范围限定在 Customize media 对话框，避免 seek 到正文里另一个播放器；在该对话框内取最宽的 video：

```js
// dlg.evaluate(SEEK, seconds)
(dialog, s) => {
  const vs = [];
  const walk = r => r.querySelectorAll('*').forEach(e => {
    if (e.tagName === 'VIDEO') vs.push(e);
    if (e.shadowRoot) walk(e.shadowRoot);
  });
  walk(dialog);
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
    dlg.evaluate(SEEK, seconds)
    page.wait_for_timeout(1000)
    dlg.locator('button:has-text("Add at")').first.click()
    box = dlg.locator("input[name=title]").last
    box.fill(title)
    box.press("Enter")
```

每加一个章节，打印一下按钮上的 `Add at MM:SS`，确认 seek 生效了再继续。全部填完后核对 Chapters 区的文字，再点 Save，等 toast "Video settings saved successfully"。

超过一小时的 Add at 可继续用累计分钟（如 `82:30`），不能假定三段式小时格式；解析为总秒数后核对。保存后按下节回读，toast 超时不作为重复保存的理由。

### 5. 回读验证

Save 之后刷新帖子页，从页面上的 `video.textTracks` 读回（同样要递归 shadow DOM 找到 video）：

- **字幕轨**：`kind` 为 captions 的轨（实测 label 是 "Default"，language 是 en），cue 数等于上传的 cue 数。轨道 `mode` 是 disabled 时浏览器不暴露 `cues`（为 null），读之前先设成 `hidden`。
- **章节轨**：`kind` 为 chapters 的轨，cue 数和标题与章节表一致。
- **逐条对账**：全部字幕的解码后文本、起止时间与上传稿一致，章节起点和标题与章节表一致；接口的 `selected_file=user` 或一张截图不足以替代轨道回读。
- **时间对齐**：seek 到几个时间点（尤其是剪辑点之后），读 `activeCues` 的文本，和原声对照。
- **截图**：看字幕渲染是不是双行、中文在上英文在下，进度条上是否出现章节分段。

一次实测：410 条字幕、10 个章节全部读回正确，剪辑点之后时间对齐。

### 6. 会话丢失

可见 Chrome 的所有窗口都被关掉后，session cookie 会丢（页面显示 Log in / Join），而这时 `connect_over_cdp` 会报 "Browser context management is not supported"。先用 `PUT http://127.0.0.1:<port>/json/new?<url>` 开一个新 tab，再连接，然后重新注入 cookie。

## 坑

编辑器操作相关的坑（连接、遮挡、对话框定位、封面、插图、大视频、正文重建、Topic、交付后误操作）见 [`browser_post_composer.md`](browser_post_composer.md) 的坑表。这里只列回放帖特有的。

| 现象 | 原因 / 对策 |
|---|---|
| 章节时间戳对不上视频 | 剪辑后没有整体平移。按剪掉的时长重算，最后一个章节用视频时长核对。 |
| Circle 自动字幕把英文讲座转成了中文 | 自动转写不可靠。上传自制双语 .vtt（Upload a custom transcript）。 |
| 字幕在剪辑点之后错位 | cue 没按剪辑映射。用 `remap_cues` 按剪掉区间前移、按截断点丢弃，回读时 seek 到剪辑点之后核对。 |
| 字幕一闪而过或互相重叠 | 长 cue 没切分，或切分后时间没按比例分配、相邻 cue 重叠。用 `build_bilingual_vtt` 组装，`validate_vtt` 校验。 |
| `[role=dialog]` 定位到了奇怪的节点 | 播放器内部的 media-error-dialog 也是 dialog。用 `get_by_role("dialog", name="Customize media")`。 |
| `document.querySelector('video')` 找不到预览视频 | 视频在 shadow DOM 里。递归 `shadowRoot` 查找，取最宽的那个。 |
| 章节时间不对 | Add at 取的是预览视频的播放头位置。每次先 pause 再设 `currentTime`，等一会儿，确认按钮上的 `Add at MM:SS` 是目标时间再点。 |
| `textTracks` 里 cues 是 null | 轨道 `mode` 是 disabled。先设成 `hidden` 再读。 |
| 上传字幕后点 Save 毫无反应，没有请求也没有报错 | .vtt 的 cue 文本里有裸 `&`（如 "Q&A"）。转义成 `&amp;`（`<`、`>` 同理）；命令会提前拒绝这种文件。 |
| 封面在帖子页完整，在空间列表卡片里左右被裁、标题显示不全 | 列表卡片按另一个比例居中裁切。把主要元素放进画面中间的安全区，两处都截图核对。 |
| 改了回放帖视频的字幕或章节，活动页录像也跟着变了 | 帖子复用了活动录像的 `signed_id`，两处共用同一份媒体设置。改之前先确认这是想要的效果；需要两套设置就重新上传。 |
| 用脚本往已发布帖子里插入段落，点 Save 后刷新发现没保存上 | 编辑器没有把脚本插入识别成用户编辑。改用键盘输入那一段再保存；每次保存后刷新页面读回正文。 |
