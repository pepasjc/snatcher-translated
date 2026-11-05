/* The review page. State: the scene list, the open scene, the dirty rows.
   Every fit verdict comes from the server (the same code the build uses);
   the page only debounces the check while you type. */
'use strict';

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

const state = {
  scenes: [], scene: null, kind: 'cue', dirty: new Map(), // rowKey -> {kind, idx, key, field, value}
  playing: null,
};

async function api(path, body) {
  const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) } : undefined);
  const j = await r.json();
  if (!r.ok || j.error) throw new Error(j.error || r.statusText);
  return j;
}

function setStatus(msg, cls = '') {
  const el = $('#status'); el.textContent = msg; el.className = 'status ' + cls;
}

/* ---- scene list ---- */
async function loadScenes() {
  state.scenes = await api('/api/scenes');
  renderScenes();
  const cues = state.scenes.reduce((a, s) => a + s.cues, 0);
  const tr = state.scenes.reduce((a, s) => a + s.translated, 0);
  const tot = state.scenes.reduce((a, s) => a + s.strings, 0);
  $('#totals').textContent = `${state.scenes.length} scenes · ${cues} voice cards · ${tr}/${tot} strings translated`;
}

function renderScenes() {
  const f = $('#scene-filter').value.trim().toLowerCase();
  const ul = $('#scenes'); ul.innerHTML = '';
  for (const s of state.scenes) {
    const label = `${s.id} ${s.name} ${s.note}`.toLowerCase();
    if (f && !label.includes(f)) continue;
    const li = document.createElement('li');
    li.dataset.id = s.id;
    if (state.scene && state.scene.id === s.id) li.classList.add('on');
    if (s.note) li.title = s.note;
    li.innerHTML = `<span class="sid">${s.id}</span><span class="sname">${esc(s.name || '')}</span>` +
      `<span class="counts"><b>${s.cues}</b>♪ <b>${s.translated}</b>/${s.strings}</span>`;
    li.onclick = () => openScene(s.id);
    ul.appendChild(li);
  }
}

/* ---- a scene ---- */
async function openScene(id) {
  if (state.dirty.size && !confirm('Unsaved edits in this scene will be lost. Continue?')) return;
  state.dirty.clear(); updateSaveAll();
  setStatus('loading…');
  state.scene = await api('/api/scene/' + id);
  $('#empty').hidden = true; $('#scene').hidden = false;
  $('#scene-id').textContent = id;
  const meta = state.scenes.find(s => s.id === id) || {};
  $('#scene-name').value = meta.name || '';
  const o = state.scene.options || {};
  $('#scene-meta').textContent =
    `${state.scene.cues.length} voice cards · ${state.scene.strings.length} strings · card ${state.scene.rows} rows × ${state.scene.cols} cells` +
    (o.faceleft ? ' · face-left' : '') + (o._note ? ' · ' + o._note : '') +
    (state.scene.slack ? ` · longs ${state.scene.slack.count} (${state.scene.slack.longs} B), ${state.scene.slack.free} B free in the bank slot` : '') +
    (state.scene.have_ref ? '' : ' · (no work/ref: Japanese text missing)');
  $('#transcribe').hidden = !state.scene.asr;
  $('#furigana').parentElement.hidden = !state.scene.furigana;
  $('#segacd').parentElement.hidden = !state.scene.have_sc;
  document.body.classList.toggle('with-sc', state.scene.have_sc && $('#segacd').checked);
  renderScenes();
  renderLines();
  setStatus('');
  $('#main').scrollTop = 0;
}

function rowKey(kind, idx) { return kind + ':' + idx; }

function passesFilters(kind, rec) {
  const f = $('#line-filter').value.trim().toLowerCase();
  if (f) {
    const hay = `${rec.speaker || ''} ${rec.jp || ''} ${rec.en || ''} ${rec.long || ''} ${rec.id || ''} ${rec.sc || ''}`.toLowerCase();
    if (!hay.includes(f)) return false;
  }
  if ($('#only-untranslated').checked && (rec.en || rec.lock)) return false;
  if ($('#only-problems').checked && rec.fit.ok) return false;
  if (kind === 'string' && $('#only-dialogue').checked && rec.kind !== 'dialogue') return false;
  return true;
}

