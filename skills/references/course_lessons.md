# 往课程（course space）里批量放 lesson

本文是把一份已有的教材（多节 Markdown、图、表、视频）搬进 Circle 课程的通用做法：建 section 和 lesson、填正文、上传媒体、给视频 lesson 加 featured media、字幕和章节，全部存成 Draft，由人通读后亲手 Publish。发帖编辑器的通用操作（开窗口、节点重建、图片宽度）见 [`browser_post_composer.md`](browser_post_composer.md)，字幕文件的生成见 [`recording_posts.md`](recording_posts.md) 第六节；这里只写课程特有的部分。

id、slug、域名都是占位符（`community.example.com`、course space `9000000`、section `9000001`、lesson `9000002`）。下文的接口、按钮文案和节点结构是 2026-10 观察到的状态，动手前用 `circle_client_skill.probe` 或可见窗口重新确认。

## 执行原则

- **先抄惯例，再动手。** 用 `course-lessons` 和 `course-lesson` 读几个现有 lesson：标题格式、正文结构、多语言怎么排、视频 lesson 的正文模板、评论开关。新内容照现有惯例排，不自创格式。
- **一律存成 Draft。** Draft lesson 学员看不到；一个 section 里全是 Draft 时，整个 section 对学员也不可见（学员视角的完成进度里不计入 Draft）。脚本在保存前确认 lesson 仍是 Draft，发现已发布就停下。Publish 由人点。
- **在 test space 或新建的 Draft 里试。** 改已发布的 lesson 和发新帖一样，需要用户对这次修改单独授权。
- **写操作要有用户授权。** 建 section、建 lesson、上传 blob、Save 都会写服务端，即使内容是 Draft。

## 1. 读课程结构（含 Draft）

成员接口 `course-lessons -s <space>` 只返回学员能看到的 section 和 lesson：空 section、全是 Draft 的 section 不在里面。管理员要看全貌用：

```
GET /internal_api/courses/<space_id>/sections        → {"records": [{id, name, lessons: [{id, name, status}]}]}
```

`status` 是 `draft` / `published`。新建的东西只有在这里能核对。

## 2. 建 section

后台入口：space 页 **Edit lessons** → Lessons tab → **Add new ▾ → Section**。**点下去就建好了，不弹对话框**，名字是 "Untitled section - N"，同时出现一个已选中的行内输入框和 ✓ / ✗ 两个按钮。✓ 保存新名字；**✗ 只是放弃改名，section 已经存在**，要删得走 section 的 Options → Delete section。

对应的请求（可以直接用 member session 调）：

```
POST /internal_api/courses/<space_id>/sections   {"course_section": {"drip_delay": 0, "lesson_order": [], "name": "..."}}
PUT  /internal_api/courses/<space_id>/sections/<section_id>   {"course_section": {"name": "..."}}
```

- **section 名最长 100 个字符**，超了返回 400 "Name is too long"。双语名字很容易超，先算长度。
- 新 section 追加在最后；调整位置在 Edit lessons 里拖动（人做，或用户授权后在可见窗口里做）。

## 3. 建 lesson

后台入口：section 下面的 **+ Add new ▾ → Lesson**，同样点下去就建好，名字 "Untitled lesson - N"，状态 Draft。对应请求：

```
POST /internal_api/courses/<space_id>/sections/<section_id>/lessons
     {"course_lesson": {"featured_media": null, "name": "<最终标题>", "rich_text_body": {}, "status": "draft"}}
```

批量建时直接用这个请求，名字一次填对，按顺序追加。把返回的 lesson id 记到本地文件里，后面的步骤都按 id 操作。lesson 名的上限没有测到（94 个字符能存），保守起见也按 100 字符以内写。

## 4. lesson 编辑器

地址：`/settings/courses/<space_id>/lessons/<lesson_id>/edit`。左栏有 Lesson status（`input[name=status]` 两个 radio，第一个是 Draft）、Thumbnail（1280×720）、Settings（Enable featured media、Enable comments、Enforce video completion、Auto advance after video）、Default tab；右边是 featured media 区、lesson 标题和正文；右上角 **Save**。改动只在点 Save 时提交。

- **改名**：点 `aria-label="Edit lesson name"` 的按钮，焦点落进一个文本输入框；`Meta+A` 后输入新名字、回车。
- **正文**：tiptap，和发帖编辑器一样，DOM 元素上挂着 `editor`。可用节点只有 paragraph、heading、bulletList、orderedList、blockquote、codeBlock、horizontalRule、hardBreak、image、file、embed、cta；mark 只有 link、bold、italic、strike、underline、highlight。**没有表格、没有行内代码 mark、没有公式。** 教材里的这些要先在本地转换：表格截图成图片，行内代码变普通文本，公式改写成一行文字或截图。

### 媒体：先直传，再拼节点

不需要在编辑器里逐张点 Add image。CLI 的 `upload-image`（`client.upload_image`）走 `POST /internal_api/direct_uploads` + S3 PUT，返回 `signed_id` 和 `url`（`https://assets-v2.circle.so/<key>`），任何文件类型都可以传。拿到后直接拼节点：

```json
{"type": "image", "attrs": {"url": "<url>", "signed_id": "<signed_id>", "content_type": "image/png", "width": "100%", "alignment": "left"}}
{"type": "file",  "attrs": {"signed_id": "<signed_id>"}}
```

