# 往课程（course space）里批量放 lesson

本文是把一份已有的教材（多节 Markdown、图、表、视频）搬进 Circle 课程的做法：建 section 和 lesson、填正文、给视频 lesson 加 featured 视频、字幕、章节和封面，全部存成 Draft，由人通读后亲手 Publish。

分工的原则：**机械步骤交给 CLI 命令，需要判断的事留给 agent。** 命令里已经处理了下文「命令背后」一节列出的坑，并在每次保存后回读核对；agent 不需要再去摸索编辑器，要花心思的是第 1、2 步。

id、slug、域名都是占位符（`community.example.com`、course space `9000000`、section `9000001`、lesson `9000002`）。下文的接口、按钮文案和节点结构是 2026-10 观察到的状态；命令失败时，先用 `circle_client_skill.probe` 或可见窗口确认 Circle 是否改版，再改命令。

## 执行原则

- **一律存成 Draft。** Draft lesson 学员看不到；一个 section 里全是 Draft 时，整个 section 对学员也不可见（学员视角的完成进度也不计入 Draft）。浏览器命令发现 lesson 已发布就拒绝，除非加 `--allow-published`，而那需要用户对这次修改单独授权。Publish 由人点。
- **写操作要有用户授权。** 建 section、建 lesson、上传 blob、Save 都会写服务端，即使内容是 Draft。所有写命令默认 dry-run，live 要 `--execute --confirm <ACTION>`。
- **浏览器命令连 `open-browser` 开的 Chrome**（`--cdp`，默认 `http://127.0.0.1:9333`），不连人正在用的浏览器。浏览器命令需要 `browser` extra。

## 流程

### 1. 先抄惯例（agent）

```bash
.venv/bin/circle-client course-lessons -s 9000000                       # 学员看到的结构
.venv/bin/circle-client course-sections -s 9000000                      # 全部结构，含 Draft 和空 section
.venv/bin/circle-client --json course-lesson -s 9000000 --section-id <id> --lesson-id <id>
```

读三五个现有 lesson（文字 lesson 和视频 lesson 都要看），记下：lesson 标题格式（例如「中文 / English」）、多语言怎么排（并排、先后、分隔线加小标题）、视频 lesson 正文的固定模板、评论默认开不开、附加模块的命名方式。新内容照现有惯例排，不自创格式。

### 2. 把教材转成 lesson 清单（agent，写转换脚本）

每个 lesson 一个 JSON 文件：

```json
{"title": "第 1 节｜标题 / Section 1: Title",
 "items": [
   {"html": "<p>正文……</p><h2>小标题</h2>"},
   {"media": "../assets/fig1.png", "kind": "image"},
   {"media": "../assets/phone.png", "kind": "image", "portrait": true},
   {"media": "../assets/demo.mp4", "kind": "video"},
   {"html": "<p>……</p>"}]}
```

`media` 相对清单文件。`html` 只能用编辑器支持的结构：段落、标题、列表、引用、代码块（`<pre><code>`）、分隔线、链接、加粗、斜体、删除线、下划线、高亮。**编辑器没有表格、行内代码 mark 和公式**，转换时处理掉：表格截图成图片（从渲染好的 HTML 版截，中英各一份），行内代码变普通文本，公式改写成一行文字或截图。图片 alt 想保留时，在图后加一行斜体图注。竖图（手机截图）标 `portrait`，显示为半宽。

转完先在本地把清单渲染成预览页通读一遍，再碰 Circle。

### 3. 建 section 和 lesson（CLI）

```bash
.venv/bin/circle-client create-section -s 9000000 --name "附加模块 —— … / Bonus Module - …" --execute --confirm CREATE-SECTION
.venv/bin/circle-client rename-section -s 9000000 --section-id 9000001 --name "…" --execute --confirm RENAME-SECTION
.venv/bin/circle-client create-lesson -s 9000000 --section-id 9000001 --manifest out/01.json --execute --confirm CREATE-LESSON
```

