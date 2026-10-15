"""Local dashboard page (no placeholders; all data flows through /api)."""

from __future__ import annotations

PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Circle · 通知 one-stop</title>
<style>
:root { --line:#e3e6ea; --muted:#6b7280; --accent:#238343; --danger:#b91c1c; }
* { box-sizing:border-box; }
body { margin:0; font:15px/1.55 -apple-system,"Segoe UI","PingFang SC",sans-serif; color:#1f2328; background:#f7f8fa; }
.wrap { max-width: 960px; margin: 0 auto; padding: 22px 22px 60px; }
header.top { position: sticky; top:0; z-index:5; background:#f7f8faee; backdrop-filter: blur(6px); border-bottom:1px solid var(--line); padding: 12px 2px; display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
header.top h1 { font-size: 18px; margin: 0; }
.stat { color: var(--muted); font-size: 13px; }
button.act { font: inherit; font-size: 13px; border: 1px solid var(--line); background:#fff; border-radius: 8px; padding: 3px 10px; cursor: pointer; }
button.act:hover { border-color: var(--accent); }
button.act.react { font-size: 15px; padding: 2px 8px; }
button.act.primary { border-color: var(--accent); color: var(--accent); font-weight: 600; }
button.act:disabled { opacity: .45; cursor: default; }
.banner { display:none; margin: 10px 0; padding: 8px 12px; border-radius: 8px; background:#fdecea; color:var(--danger); font-size: 13px; white-space: pre-wrap; }
.banner.show { display:block; }
h2.sec { font-size: 15px; margin: 22px 0 8px; color:#374151; }
.sec .count { color: var(--muted); font-weight: 400; font-size: 13px; margin-left: 6px; }
article.ctx { background:#fff; border:1px solid var(--line); border-radius: 12px; margin: 14px 0; padding: 16px 18px; }
.ctx-head { display:flex; align-items: baseline; gap:8px; flex-wrap: wrap; }
.ctx-head a.t { font-weight: 600; color: inherit; text-decoration: none; }
.ctx-head a.t:hover { color: var(--accent); }
.space { font-size: 12px; color: var(--muted); background:#eef1f4; border-radius: 6px; padding: 1px 8px; }
.newbadge { font-size: 12px; color: #fff; background: var(--accent); border-radius: 10px; padding: 1px 8px; }
.when { color: var(--muted); font-size: 12px; margin-left:auto; }
.rows { margin-top: 10px; display: flex; flex-direction: column; gap: 10px; }
.row { padding: 10px 12px; border-radius: 10px; background: #fbfcfd; border: 1px solid transparent; }
.row.target { background: #f4fbf6; border-color: #d1ead9; padding-left: 14px; }
.row.done { opacity: .5; }
.row.reply { border-left: 3px solid #b7dcc5; }
.r-meta { display: flex; gap: 8px; align-items: center; }
.who { font-weight: 600; display: inline-flex; align-items: center; gap: 6px; }
.chip { display: inline-flex; width: 22px; height: 22px; border-radius: 11px; background: #dfe5ec; color: #4b5563; font-size: 12px; font-weight: 600; align-items: center; justify-content: center; flex: none; }
.time { color: var(--muted); font-size: 12px; }
.rtext { white-space: pre-wrap; margin: 5px 0 2px; word-break: break-word; }
.rx { color: var(--muted); font-size: 13px; margin-top: 2px; }
.bar { display: flex; gap: 6px; margin-top: 8px; align-items: center; flex-wrap: wrap; }
.bar a { font-size: 13px; color: var(--accent); text-decoration: none; }
.likegroup, .otherrow { background:#fff; border:1px solid var(--line); border-radius: 10px; padding: 10px 14px; margin: 10px 0; display:flex; gap:10px; align-items: center; flex-wrap: wrap; }
.likegroup.done, .otherrow.done { opacity: .5; }
#spinner { color: var(--muted); font-size: 13px; }
</style>
</head>
<body>
<div class="wrap">
<header class="top">
  <h1>Circle · 通知</h1>
  <span class="stat" id="stat">–</span>
  <span style="flex:1"></span>
  <span id="spinner"></span>
  <button class="act" id="refresh">刷新</button>
</header>
<div class="banner" id="banner"></div>
<main id="main"><p class="stat">加载中…（首刷需要把全部上下文拉一遍）</p></main>
</div>
<script>
let STATE = null;
const done = new Set();
const $ = s => document.querySelector(s);
const main = $('#main');
const banner = $('#banner');

function fail(msg) { banner.textContent = msg; banner.classList.add('show'); }
function clearFail() { banner.classList.remove('show'); }
function spinner(on, text) { $('#spinner').textContent = on ? (text || '⟳') : ''; }
async function api(path, opts) {
  const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  let j = null;
  try { j = await r.json(); } catch { /* fallthrough */ }
  if (!r.ok || !j || !j.success) throw new Error((j && j.error) || ('HTTP ' + r.status));
  return j;
}
async function refresh() {
  try {
    clearFail(); spinner(true, '刷新中…');
    const j = await api('/api/state');
    STATE = j.state; done.clear(); render();
  } catch (e) { fail('刷新失败：' + e.message); }
  finally { spinner(false); }
}
$('#refresh').onclick = refresh;
document.addEventListener('keydown', e => { if ((e.metaKey||e.ctrlKey) && e.key === 'r') { e.preventDefault(); refresh(); } });

function timefmt(iso) { if (!iso) return ''; const d = new Date(iso); if (isNaN(d)) return iso; return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; }
function initials(name) { const c = (name || '?').trim(); return c ? c[0].toUpperCase() : '?'; }
function avatar(name) {
  const wrap = el('span', 'who');
  const chip = el('span', 'chip'); chip.textContent = initials(name);
  wrap.appendChild(chip);
  if (name) wrap.appendChild(document.createTextNode(name));
  return wrap;
}
function allIds(row) { return row.notification_ids || []; }
function rowDone(row) { const ids = allIds(row); return ids.length > 0 && ids.every(id => done.has(id)); }
function glyphOf(unicode) { const e = (STATE.emotes || []).find(x => x.unicode === unicode); return (e && e.glyph) || '🙂'; }

let refreshTimer = null;
function scheduleRefresh(delay) {
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => { refreshTimer = null; refresh(); }, delay || 400);
}
async function act(path, body, okNote) {
  try {
    await api(path, { method: 'POST', body: JSON.stringify(body) });
    clearFail();
    if (okNote) { okNote(); }
    scheduleRefresh();
  } catch (e) { fail('操作失败：' + e.message); }
  finally { spinner(false); }
}
function react(row, payload) {
  const kind = row.kind === 'message' ? 'chat_room_message' : 'comment';
  const hasNotification = !!(row.target && allIds(row).length);
  spinner(true, '反应中…');
  act('/api/react', {
    notification_id: hasNotification ? allIds(row)[0] : null,
    target_id: row.id,
    kind: kind,
    ...payload,
  }, () => { if (hasNotification) allIds(row).forEach(id => done.add(id)); });
}
function markRead(row) {
  const ids = allIds(row); let i = 0;
  const next = () => { if (i >= ids.length) { scheduleRefresh(); render(); return; }
    const id = ids[i++]; spinner(true, '标记中…');
    api('/api/mark_read', { method: 'POST', body: JSON.stringify({ notification_id: id }) })
      .catch(e => { clearFail(); fail('标记已读失败：' + e.message); })
      .finally(() => { done.add(id); setTimeout(next, 250); });
  };
  next();
}
function markGroup(group, btn) {
  if (!btn.dataset.confirm) {
    btn.dataset.confirm = '1'; btn.classList.add('primary');
    btn.textContent = `确认已读 ${group.count} 条？`;
    setTimeout(() => { if (btn.dataset.confirm) { btn.dataset.confirm = ''; btn.classList.remove('primary'); btn.textContent = '✓ 全部已读'; } }, 6000);
    return;
  }
  btn.dataset.confirm = ''; btn.classList.remove('primary');
  const ids = group.notification_ids || []; let i = 0;
  const next = () => { if (i >= ids.length) { scheduleRefresh(); render(); return; }
    const id = ids[i++]; spinner(true, `已读 ${i}/${ids.length}…`);
    api('/api/mark_read', { method: 'POST', body: JSON.stringify({ notification_id: id }) })
      .catch(e => { clearFail(); fail('标记已读失败：' + e.message); })
      .finally(() => { done.add(id); setTimeout(next, 250); });
  };
  next();
}

function reactionsOf(row) {
  const rx = row.reactions || [];
  if (!rx.length) return null;
  return rx.map(r => `${glyphOf(r.unicode)}${r.count > 1 ? '×' + r.count : ''}`).join(' ');
}

function rowNode(row, ctxUrl) {
  const depth = Math.min(row.depth || 0, 4);
  const rowEl = el('div', 'row' + (depth ? ' reply' : '') + (row.is_target ? ' target' : '') + (rowDone(row) ? ' done' : ''));
  rowEl.style.marginLeft = (depth * 36) + 'px';
  if (row.missing) {
    rowEl.appendChild(el('div', 'rtext', '⚠︎ 消息不在最近窗口内（可能在线程深处），请用「打开」去原页看'));
    if (row.actor_name) rowEl.appendChild(el('div', 'r-meta', row.actor_name));
    if (ctxUrl) { const a = el('a', '', '打开 ↗'); a.href = ctxUrl; a.target = '_blank'; a.rel = 'noopener'; rowEl.appendChild(el('div', 'bar')).appendChild(a); }
    return rowEl;
  }
  const meta = el('div', 'r-meta');
  meta.appendChild(avatar(row.actor_name));
  if (row.reply_to) meta.appendChild(el('span', 'time', `↩ 回复 ${row.reply_to}`));
  meta.appendChild(el('span', 'time', timefmt(row.created_at)));
  rowEl.appendChild(meta);
  if (row.text !== undefined && row.text !== null && row.text !== '') rowEl.appendChild(el('div', 'rtext', row.text));
  if (row.missing) rowEl.appendChild(el('div', 'rx', '⚠︎ 消息不在最近窗口内'));
  const rxText = reactionsOf(row);
  if (rxText) rowEl.appendChild(el('div', 'rx', '已有反应：' + rxText));
  if (row.hidden_replies) rowEl.appendChild(el('div', 'rx', `＋${row.hidden_replies} 条回复未展示`));
  const kind = row.kind === 'message' ? 'chat_room_message' : 'comment';
  const kinds = (STATE.verified_reaction_kinds || []);
  const isDone = rowDone(row);
  if (!row.missing && kinds.includes(kind) && !isDone) {
    const bar = el('div', 'bar');
    const buttons = kind === 'comment'
      ? (STATE.comment_reactions || []).map(r => ({ glyph: r.glyph, payload: { reaction_type: r.type } }))
      : (STATE.emotes || []).map(e => ({ glyph: e.glyph, payload: { unicode: e.unicode } }));
    buttons.forEach(b => {
      const btn = el('button', 'act react', b.glyph);
      btn.setAttribute('aria-label', Object.values(b.payload)[0]);
      btn.onclick = () => react(row, b.payload, b.glyph);
      bar.appendChild(btn);
    });
    rowEl.appendChild(bar);
    if (row.target && allIds(row).length) {
      const bar2 = el('div', 'bar');
      const read = el('button', 'act', '✓ 已读'); read.onclick = () => markRead(row); bar2.appendChild(read);
      if (ctxUrl) { const a = el('a', '', '打开 ↗'); a.href = ctxUrl; a.target = '_blank'; a.rel = 'noopener'; bar2.appendChild(a); }
      rowEl.appendChild(bar2);
    } else if (ctxUrl) {
      const bar2 = el('div', 'bar');
      const a = el('a', '', '打开 ↗'); a.href = ctxUrl; a.target = '_blank'; a.rel = 'noopener'; bar2.appendChild(a);
      rowEl.appendChild(bar2);
    }
  } else if (row.is_target && isDone) {
    rowEl.appendChild(el('div', 'rx', '✓ 处理过（刷新后从列表消失）'));
  }
  return rowEl;
}

function ctxNode(context) {
  const card = el('article', 'ctx');
  const head = el('div', 'ctx-head');
  if (context.url) { const a = el('a', 't', context.title || '(无标题)'); a.href = context.url; a.target = '_blank'; a.rel = 'noopener'; head.appendChild(a); }
  else head.appendChild(el('span', 't', context.title || '(无标题)'));
  head.appendChild(el('span', 'space', context.space_title || ''));
  head.appendChild(el('span', 'newbadge', `新 ${context.new_count}`));
  head.appendChild(el('span', 'when', timefmt(context.updated_at)));
  card.appendChild(head);
  if (context.error) card.appendChild(el('div', 'rx', '⚠︎ 拉取失败：' + context.error));
  const rowsEl = el('div', 'rows');
  const shown = (context.rows || []).length ? context.rows : context.targets;
  if (!shown || !shown.length) rowsEl.appendChild(el('div', 'stat', context.error ? '' : '（内容为空）'));
  (shown || []).forEach(row => rowsEl.appendChild(rowNode(row, context.url)));
  card.appendChild(rowsEl);
  return card;
}

function render() {
  if (!STATE) return;
  main.textContent = '';
  $('#stat').textContent = `未读 ${STATE.count} ｜ badge ${STATE.badge_count == null ? '–' : STATE.badge_count} ｜ 更新于 ${timefmt(STATE.fetched_at)}`;
  for (const sec of STATE.sections || []) {
    const h = el('h2', 'sec', sec.title); h.appendChild(el('span', 'count', sectionCount(sec))); main.appendChild(h);
    if (sec.id === 'discussions') {
      if (!sec.contexts.length) main.appendChild(el('p', 'stat', '没有要回应的讨论 ✓'));
      sec.contexts.forEach(c => main.appendChild(ctxNode(c)));
    } else if (sec.id === 'likes') {
      if (!sec.groups.length) main.appendChild(el('p', 'stat', '没有待处理的点赞 ✓'));
      sec.groups.forEach(g => {
        const div = el('div', 'likegroup' + (g.notification_ids.every(id => done.has(id)) ? ' done' : ''));
        div.appendChild(el('span', '', `${g.count} 人赞了《${g.title || ''}》`));
        div.appendChild(el('span', 'time', (g.actors || []).slice(0, 6).join('、') + (g.actors.length > 6 ? ' 等' + g.actors.length + ' 人' : '')));
        const sp = el('span'); sp.style.cssText = 'flex:1'; div.appendChild(sp);
        if (g.url) { const a = el('a', '', '打开 ↗'); a.href = g.url; a.target = '_blank'; a.rel = 'noopener'; div.appendChild(a); }
        const b = el('button', 'act', '✓ 全部已读'); b.onclick = () => markGroup(g, b); div.appendChild(b);
        div.appendChild(el('span', 'time', timefmt(g.updated_at)));
        main.appendChild(div);
      });
    } else {
      if (!sec.items.length) main.appendChild(el('p', 'stat', '没有其他通知 ✓'));
      sec.items.forEach(item => {
        const div = el('div', 'otherrow' + (item.notification_ids.every(id => done.has(id)) ? ' done' : ''));
        if (item.actor_name) div.appendChild(avatar(item.actor_name));
        div.appendChild(el('span', '', `${item.title || ''}`));
        div.appendChild(el('span', 'time', `${item.display_action || ''} · ${item.space_title || ''}`));
        const sp = el('span'); sp.style.cssText = 'flex:1'; div.appendChild(sp);
        if (item.url) { const a = el('a', '', '打开 ↗'); a.href = item.url; a.target = '_blank'; a.rel = 'noopener'; div.appendChild(a); }
        if (item.allow_mark_read) {
          if (!item.notification_ids.every(id => done.has(id))) { const b = el('button', 'act', '✓'); b.title = '标记已读'; b.onclick = () => markRead(item); div.appendChild(b); }
        } else div.appendChild(el('span', 'time', '需人工审核'));
        div.appendChild(el('span', 'time', timefmt(item.created_at)));
        main.appendChild(div);
      });
    }
  }
  if (!done.size) $('#refresh').textContent = '刷新';
}

function sectionCount(sec) {
  if (sec.id === 'discussions') { const n = (sec.contexts || []).reduce((a, c) => a + (c.new_count || 0), 0); return n ? `${n} 条` : ''; }
  if (sec.id === 'likes') { const n = (sec.groups || []).reduce((a, g) => a + (g.count || 0), 0); return n ? `${n} 条` : ''; }
  const n = (sec.items || []).length; return n ? `${n} 条` : '';
}

refresh();
</script>
</body>
</html>
"""