竖图加 `"width_ratio": 0.5`。`file` 节点放 mp4 会渲染成正文里的播放器。blob 是社区级的，同一个文件可以在多个 space、多个 lesson 里复用同一个 `signed_id`；按文件内容哈希缓存，重跑时不重复上传。（这解决了 `browser_post_composer.md` 里「待验证」的那一条：至少在 lesson 编辑器里，只带 `signed_id` + `url` 的 image 节点能正常渲染、保存和显示。）

### 重建正文、保存、回读

```js
// page.evaluate(js, parts)：parts 里是 HTML 片段或上面的节点 JSON，按阅读顺序排好
(parts) => {
  const ed = [...document.querySelectorAll('.ProseMirror')].find(e => e.editor).editor;
  const end = () => ed.state.doc.content.size;
  ed.commands.setContent('');
  for (const p of parts) ed.commands.insertContentAt(end(), p);
  ed.commands.setTextSelection(1);
  return ed.getJSON().content.map(n => n.type);
}
```

- **改完正文要等两三秒再点 Save。** 页面把编辑器内容同步到表单状态有延迟；太早点 Save，请求里带的是旧正文，响应照样是 200，只有标题改了。判据：Save 的 PUT 请求体里能数到预期数量的 image 节点。
- Save 是 `PUT .../lessons/<lesson_id>`。保存后刷新页面，用 `getJSON()` 回读节点类型序列和媒体数。**Circle 会丢掉开头和结尾的空段落**，比较时去掉两端的空段落。
- 页面有未保存改动时离开会弹 "leave page?"，脚本里 `page.on('dialog', d => d.accept())`。

## 5. 视频 lesson：featured media、字幕、章节

**featured media。** 编辑页上 featured 区的 "Upload or embed media" 旁边已经有一个 `input[type=file][accept^="video/*"]`，直接对它设文件；大于 50 MB 时用 CDP `DOM.setFileInputFiles`（`browser_post_composer.md` 第 6 节）。上传过程中页面显示 "Uploading file N%"，这行字消失、featured 区出现播放器后点 Save。回读：lesson 接口的 `featured_media.duration` 等于本地视频时长。

**字幕和章节。** 和帖子一样在 **Customize media** 对话框里做（`recording_posts.md` 第六节），lesson 编辑页上有三处不同：

- **按钮只在指针悬停在播放器上时才渲染。** 先把鼠标移到播放器上，等按钮出现再点。
- **seek 要限定在对话框内部。** 编辑页自己的主播放器比对话框里的预览更宽，"页面上最宽的 video" 会选中主播放器；结果 seek 不生效，每次 **Add at** 都落在同一个时间附近（实测依次落在 00:10、00:20……）。在对话框元素里递归 shadow DOM 找 video，并且每次点 Add at 之前核对按钮上的时间。
- **删除章节有二次确认。** 章节行的 Actions 菜单只有 Rename 和 Delete；Delete 会弹 "Delete this chapter?" 对话框，要再点一次 Delete。章节时间不能编辑，写错了只能删掉重加。重跑时先删光已有章节再加，脚本就是幂等的。
- Upload a custom transcript 的 radio 是视觉隐藏的，点它的文字标签来选；保存成功的 toast 会同时出现两个节点，等待时取 `.first`。

## 6. 交付前核对

- 管理员接口里新 section 的位置、lesson 数量、每个 lesson 都是 `draft`。
- 每个 lesson：标题等于定稿，回读的节点序列和媒体数与本地清单一致。
- 视频 lesson：`featured_media.duration` 对；`video.textTracks` 读回字幕条数和章节标题（`recording_posts.md` 第六节第 5 步）。
- 用 Preview（View as student）抽看一两个 lesson：多语言分隔、表格图片、代码块、正文视频。
- 学员视角的 `course-lessons` 里看不到新 section。

然后告诉人：在哪个 space 的哪个 section、lesson 列表、哪些设置留给人决定（缩略图、评论开关、是否通知学员），由人通读后 Publish。

## 坑

| 现象 | 原因 / 对策 |
|---|---|
| 点了 Add new → Section 就多出一个 section，点 ✗ 也没删掉 | Section 和 Lesson 都是点下去就建；✗ 只放弃改名。要删走 Options → Delete。 |
| 改 section 名返回 400 | 名字最长 100 字符。 |
| `course-lessons` 里看不到刚建的 section | 成员接口不返回空的或全是 Draft 的 section。用 `GET /internal_api/courses/<space>/sections`。 |
| Save 返回 200，刷新后正文是空的或旧的 | 正文改完太快点了 Save。等两三秒，并检查 PUT 请求体。 |
| 回读比填入少一两个节点 | 首尾空段落被丢掉，正常。 |
| 教材里的表格、行内代码、公式不见了或变形 | 编辑器没有这些节点。先在本地转换（截图 / 普通文本 / 文字）。 |
| `Customize media` 按钮找不到 | 只在悬停时渲染，先 hover 播放器。 |
| 章节全挤在开头几十秒 | seek 了页面的主播放器而不是对话框预览。限定在对话框内找 video。 |
| 删章节的循环提前结束、后续操作超时 | 每次 Delete 都有确认对话框，它让 Customize media 对话框在无障碍树里变成隐藏。点确认里的 Delete 再继续。 |
| Circle 的自动转写把英文讲课识别成中文 | 上传自制 .vtt（`recording_posts.md` 第六节）。 |