section 名最长 100 个字符，命令在 dry-run 时就会检查。新 section 和新 lesson 都追加在最后；section 的位置在后台 Edit lessons 里拖动调整（由人做，或者用户授权后在可见窗口里拖）。把 `create-lesson` 返回的 lesson id 记到本地文件里，后面按 id 操作。

### 4. 填正文（CLI，可反复运行）

```bash
.venv/bin/circle-client open-browser --path /c/example-course --port 9333 --profile-dir data/visible_browser/profile
.venv/bin/circle-client fill-lesson -s 9000000 --lesson-id 9000002 --manifest out/01.json [--thumbnail cover.png] \
  --execute --confirm FILL-LESSON
```

命令依次：把清单里的媒体直传成 blob（按内容哈希缓存在 `--upload-cache`，默认 `data/course_uploads.json`；内容没变的文件不重复上传，blob 是社区级的，可以跨 space 复用）→ 打开 lesson 编辑器并确认是 Draft → 改名 → 用 `setContent` + `insertContentAt` 整篇重建正文 → 可选设置 lesson 缩略图 → 等表单同步后 Save → 刷新并回读标题和节点序列。输出 JSON 里 `title_ok`、`body_ok`、`draft` 都应为 true。每次都是整篇重建，所以改了教材就重跑；`--no-save` 只填不存，留给人在窗口里看。

### 5. 视频 lesson（CLI）

```bash
.venv/bin/circle-client lesson-featured-video -s 9000000 --lesson-id 9000002 --video intro.mp4 \
  --execute --confirm LESSON-FEATURED-VIDEO
.venv/bin/circle-client lesson-media-settings -s 9000000 --lesson-id 9000002 \
  --vtt intro_zh_en.vtt --chapters chapters.txt --video-thumbnail cover.png \
  --execute --confirm LESSON-MEDIA-SETTINGS
```

章节文件一行一个 `MM:SS 标题`（或 `H:MM:SS`），第一行必须是 `00:00`，`#` 开头的行是注释。三个参数可以分开给；给了 `--chapters` 时会先删光已有章节再按文件重加，所以重跑是安全的。命令最后从页面的 `video.textTracks` 读回字幕条数和章节标题，并给出视频的 poster 地址。

**等 featured 视频处理完再跑 `lesson-media-settings`。** 上传到 100% 之后 Circle 还要处理一段时间，这期间对话框里的预览只能 seek 到已经处理好的部分（2026-10-21 一个 100 MB、18 分钟的视频，上传完立刻跑，要 03:49 却落在 00:10，约 3 分钟后重跑成功）。命令给了 `--chapters` 时会先等预览的时长覆盖最后一个章节，每次 seek 也会重试，合计最多等 5 分钟；还不行就报错，提示几分钟后重跑。**对话框只在最后点一次 Save，中途任何一步失败都什么也没存下**，日志里已经打印的 "video thumbnail set"、"transcript attached" 也不算数，要把整步重跑，不能只补章节。字幕文件怎么做（自动转写不可靠时自制双语 WebVTT）见 [`recording_posts.md`](recording_posts.md) 第六节。字幕文本里的 `&`、`<`、`>` 必须转义，否则对话框的 Save 静默无效；命令在打开浏览器前就会检查并拒绝。把 lesson 搬成公开帖子、给已发布 lesson 顶部加指路，见 [`public_posts_migration.md`](public_posts_migration.md)。

封面图用品牌规范做成 16:9（1280×720 或其倍数）：同一张图既做 lesson 缩略图（`fill-lesson --thumbnail`，显示在课程目录里，很小）也做视频封面帧（`--video-thumbnail`，学员点播放前看到的画面）。不设视频封面时，Circle 用视频的某一帧，录屏开头往往是别的场合的标题页。

### 6. 交付前核对