function renderLines() {
  const box = $('#lines'); box.innerHTML = '';
  const sc = state.scene;
  const kinds = state.kind === 'all' ? ['cue', 'string'] : [state.kind];
  for (const kind of kinds) {
    const list = kind === 'cue' ? sc.cues : sc.strings;
    const shown = list.filter(r => passesFilters(kind, r));
    const h = document.createElement('div'); h.className = 'group-head';
    h.textContent = (kind === 'cue' ? 'Voice lines (subtitle cards)' : 'Dialogue-box text (bank strings)') +
      ` · ${shown.length} of ${list.length}`;
    box.appendChild(h);
    for (const r of shown) box.appendChild(kind === 'cue' ? cueRow(r) : stringRow(r));
  }
}

function rubyHtml(rec) {
  if (!rec.ruby || !rec.ruby.length) return esc(rec.jp || '');
  // tokens {p: [[text, reading|null], ...], g: gloss|null}; a gloss makes the token hoverable
  const piece = ([t, r]) => r ? `<ruby>${esc(t)}<rt>${esc(r)}</rt></ruby>` : esc(t);
  return rec.ruby.map(tok => {
    const inner = tok.p.map(piece).join('');
    return tok.g ? `<span class="tok" data-g="${esc(tok.g)}">${inner}</span>` : inner;
  }).join('');
}

function jpCell(c) {
  const body = c.jp ? rubyHtml(c)
    : (c.stream ? (c.stream.has_ts ? 'no ASR segment inside this span (' + esc(c.stream.key) + ')' : 'no transcript for ' + esc(c.stream.key))
                : 'no stream in the census');
  const btn = c.stream ? `<div><button class="tx" title="${c.stream.has_ts ? 'transcribe this stream again with VAD off (quiet speech the filter dropped)' : 'transcribe this stream with whisper'}">${c.stream.has_ts ? 'redo, no VAD' : 'transcribe'}</button></div>` : '';
  return body + btn;
}

function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

function fitText(kind, fit) {
  if (kind === 'cue') return `${fit.rows.length}/${fit.max_rows} rows · ${Math.max(0, ...fit.cells)}/${fit.cols} cells`;
  if (fit.size == null) return 'unencodable';
  return `${fit.size}/${fit.budget} bytes`;
}

function previewHtml(fit) {
  return fit.rows.map((r, i) => {
    const over = fit.cells[i] > fit.cols || i >= fit.max_rows;
    return `<span class="${over ? 'over' : ''}">${esc(r || ' ')}</span>`;
  }).join('\n');
}

function markDirty(row, entry) {
  const k = rowKey(entry.kind, entry.idx) + ':' + entry.field;
  if (entry.value === entry.orig) state.dirty.delete(k); else state.dirty.set(k, entry);
  row.classList.toggle('dirty', [...state.dirty.keys()].some(x => x.startsWith(rowKey(entry.kind, entry.idx) + ':')));
  updateSaveAll();
}

function updateSaveAll() {
  $('#save-all').disabled = state.dirty.size === 0;
  $('#save-all').textContent = state.dirty.size ? `Save all (${state.dirty.size}) — Ctrl+S` : 'Save all (Ctrl+S)';
}

let checkTimer = null;
function scheduleCheck(row, kind, rec, value) {
  clearTimeout(checkTimer);
  checkTimer = setTimeout(async () => {
    try {
      const body = { scene: state.scene.id, kind, idx: rec.idx, value };
      if (kind === 'cue') { body.rows = state.scene.rows; body.cols = Math.min(rec.fit.cols, state.scene.cols); }
      else body.budget = rec.budget;
      const j = await api('/api/check', body);
      applyFit(row, kind, j.fit);
    } catch (e) { setStatus(e.message, 'err'); }
  }, 250);
}

function applyFit(row, kind, fit) {
  const f = $('.fit', row); f.textContent = fitText(kind, fit); f.className = 'fit ' + (fit.ok ? 'ok' : 'bad');
  row.classList.toggle('bad', !fit.ok);
  const h = $('.hint', row); if (h) h.hidden = fit.ok || !!($('input[data-field=long]', row) || {}).value;
  const p = $('.preview', row); if (p) p.innerHTML = previewHtml(fit);
}

function editable(row, kind, rec, field, el, isBool = false) {
  const orig = isBool ? !!rec[field] : (rec[field] || '');
  el.addEventListener('input', () => {
    const v = isBool ? el.checked : el.value;
    markDirty(row, { kind, idx: rec.idx, key: kind === 'cue' ? rec.id : rec.off, field, value: v, orig });
    if (field === 'en') scheduleCheck(row, kind, rec, v);
  });
  el.addEventListener('keydown', ev => {
    if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); saveRow(row, kind, rec); }
    if (ev.key === 'Escape') { revertRow(row, kind, rec); el.blur(); }
  });
}

