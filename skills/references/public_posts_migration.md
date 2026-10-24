# Moving free course lessons into a public posts space

This reference covers taking lessons out of a course space and republishing them as posts in a posts space that logged-out visitors can open. It also covers publishing new native-video posts into that space, adding captions, chapters and covers to them, and leaving a pointer in each old lesson. Everything here was observed on one community in 2026-10. Circle's internal API has no public contract, so re-check endpoints and dialogs in a visible window before relying on them.

All ids, slugs and hosts below are placeholders (`community.example.com`, `<space_id>`, `<lesson_id>`, `<post-slug>`).

## Why a posts space

**Course lessons are never open to logged-out visitors.** A course space can be listed publicly, so its table of contents shows with a lock on every lesson. But a lesson needs the visitor to join the community and enroll. When a logged-out visitor opens a lesson URL, the page returns 200, then the front end sends them to the home page and drops the query string, `utm_*` included.

**A posts space with "Show to logged out visitors" turned on works fully.** Logged-out visitors can open a post URL directly. The UTM query string stays in the address bar, a natively uploaded video plays, and comments show. The comment box offers Log in / Join, so visitors only need an account to interact.

## You cannot hand an existing slug to the new space

- A space's type is fixed when it is created. A course space cannot become a posts space.
- **Renamed space slugs are never freed.** The old slug keeps answering with a 302 to the space's current slug and drops the query string. A new space that asks for a taken slug gets a random suffix (`<slug>-1a2b3c`).
- Circle's Redirects feature only covers Website-builder pages. It cannot redirect from posts, events, courses or spaces.
- So as long as the course space exists, it keeps its slug, and old lesson URLs keep working only for logged-in, enrolled members. Pick a new slug for the posts space. Once a slug is used it stays taken, so test in a space with an obviously throwaway slug, not the real one.

## Plan

1. Create a **Secret** posts space in an admin-only space group. Turn off email, in-app and mobile new-post notifications. Do not add the space group's members. Turn on the space-level **Hide all posts from featured areas**.
2. Create one Topic per original course section, in section order, and attach them to the space.
3. Create one post per lesson (below). Add a pinned directory post that lists every post by section, then update it as more posts land.
4. Verify every post against its lesson (below).
5. **Publish moment (the human decides):** after the human has reviewed the staged posts, move the space to the public group, set access to **Open**, and keep **Show to logged out visitors** on. This stands in for the human clicking Publish. Check logged-out access in a headed, cookie-less browser (headless runs can hit the Cloudflare challenge).
6. Add a one-line pointer at the top of each old lesson (below). Do not change the course's slug, do not delete it, and do not touch its access groups.
7. Update external links to the new post URLs.

Every step writes to the community, and each one needs the user's explicit authorization for that run.

**This is an exception to the repository's rule that post writes go through the visible browser composer, with a human clicking Publish.** Creating posts through the API is allowed only when all three conditions hold:

- The user explicitly authorizes API post creation for this migration run.
- The posts land in a Secret staging space that only admins can see.
- Opening that space (step 5) is done or approved by the human after review.

Outside a migration like this, the browser composer rule applies unchanged.

The space, topic, post and lesson writes below are raw requests, not CLI commands, so the dry-run gate does not cover them. Before sending each batch, print the exact method, path and payload as a dry run. Send only after the user approves that batch.

## Space and Topic endpoints (member session, admin account)

```
POST /internal_api/spaces            {"space": {"name", "space_group_id", "post_type": "basic", "visibility": "secret",
                                                "add_members_from_space_group": false,
                                                "default_notification_setting": "never",
                                                "default_in_app_notification_setting": "never",
                                                "default_mobile_notification_setting": "never", ...}}
PUT  /internal_api/spaces/<space_id> {"space": {...the whole settings object the dialog sends...}}
POST /internal_api/settings/topics   {"topic": {"name": "...", "space_ids": [null]}}   → community-wide topic id
```