- `course-sections`：新 section 的位置、lesson 数量、每个 lesson 都是 `draft`。
- 每个 `fill-lesson` 的输出都是 `saved`、`title_ok`、`body_ok`、`draft`。
- 视频 lesson：`course-lesson` 的 `featured_media.duration` 等于本地视频时长；`lesson-media-settings` 读回的字幕条数、章节标题对。
- 在后台用 Preview（View as student）抽看一两个 lesson：多语言分隔、表格图、代码块、正文视频、视频封面。
- 学员视角的 `course-lessons` 里看不到新 section。

然后告诉人：在哪个 space 的哪个 section、lesson 列表、留给人决定的事（评论开关、section 位置），由人通读后 Publish。lesson 的 Publish 流程里没有「通知学员」的选项（2026-10-21 实测一次，同一 space 已有 lesson 的 `notify_students` 都是 false），不要让人在发布时决定要不要通知。

## 命令背后：接口和编辑器行为

命令失灵时从这里查原因。

**接口（member session 的 cookie + CSRF）。**

```
GET  /internal_api/courses/<space_id>/sections                       → {"records": [{id, name, lessons: [{id, name, status}]}]}
POST /internal_api/courses/<space_id>/sections                       {"course_section": {"drip_delay": 0, "lesson_order": [], "name": "..."}}
PUT  /internal_api/courses/<space_id>/sections/<section_id>          {"course_section": {"name": "..."}}
POST /internal_api/courses/<space_id>/sections/<section_id>/lessons  {"course_lesson": {"featured_media": null, "name": "...", "rich_text_body": {}, "status": "draft"}}
PUT  /internal_api/courses/<space_id>/sections/<section_id>/lessons/<lesson_id>   ← 编辑器的 Save
POST /internal_api/direct_uploads + S3 PUT                           ← upload-image；返回 signed_id 和 url
```

成员接口（`course-lessons`，读 space 的 `course_sections`）不返回空的或全是 Draft 的 section，核对只能用第一个接口。

**后台 UI。** Edit lessons → Lessons tab → Add new ▾ → Section / Lesson：**点下去就建好，不弹对话框**。新 section 的名字出现在一个已选中的行内输入框里，带 ✓ 和 ✗：✓ 保存新名字，**✗ 只是放弃改名，section 已经存在**，要删得走 section 的 Options → Delete section。lesson 的 Options 菜单有 Edit、Unpublish、View as student、Rename、Duplicate、Delete。

**lesson 编辑器**（`/settings/courses/<space_id>/lessons/<lesson_id>/edit`）。左栏：Lesson status（`input[name=status]`，第一个 radio 是 Draft）、Thumbnail、Settings（Enable featured media、Enable comments、Enforce video completion、Auto advance after video）、Default tab。右边：featured media 区、lesson 标题、tiptap 正文；右上角 Save，改动只在 Save 时提交。

- 改名：点 `aria-label="Edit lesson name"`，焦点落进文本框，全选后输入、回车。
- 媒体节点：`{"type": "image", "attrs": {"url", "signed_id", "content_type", "width": "100%", "alignment": "left"}}`，竖图加 `"width_ratio": 0.5`；视频是 `{"type": "file", "attrs": {"signed_id"}}`，渲染成正文里的播放器。只带直传返回的 `signed_id` 和 `url` 的节点能正常渲染、保存和显示，不需要在编辑器里逐张点 Add image。
- **保存时机。** 页面把编辑器内容同步到表单状态有延迟。程序改完正文立刻点 Save，请求里带的是旧正文，响应照样是 200，只有标题改了。命令改完后等 2.5 秒，并检查 Save 请求体里的 image 节点数。
- **首尾空段落会被丢掉**，回读的节点序列比填入时少一两个是正常的，比较时去掉两端的段落。
- 页面有未保存改动时离开会弹 "leave page?"，命令自动确认。
- **缩略图。** 对 `input[type=file][name=thumbnail]` 设文件后会弹出 "Upload thumbnail" 裁剪对话框，要点 Save changes 才生效，再点页面的 Save。16:9 的图正好填满裁剪框。