async function saveRow(row, kind, rec) {
  const prefix = rowKey(kind, rec.idx) + ':';
  const entries = [...state.dirty.entries()].filter(([k]) => k.startsWith(prefix));
  if (!entries.length) return;
  for (const [k, e] of entries) {
    try {
      const j = await api('/api/save', { scene: state.scene.id, kind, idx: e.idx, key: e.key, field: e.field, value: e.value });
      rec[e.field] = j.text !== undefined ? j.text : e.value; rec.fit = j.fit;
      state.dirty.delete(k);
      if (j.text !== undefined && j.text !== e.value) {      // the server re-laid the ￥ breaks
        const el = $(`[data-field="${e.field}"]`, row); if (el && el.type !== 'checkbox') el.value = j.text;
      }
      applyFit(row, kind, j.fit);
      // what check_strings says about the line as saved: a colour code of the
      // Japanese gone, a row wider than the box, a control byte dropped
      if (j.warn && j.warn.length) setStatus(`saved ${kind} #${rec.idx} - ` + j.warn.join('; '), 'err');
      else setStatus(`saved ${kind} ${kind === 'cue' ? rec.id : '#' + rec.idx}`, 'ok');
    } catch (err) { setStatus(`save failed: ${err.message}`, 'err'); return; }
  }
  row.classList.remove('dirty'); updateSaveAll();
  if (kind === 'string') refreshCounts();
}

function revertRow(row, kind, rec) {
  const prefix = rowKey(kind, rec.idx) + ':';
  for (const k of [...state.dirty.keys()]) if (k.startsWith(prefix)) state.dirty.delete(k);
  $$('textarea, input', row).forEach(el => {
    const f = el.dataset.field; if (!f) return;
    if (el.type === 'checkbox') el.checked = !!rec[f]; else el.value = rec[f] || '';
  });
  applyFit(row, kind, rec.fit);
  row.classList.remove('dirty'); updateSaveAll();
}

async function saveAll() {
  const groups = new Map();
  for (const [k, e] of state.dirty) { const g = rowKey(e.kind, e.idx); if (!groups.has(g)) groups.set(g, e); }
  for (const [g, e] of groups) {
    const row = $(`.row[data-key="${g}"]`);
    const rec = (e.kind === 'cue' ? state.scene.cues : state.scene.strings)[e.idx];
    if (row) await saveRow(row, e.kind, rec);
  }
  setStatus(state.dirty.size ? 'some rows failed' : 'all saved', state.dirty.size ? 'err' : 'ok');
}

async function refreshCounts() {
  const scenes = await api('/api/scenes');
  state.scenes = scenes; renderScenes();
}

/* ---- rows ---- */
function cueRow(c) {
  const row = document.createElement('div');
  row.className = 'row' + (c.fit.ok ? '' : ' bad') + (c.enabled ? '' : ' lock');
  row.dataset.key = rowKey('cue', c.idx);
  row.innerHTML = `
    <div class="n"><span class="id">${esc(c.id)}</span>${c.start}–${c.end}<br>${c.dur != null ? c.dur + ' s' : ''}
      ${c.last ? '<span class="badge">last</span>' : ''}${c.by_ear ? '<span class="badge">ear</span>' : ''}${c.enabled ? '' : '<span class="badge off">off</span>'}</div>
    <div class="spk"><input type="text" data-field="speaker" value="${esc(c.speaker)}" spellcheck="false">
      <label class="tag"><input type="checkbox" data-field="enabled" ${c.enabled ? 'checked' : ''}> shown</label></div>
    <div class="jp ${c.jp ? '' : 'none'}">${jpCell(c)}</div>
    ${scCell(c)}
    <div class="en"><textarea data-field="en" rows="2" spellcheck="true">${esc(c.en)}</textarea>
      <div class="preview">${previewHtml(c.fit)}</div>
      <div class="fit ${c.fit.ok ? 'ok' : 'bad'}">${fitText('cue', c.fit)}</div></div>
    <div class="act">
      <button class="play" title="play this card's span">▶ card</button>
      ${c.stream ? `<a href="#" class="play-stream" title="the whole stream ${esc(c.stream.key)}">▶ stream ${fmtDur(c.stream.dur)}</a>` : ''}
      <a href="/audio/f${c.file}_c${c.chan}_${c.start}_${c.end}.wav" download title="save the card's wav">⤓ wav</a>
      <button class="row-save" title="Ctrl+Enter">save</button><button class="row-undo" title="Esc">undo</button>
    </div>`;
  const ta = $('textarea', row); autosize(ta);
  editable(row, 'cue', c, 'en', ta);
  editable(row, 'cue', c, 'speaker', $('input[data-field=speaker]', row));
  editable(row, 'cue', c, 'enabled', $('input[data-field=enabled]', row), true);
  $('.play', row).onclick = () => play($('.play', row), `/audio/f${c.file}_c${c.chan}_${c.start}_${c.end}.wav`);
  const ps = $('.play-stream', row);
  if (ps) ps.onclick = ev => { ev.preventDefault(); play($('.play', row), `/audio/f${c.file}_c${c.chan}_${c.stream.start}_${c.stream.end}.wav`); };
  $('.row-save', row).onclick = () => saveRow(row, 'cue', c);
  $('.row-undo', row).onclick = () => revertRow(row, 'cue', c);
  const tx = $('.tx', row);
  if (tx) tx.onclick = () => transcribe([c.id], c.stream.has_ts);
  return row;
}