- The create dialog has no slug field. The slug comes from the name, so create the space with an ASCII name that slugifies to the slug you want (for example "Free Videos" → `free-videos`), then rename it. Renaming does not change the slug; read it back to make sure.
- The space settings dialog (Customize / Options) saves the whole object with one `PUT`. Fields: `hide_from_featured_areas`, `is_post_disabled` (members cannot post), `display_view`, `topics` (ordered ids), `space_group_id`, `visibility`. "Show to logged out visitors" is stored as `is_hidden: false`.
- Topics are community-wide objects. Creating one in the space dialog posts it with `space_ids: [null]`, and the space's `PUT` attaches it.

## One post per lesson

Read the lesson with `course-lesson`. The lesson's `rich_text_body` uses the same TipTap format as a post (`format: "post"`), so the post body is:

```json
{"body": {"type": "doc", "content": [
   {"type": "file", "attrs": {"signed_id": "<lesson featured_media.signed_id>"}},
   "...the lesson's rich_text_body.body.content, with circle_ios_fallback_text keys removed..."]},
 "inline_attachments": [], "sgids_to_object_map": {}, "format": "post"}
```

Send it as a raw `POST /internal_api/spaces/<space_id>/posts` with the same envelope as `CircleClient.create_post`. That helper hard-codes `slug: ""`, `published_at: null` and `hide_from_featured_areas: false`, so build the payload yourself and set these fields:

- `slug`: a stable, descriptive English slug.
- `topics`: `[<topic_id>]` for the lesson's section.
- `published_at`: the lesson's `created_at`. The backfill works, and `created_at` is backfilled with it, so sorting and the displayed dates follow the original course.
- `hide_from_featured_areas: true` (shown as **Hide from featured areas**: not in the Feed or the weekly digest).
- For the directory post: `pin_to_top: true` and `is_truncation_disabled: true`.

What carries over by reusing the `signed_id`:

- The video, its custom captions (`webvtt_file_url`), chapters (`/media_chapters/<signed_id>.vtt`), Circle's transcript and the custom cover frame. All of these hang off the blob, not off the lesson.
- Image nodes and file nodes (PDF cards) in the body, also by `signed_id`.
- Entity nodes that link to other lessons. Their sgids carry no expiry and render as link chips.

Read the response back. `tiptap_body.inline_attachments` should list each blob, and the video should show `media_transcoding.status: succeeded`.

**Pace the writes.** Creating posts back to back hit HTTP 429 on the third post. Sleep about 20 s between posts and back off on 429. A 429 means the post was not created; check with `get-post` before you retry.

## Shared blobs: one video, two places

The post and the lesson point at the same blob:

- Editing captions, chapters or the cover through Customize media on the post changes the lesson too, and the reverse.
- Never delete the source lesson, the course space, the staging or pilot space, or any post that reuses a blob. Whether a delete purges the shared blob was not tested, and the downside is losing the video in the other place.
- Comments do not carry over. Lesson comments live in a chat room, and there is no migration path.

## Native video posts (no source lesson)

1. Upload the file with `direct_uploads` (`CircleClient.upload_image` works for videos too; it takes the content type from the file extension and falls back to `image/png`, so use a `.mp4` / `.mov` name). 60–190 MB videos uploaded in 11–92 s. Give the client a generous timeout, because the S3 PUT is one request.
2. Put `{"type": "file", "attrs": {"signed_id": ...}}` first in the post body and create the post. Transcoding starts once the blob is attached (`media_transcoding.status` goes from `pending` to `succeeded` within minutes). Poll with `get-post`.
3. Add captions, chapters and the cover with `post-media-settings` (below).

## Captions, chapters and cover on a post: `post-media-settings`

```bash
.venv/bin/circle-client post-media-settings --url https://community.example.com/c/<space>/<post-slug> \
  --vtt subtitles.vtt --chapters chapters.txt --video-thumbnail cover.jpg --cdp http://127.0.0.1:9333
.venv/bin/circle-client post-media-settings ... --execute --confirm POST-MEDIA-SETTINGS
```