**featured 视频。** 编辑页上 featured 区已经有一个 `input[type=file][accept^="video/*"]`；大于 50 MB 时 Playwright 的 `set_input_files` 在 CDP 连接下会拒绝，改用 CDP `DOM.setFileInputFiles` 传本地路径。上传中页面显示 "Uploading file N%"，这行字消失、featured 区出现播放器后再 Save。

**Customize media**（视频的字幕、章节、封面）。

- **按钮只在指针悬停在播放器上时才渲染。** 先移动鼠标到播放器上，等按钮出现再点。
- **seek 要限定在对话框内部。** 编辑页自己的主播放器比对话框里的预览更宽，"页面上最宽的 video" 会选中主播放器，结果 seek 不生效，每次 Add at 都落在同一时间附近（一次实测依次落在 00:10、00:20……）。命令在对话框元素里递归 shadow DOM 找 video，并在每次点 Add at 之前核对按钮上的时间。
- **视频还在处理时 seek 不过去。** 预览的 `duration` / `seekable` 只覆盖已处理的部分，设 `currentTime` 会被夹到那里，Add at 按钮显示的是夹住后的时间。命令在动对话框里任何东西之前先等它覆盖最后一个章节，每次 seek 失败后重新 seek，共享一个 5 分钟的等待上限。
- **删除章节有二次确认**（"Delete this chapter?"），确认对话框打开时 Customize media 在无障碍树里变成隐藏。章节行的 Actions 菜单只有 Rename 和 Delete，时间不能改，写错只能删掉重加。
- Upload a custom transcript 的 radio 是视觉隐藏的，点它的文字标签；已经挂了 .vtt 时要先在对话框里删掉旧文件。
- 视频封面：Custom thumbnail 区的 "Add image" 按钮打开 "Choose image" 对话框（Upload / Unsplash），里面有自己的文件输入框，设文件后点 Save changes。
- 保存成功的 toast "Video settings saved successfully" 会同时出现两个节点，等待时取第一个。
- Circle 的自动转写对英文讲座不可靠（实测把英文识别成中文），用自制 .vtt。

## 坑

| 现象 | 原因 / 对策 |
|---|---|
| 点了 Add new → Section 就多出一个 section，点 ✗ 也没删掉 | Section 和 Lesson 都是点下去就建；✗ 只放弃改名。要删走 Options → Delete。 |
| 改 section 名返回 400 | 名字最长 100 字符。双语名字容易超，先算长度。 |
| `course-lessons` 里看不到刚建的 section | 成员接口不返回空的或全是 Draft 的 section。用 `course-sections`。 |
| Save 返回 200，刷新后正文是旧的 | 正文改完太快点了 Save。`fill-lesson` 已经等待并检查请求体；手工操作时也要等几秒。 |
| 回读比填入少一两个节点 | 首尾空段落被丢掉，正常。 |
| 教材里的表格、行内代码、公式不见了或变形 | 编辑器没有这些节点。在清单转换阶段处理。 |
| 设了缩略图，页面的 Save 点不到 | 裁剪对话框还开着。点它的 Save changes。 |
| `Customize media` 按钮找不到 | 只在悬停时渲染。 |
| 章节全挤在开头几十秒 | seek 了页面主播放器。限定在对话框内找 video。 |
| `seek failed: button says 'Add at 00:10', wanted 03:49`，或 video still processing 的报错 | featured 视频刚上传完还在处理。几分钟后重跑整个 `lesson-media-settings`；失败时封面和字幕也没存。 |
| 删章节的循环提前结束、后续操作超时 | 每次 Delete 都有确认对话框。 |
| 视频封面点了 Add image 没有文件选择框 | 它打开的是 "Choose image" 对话框，对里面的文件输入框设文件。 |
| 视频封面是录屏开头别的场合的标题页 | 用 `--video-thumbnail` 换成模块封面。 |
| 点了 Save 没有任何反应，也没有 toast | 字幕文件里有裸 `&`、`<` 或 `>`。转义后重跑（命令现在会提前拒绝）。 |