function stringRow(s) {
  const row = document.createElement('div');
  row.className = 'row' + (s.fit.ok ? '' : ' bad') + (s.lock ? ' lock' : '');
  row.dataset.key = rowKey('string', s.idx);
  row.innerHTML = `
    <div class="n"><span class="id">#${s.idx}</span>@${s.off}<br>${s.budget} B${s.lock ? '<span class="badge lock">lock</span>' : ''}</div>
    <div class="spk"><span class="badge kind ${s.kind}">${s.kind}</span><span class="tag">${s.long ? ' + long' : ''}</span></div>
    <div class="jp ${s.jp ? '' : 'none'}">${s.jp ? rubyHtml(s) : 'no Japanese (work/ref missing)'}</div>
    ${scCell(s)}
    <div class="en"><textarea data-field="en" rows="1" spellcheck="true" ${s.lock ? 'readonly' : ''}>${esc(s.en)}</textarea>
      <div class="long">long <input type="text" data-field="long" value="${esc(s.long)}" placeholder="full text shown at runtime via repoint (menu labels)" ${s.lock ? 'readonly' : ''}></div>
      <div class="fit ${s.fit.ok ? 'ok' : 'bad'}">${fitText('string', s.fit)}</div>
      <div class="hint" hidden>over budget: the build skips this text and keeps the Japanese. Keep "en" within budget and put the full text in "long" (appended to the bank, remapped at runtime).</div></div>
    <div class="act">${s.lock ? '' : '<button class="row-save" title="Ctrl+Enter">save</button><button class="row-undo" title="Esc">undo</button>'}</div>`;
  const ta = $('textarea', row); autosize(ta);
  const hint = $('.hint', row); hint.hidden = s.fit.ok || !!s.long;
  if (!s.lock) {
    editable(row, 'string', s, 'en', ta);
    editable(row, 'string', s, 'long', $('input[data-field=long]', row));
    $('.row-save', row).onclick = () => saveRow(row, 'string', s);
    $('.row-undo', row).onclick = () => revertRow(row, 'string', s);
  }
  return row;
}

function scCell(r) {
  if (!state.scene.have_sc || !$('#segacd').checked) return '';
  if (!r.sc) return '<div class="sc none">no Sega CD match</div>';
  const w = r.sc_score < 60 ? ' weak' : '';
  const body = r.sc.split('￥').map(esc).join('<br>');
  return `<div class="sc${w}" title="Sega CD line paired by ps1/tools/segacd_align.py (score ${r.sc_score})">${body}<span class="score">${r.sc_score}</span></div>`;
}

function fmtDur(d) { return d == null ? '' : (d >= 60 ? `${Math.floor(d / 60)}m${Math.round(d % 60)}s` : `${d}s`); }

function autosize(ta) {
  const fit = () => { ta.style.height = 'auto'; ta.style.height = Math.max(ta.scrollHeight, 28) + 'px'; };
  ta.addEventListener('input', fit); requestAnimationFrame(fit);
}

/* ---- audio ---- */
const player = $('#player');
function play(btn, src) {
  if (state.playing && state.playing.btn === btn && state.playing.src === src && !player.paused) {
    player.pause(); return;
  }
  if (state.playing) state.playing.btn.classList.remove('playing');
  state.playing = { btn, src };
  btn.classList.add('playing'); btn.textContent = '… card';
  player.src = src;
  player.play().catch(e => { setStatus('audio: ' + e.message, 'err'); btn.classList.remove('playing'); });
}
player.addEventListener('playing', () => { if (state.playing) state.playing.btn.textContent = '⏸ card'; });
player.addEventListener('pause', () => { if (state.playing) { state.playing.btn.textContent = '▶ card'; state.playing.btn.classList.remove('playing'); } });
player.addEventListener('ended', () => { if (state.playing) { state.playing.btn.textContent = '▶ card'; state.playing.btn.classList.remove('playing'); } });
player.addEventListener('error', () => {
  setStatus('audio failed (no pristine image, or the span has no such stream)', 'err');
  if (state.playing) { state.playing.btn.textContent = '▶ card'; state.playing.btn.classList.remove('playing'); }
});