It drives the same Customize media dialog as `lesson-media-settings`, opened from the post page. On a post page, the hover that reveals the button targets the player itself. The waiting, seeking, all-or-nothing Save and `video.textTracks` read-back are shared with the lesson command (see [`course_lessons.md`](course_lessons.md)). Wait for transcoding to finish first. Saving changes a published post, so each live run needs the user's authorization.

**Bare `&` in a WebVTT file makes Save silently do nothing.** With such a file attached, clicking Save sends no request and shows no error. Browsers tolerate the character, but Circle's dialog does not. Escape `&`, `<` and `>` in cue text (`&amp;`, `&lt;`, `&gt;`). Players and the transcript panel still show "Q&A". `build_bilingual_vtt` now escapes its segments, `validate_vtt` reports unescaped characters, and both media-settings commands refuse such a file before opening the browser.

## Pointer at the top of each old lesson

Lessons are published, so treat each one as a single-run, authorized edit:

1. Back up every lesson's full JSON (`course-lesson --json`) to a local, untracked folder.
2. In the lesson editor, intercept the editor's Save request (`PUT /internal_api/courses/<space_id>/sections/<section_id>/lessons/<lesson_id>`). Replace `course_lesson.rich_text_body.body.content` with `[pointer paragraph] + backup content` (the backup with `circle_ios_fallback_text` removed). Keep the editor's other fields, such as `featured_media` and `thumbnail`. This guarantees the rest of the body is byte-for-byte the backup, even where the editor would have normalized nodes.
3. The editor can rewrite settings fields. One long-text lesson saved `default_tab: comments` instead of `curriculum`. Before continuing the request, set `default_tab`, `comments_enabled`, `featured_media_enabled`, `enforce_featured_media_completion`, `autocomplete_on_featured_media_completion`, `name` and `status` back to the backup values.
4. Read the lesson back. Check that the first node is the pointer, the remaining nodes equal the backup, and the media fields (`signed_id`, `chapters_url`, `media_transcript_id`, cover path ignoring CDN tokens) and settings are unchanged.

## Verification checklist

- **Each post against its lesson:** in the same admin browser, compare video duration (±1 s), caption cue count, chapter titles and the poster file. Play the post for a few seconds and check that `currentTime` advances.
- **Images:** Circle scrolls an inner container, not `window`, so lazy images only load after `scrollIntoView()` on each one. Count the loaded `img` elements after that.
- **Native videos:** check duration against `ffprobe`, cue count against the VTT, and chapter start times and titles against the chapters file. A cue's `text` keeps `&amp;`; `getCueAsHTML().textContent` shows `&`.
- **Logged out, in a headed browser with no cookies:** `?utm_source=test` returns 200 with no redirect and keeps the query string, the video plays, a captions track exists, comments show, and Log in / Join appear. Check the space root and the directory post too.
- **Quiet:** the posts are absent from the admin Feed, and no new notifications appear.

## Pitfalls

| Symptom | Cause / fix |
|---|---|
| Customize media Save does nothing, no request, no error | Unescaped `&` (or `<`, `>`) in the VTT. Escape it. The commands now refuse such files. |
| HTTP 429 while creating posts | Rate limit. About 20 s between posts, back off, confirm with `get-post` before retrying. |
| New space got `<slug>-xxxxxx` | The slug was taken earlier, possibly by a renamed space. Taken slugs are never freed. |
| Lesson's default tab flipped after an editor save | The editor rewrote it. Restore settings fields from the backup inside the intercepted request, then read back. |
| Image check reports unloaded images | Lazy loading in an inner scroll container. `scrollIntoView()` each image first. |
| Thumbnail URL differs after an unrelated save | The `bcdn_token` on CDN URLs rotates. Compare paths without the token. |
| Many video pages open at once crash the automation Chrome | Reuse one tab. After a crash, and only for the dedicated profile that `open-browser` created, move the stale `Singleton*` lock files to the trash once the owning PID is gone, then reopen. |