/* ---- wiring ---- */
$('#scene-filter').addEventListener('input', renderScenes);
$('#line-filter').addEventListener('input', () => state.scene && renderLines());
$('#only-untranslated').addEventListener('change', () => state.scene && renderLines());
$('#only-problems').addEventListener('change', () => state.scene && renderLines());
$$('#kind-seg button').forEach(b => b.onclick = () => {
  $$('#kind-seg button').forEach(x => x.classList.toggle('on', x === b));
  state.kind = b.dataset.kind; if (state.scene) renderLines();
});
$('#save-all').onclick = saveAll;
$('#only-dialogue').addEventListener('change', () => state.scene && renderLines());
$('#segacd').addEventListener('change', ev => { document.body.classList.toggle('with-sc', state.scene && state.scene.have_sc && ev.target.checked); state.scene && renderLines(); });
$('#furigana').addEventListener('change', ev => document.body.classList.toggle('no-furigana', !ev.target.checked));
$('#transcribe').onclick = () => transcribe(null, false);

/* ---- transcription ---- */
async function transcribe(ids, redo) {
  if (!state.scene) return;
  try {
    const j = await api('/api/transcribe', { scene: state.scene.id, ids, redo, novad: !!redo });
    setStatus(`transcribing ${j.queued.length} stream(s)…`, 'ok');
    pollJob();
  } catch (e) { setStatus(e.message, 'err'); }
}

let jobTimer = null;
async function pollJob() {
  clearTimeout(jobTimer);
  const j = await api('/api/job');
  $('#transcribe').disabled = j.running;
  $$('button.tx').forEach(b => b.disabled = j.running);
  if (j.running) {
    pollJob.wasRunning = true;
    setStatus(`whisper ${j.done}/${j.total} · ${j.current}`, '');
    jobTimer = setTimeout(pollJob, 2000);
    return;
  }
  if (j.error) setStatus('transcription failed: ' + j.error, 'err');
  else if (j.total) setStatus(`transcribed ${j.done}/${j.total}: ` + j.log.slice(-3).join(' · '), 'ok');
  if (j.total && state.scene && pollJob.wasRunning) refreshJapanese();
  pollJob.wasRunning = false;
}

async function refreshJapanese() {
  /* re-read the scene's Japanese without touching the rows' edits */
  const fresh = await api('/api/scene/' + state.scene.id);
  for (const c of fresh.cues) {
    const old = state.scene.cues[c.idx];
    if (!old || old.id !== c.id) continue;
    old.jp = c.jp; old.ruby = c.ruby; old.stream = c.stream;
    const row = $(`.row[data-key="cue:${c.idx}"]`);
    if (!row) continue;
    const jp = $('.jp', row);
    jp.classList.toggle('none', !c.jp);
    jp.innerHTML = jpCell(c);
    const nb = $('.tx', row); if (nb) nb.onclick = () => transcribe([c.id], c.stream.has_ts);
  }
}
$('#scene-name').addEventListener('change', async ev => {
  if (!state.scene) return;
  await api('/api/scene_name', { scene: state.scene.id, name: ev.target.value.trim() });
  refreshCounts();
});
document.addEventListener('keydown', ev => {
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 's') { ev.preventDefault(); saveAll(); }
});
window.addEventListener('beforeunload', ev => { if (state.dirty.size) { ev.preventDefault(); ev.returnValue = ''; } });

/* ?kind=cue|string|all &q=text &problems=1 &untranslated=1 &dialogue=0 &furigana=0 #BANK */
const params = new URLSearchParams(location.search);
if (params.get('kind')) { const b = $(`#kind-seg button[data-kind=${params.get('kind')}]`); if (b) b.click(); }
if (params.get('q')) $('#line-filter').value = params.get('q');
for (const [k, id] of [['problems', 'only-problems'], ['untranslated', 'only-untranslated'], ['dialogue', 'only-dialogue'], ['furigana', 'furigana'], ['segacd', 'segacd']]) {
  if (params.has(k)) { const el = $('#' + id); el.checked = params.get(k) !== '0'; el.dispatchEvent(new Event('change')); }
}

loadScenes().then(() => {
  const h = location.hash.replace('#', '');
  if (h) openScene(h);
  pollJob();
});
