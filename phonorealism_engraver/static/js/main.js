/*
 * main.js — engraver application wiring.
 *
 * Organised as Setup / Write / Engrave, following Dorico: what you are doing
 * decides what the panel offers. Setup names the parts, Write places the marks,
 * Engrave controls spacing, breaks and page furniture.
 *
 * The score is read by the shared reader, exactly as the conductor page reads
 * it, so partial numbering is guaranteed identical between the applications.
 */

import { loadScoreFile, defaultParts, partLabel } from '/shared/score.js';
import {
  GLOBAL, KINDS, KIND_ORDER, makeProject, validate,
  addAnnotation, removeAnnotation, updateAnnotation, explodeToParts,
  allSorted, toPartMap,
} from '/shared/annotations.js';
import {
  defaultLayouts, layoutFor, profileKeyFor, pageGeometry, PAGE_SIZES,
  addBreak, removeBreak, orderedParts,
} from '/shared/layout.js';
import { EngraveCanvas } from './canvas.js';
import { openPrintView, downloadSVG } from './print.js';

const $ = (id) => document.getElementById(id);

const state = {
  score: null,
  project: makeProject(),
  filter: 'all',
  editingId: null,
  pendingPlace: null,
  editingBreakId: null,
  dirty: false,
  mode: 'export', // or 'print', for the shared dialogue
};

const sheet = new EngraveCanvas($('sheet'));

/**
 * The layout profile currently being edited, and the one the canvas is showing.
 *
 * Settings live on the project so they save with it. Older projects carried a
 * single `layout`; that is promoted to both profiles on load rather than
 * discarded.
 */
function ensureLayouts() {
  const p = state.project;
  if (!p.layouts) {
    p.layouts = defaultLayouts();
    if (p.layout) {
      p.layouts.score = { ...p.layouts.score, ...p.layout };
      p.layouts.parts = { ...p.layouts.parts, ...p.layout };
      delete p.layout;
    }
  }
  return p.layouts;
}

/** The profile the Engrave panel edits. */
function editedProfile() {
  return $('layoutProfile')?.value === 'parts' ? 'parts' : 'score';
}

function editedLayout() {
  const set = ensureLayouts();
  const key = editedProfile();
  if (!set[key]) set[key] = defaultLayouts()[key];
  return set[key];
}

/** The profile governing what is currently drawn. */
function layout() {
  ensureLayouts();
  return layoutFor(state.project, sheet.target);
}

/* ------------------------------------------------------------------ *
 * Tabs
 * ------------------------------------------------------------------ */

for (const tab of document.querySelectorAll('.tab')) {
  tab.onclick = () => {
    for (const t of document.querySelectorAll('.tab')) t.classList.toggle('active', t === tab);
    for (const p of document.querySelectorAll('.tabpane')) {
      p.classList.toggle('hidden', p.dataset.pane !== tab.dataset.tab);
    }
    // The surface reads the mode to decide what a click on empty space means.
    sheet.mode = tab.dataset.tab;
    $('zoomHint').textContent =
      tab.dataset.tab === 'write'
        ? 'click to place a mark'
        : tab.dataset.tab === 'engrave'
          ? 'click to place a break · drag a flag to move it'
          : sheet.view === 'page'
            ? 'scroll to page · ⌘-scroll to zoom'
            : 'scroll to zoom · shift-scroll to pan';
    sheet.draw();
  };
}

/* ------------------------------------------------------------------ *
 * Score loading
 * ------------------------------------------------------------------ */

$('loadScoreBtn').onclick = () => $('scoreFile').click();

$('scoreFile').onchange = async () => {
  const file = $('scoreFile').files[0];
  if (file) await ingestScore(file);
};

async function ingestScore(file) {
  {
    try {
    const score = await loadScoreFile(file);
    state.score = score;
    if (!state.project.parts.length) {
      const p = makeProject(score, defaultParts(score).map(stripAuto));
      p.layouts = ensureLayouts();
      p.breaks = state.project.breaks || [];
      state.project = p;
    } else {
      state.project.score = makeProject(score).score;
    }
    $('scoreInfo').textContent =
      `${score.name} · ${score.partials.length} partials · ${score.duration.toFixed(1)} s · ${score.source}`;
    if (!$('projectName').value) $('projectName').value = score.name;
    sheet.setScore(score);
    sheet.setProject(state.project);
    sheet.fitAll();
    refresh();
    } catch (err) {
      showIssues([
        { level: 'error', message: `Could not read "${file.name}": ${err.message}` },
      ]);
    }
  }
}

const stripAuto = (p) => ({ id: p.id, name: p.name, partials: p.partials });

/**
 * Drag a score anywhere onto the surface.
 *
 * The file dialog depends on the browser honouring a programmatic click on a
 * hidden input, which is the one step here that cannot be verified from
 * outside the browser. Drag and drop reaches the same code path without it.
 */
{
  const stage = $('stage');
  const stop = (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
  };
  for (const type of ['dragenter', 'dragover']) {
    stage.addEventListener(type, (ev) => {
      stop(ev);
      stage.classList.add('dropping');
    });
  }
  for (const type of ['dragleave', 'drop']) {
    stage.addEventListener(type, (ev) => {
      stop(ev);
      stage.classList.remove('dropping');
    });
  }
  stage.addEventListener('drop', (ev) => {
    const file = ev.dataTransfer?.files?.[0];
    if (file) ingestScore(file);
  });
}

function showIssues(issues) {
  const box = $('issues');
  if (!issues.length) {
    box.classList.add('hidden');
    box.innerHTML = '';
    return;
  }
  box.classList.remove('hidden');
  box.innerHTML = issues
    .map((i) => `<div class="${i.level === 'warn' ? 'warn' : ''}">${escapeHtml(i.message)}</div>`)
    .join('');
}

/* ------------------------------------------------------------------ *
 * Setup — parts
 * ------------------------------------------------------------------ */

$('autoParts').onclick = () => {
  if (!state.score) return;
  state.project.parts = defaultParts(state.score).map(stripAuto);
  touched();
};

$('addPart').onclick = () => {
  if (!state.score) return;
  const name = prompt('Part name (e.g. "Violin 1")');
  if (!name) return;
  const spec = prompt(
    `Which partials? 1–${state.score.partials.length}. Ranges allowed, e.g. "3, 7, 12-14"`
  );
  if (!spec) return;
  const partials = parseSpec(spec, state.score.partials.length);
  if (!partials.length) return alert('No valid partial numbers in that.');
  state.project.parts.push({ id: `g${Date.now().toString(36)}`, name: name.trim(), partials });
  touched();
};

function parseSpec(spec, max) {
  const out = new Set();
  for (const chunk of String(spec).split(',')) {
    const r = chunk.trim().match(/^(\d+)\s*[-–]\s*(\d+)$/);
    if (r) {
      for (let i = Math.min(+r[1], +r[2]); i <= Math.max(+r[1], +r[2]); i++) {
        if (i >= 1 && i <= max) out.add(i);
      }
    } else {
      const n = parseInt(chunk, 10);
      if (n >= 1 && n <= max) out.add(n);
    }
  }
  return [...out].sort((a, b) => a - b);
}

function renderParts() {
  const box = $('partList');
  box.innerHTML = '';
  if (!state.project.parts.length) {
    box.innerHTML = '<div class="hint">No parts yet.</div>';
    return;
  }
  // Listed in the order they appear on the page, so the panel matches the score.
  for (const part of orderedParts(state.project.parts, layout())) {
    const row = document.createElement('div');
    row.className = 'item';
    const grow = document.createElement('div');
    grow.className = 'grow';
    const nm = document.createElement('div');
    nm.className = 'nm';
    nm.textContent = part.name;
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = state.score
      ? `${part.partials.join(', ')} · ${partLabel(state.score, part)}`
      : part.partials.join(', ');
    grow.append(nm, meta);
    grow.onclick = () => {
      const n = prompt('Part name', part.name);
      if (n) part.name = n.trim();
      const s = prompt('Partials', part.partials.join(', '));
      if (s && state.score) part.partials = parseSpec(s, state.score.partials.length);
      touched();
    };
    const del = document.createElement('button');
    del.className = 'sm';
    del.textContent = '✕';
    del.onclick = (e) => {
      e.stopPropagation();
      state.project.parts = state.project.parts.filter((p) => p !== part);
      touched();
    };
    row.append(grow, del);
    box.append(row);
  }
}

$('lowestAtBottom').onchange = () => {
  // Part ordering describes the work, not one layout of it.
  const set = ensureLayouts();
  for (const key of Object.keys(set)) set[key].lowestAtBottom = $('lowestAtBottom').checked;
  touched();
};

/* ------------------------------------------------------------------ *
 * Target selector — "Full Score" or a bare part name
 * ------------------------------------------------------------------ */

function renderTargetSelect() {
  const sel = $('targetSelect');
  const cur = sel.value;
  sel.innerHTML = '<option value="score">Full Score</option>';
  for (const p of orderedParts(state.project.parts, layout())) {
    const o = document.createElement('option');
    o.value = p.id;
    o.textContent = p.name;
    sel.append(o);
  }
  sel.value = cur && [...sel.options].some((o) => o.value === cur) ? cur : 'score';
  sheet.target = sel.value;
}

$('targetSelect').onchange = () => {
  sheet.target = $('targetSelect').value;
  // Editing follows viewing: the Engrave panel should describe what is on screen.
  $('layoutProfile').value = profileKeyFor(sheet.target);
  syncControls();
  sheet.draw();
  renderBreaks();
};

/* ------------------------------------------------------------------ *
 * Write — annotations
 * ------------------------------------------------------------------ */

sheet.addEventListener('place', (ev) => {
  if (!state.project.parts.length) return;
  state.pendingPlace = ev.detail;
  openModal(null);
});
sheet.addEventListener('edit', (ev) => openModal(ev.detail));
sheet.addEventListener('select', (ev) => {
  state.editingId = ev.detail;
  renderInspector();
  renderMarks();
});
sheet.addEventListener('edited', () => {
  markDirty();
  renderInspector();
  renderMarks();
});

function scopeOptions(selectEl, selected) {
  selectEl.innerHTML = `<option value="${GLOBAL}">Full Score</option>`;
  for (const p of orderedParts(state.project.parts, layout())) {
    const o = document.createElement('option');
    o.value = p.id;
    o.textContent = p.name;
    selectEl.append(o);
  }
  if (selected) selectEl.value = selected;
}

function openModal(id) {
  const a = id ? state.project.annotations.find((x) => x.id === id) : null;
  state.editingId = id;

  $('modalTitle').textContent = a ? 'Edit annotation' : 'New annotation';
  $('mKind').innerHTML = KIND_ORDER.map(
    (k) => `<option value="${k}">${KINDS[k].label}</option>`
  ).join('');
  scopeOptions($('mScope'), a ? a.scope : state.pendingPlace?.partId || GLOBAL);

  if (a) {
    $('mText').value = a.text;
    $('mKind').value = a.kind;
    $('mTime').value = a.t.toFixed(2);
    $('mTime2').value = a.t2 == null ? '' : a.t2.toFixed(2);
    $('mPlace').value = a.place;
  } else {
    const p = state.pendingPlace;
    $('mText').value = '';
    $('mKind').value = 'lyric';
    $('mTime').value = (p ? p.t : 0).toFixed(2);
    $('mTime2').value = '';
    $('mPlace').value = 'on';
  }
  $('mDelete').classList.toggle('hidden', !a);
  $('mExplode').classList.toggle('hidden', !a || a.scope !== GLOBAL);
  $('modal').classList.remove('hidden');
  $('mText').focus();
}

$('mSave').onclick = () => {
  const text = $('mText').value.trim();
  if (!text) return alert('Give the annotation some text.');
  const spec = {
    scope: $('mScope').value,
    kind: $('mKind').value,
    t: parseFloat($('mTime').value) || 0,
    t2: $('mTime2').value === '' ? null : parseFloat($('mTime2').value),
    text,
    place: $('mPlace').value,
  };
  if (state.editingId) {
    updateAnnotation(state.project, state.editingId, spec);
  } else {
    const a = addAnnotation(state.project, spec);
    // Land the mark exactly where it was clicked. The offset is stored in cents
    // from the sounding line, so it holds its position as the view rescales.
    const p = state.pendingPlace;
    if (p && Number.isFinite(p.cents)) {
      const band = bandCentsAt(p.partId, spec.t);
      a.dy = band == null ? 0 : p.cents - band;
    }
    state.editingId = a.id;
    sheet.selectedId = a.id;
  }
  state.pendingPlace = null;
  $('modal').classList.add('hidden');
  touched();
};

/** Pitch of the loudest partial of a part at time t, in cents. */
function bandCentsAt(partId, t) {
  const part = state.project.parts.find((p) => p.id === partId);
  if (!part || !state.score) return null;
  let best = null;
  for (const i of part.partials) {
    const p = state.score.partials[i - 1];
    if (!p) continue;
    const n = p.t.length;
    if (t < p.t[0] || t > p.t[n - 1]) continue;
    let k = 0;
    while (k + 1 < n && p.t[k + 1] <= t) k++;
    if (k + 1 >= n) continue;
    const u = (t - p.t[k]) / (p.t[k + 1] - p.t[k] || 1);
    const f = p.f[k] + u * (p.f[k + 1] - p.f[k]);
    const amp = p.a[k] + u * (p.a[k + 1] - p.a[k]);
    if (f > 0 && (!best || amp > best.a)) best = { f, a: amp };
  }
  return best ? 1200 * Math.log2(best.f / 440) : null;
}

$('mKind').onchange = () => {};
$('mDelete').onclick = () => {
  if (state.editingId) removeAnnotation(state.project, state.editingId);
  state.editingId = null;
  sheet.selectedId = null;
  $('modal').classList.add('hidden');
  touched();
};
$('mExplode').onclick = () => {
  if (state.editingId) explodeToParts(state.project, state.editingId);
  state.editingId = null;
  sheet.selectedId = null;
  $('modal').classList.add('hidden');
  touched();
};
$('mCancel').onclick = () => {
  state.pendingPlace = null;
  $('modal').classList.add('hidden');
};

function renderInspector() {
  const box = $('inspector');
  const a = state.project.annotations.find((x) => x.id === state.editingId);
  if (!a) {
    box.className = 'hint';
    box.textContent =
      'Click anywhere on a part to place a mark exactly there. Click a mark to ' +
      'select it, drag to move, double-click to retype.';
    return;
  }
  box.className = '';
  const scopeName =
    a.scope === GLOBAL
      ? 'Full Score'
      : state.project.parts.find((p) => p.id === a.scope)?.name || 'unknown part';
  box.innerHTML = `
    <div class="item selected" style="cursor:default">
      <div class="grow">
        <div class="nm">${escapeHtml(a.text)}</div>
        <div class="meta">${KINDS[a.kind]?.label || a.kind} · ${escapeHtml(scopeName)} · ${a.t.toFixed(2)}s${
          a.t2 != null ? `–${a.t2.toFixed(2)}s` : ''
        }</div>
      </div>
    </div>
    <div class="row wrap" style="margin-top:8px">
      <button class="sm" id="insEdit">Edit…</button>
      <button class="sm" id="insDup">Duplicate</button>
      <button class="sm danger" id="insDel">Delete</button>
    </div>`;
  $('insEdit').onclick = () => openModal(a.id);
  $('insDup').onclick = () => {
    const copy = addAnnotation(state.project, { ...a, t: a.t + 0.5 });
    sheet.selectedId = copy.id;
    state.editingId = copy.id;
    touched();
  };
  $('insDel').onclick = () => {
    removeAnnotation(state.project, a.id);
    state.editingId = null;
    sheet.selectedId = null;
    touched();
  };
}

function renderMarks() {
  const box = $('markList');
  box.innerHTML = '';
  let marks = allSorted(state.project);
  if (state.filter === 'global') marks = marks.filter((a) => a.scope === GLOBAL);
  if (!marks.length) {
    box.innerHTML = '<div class="hint">Nothing yet.</div>';
    return;
  }
  for (const a of marks) {
    const row = document.createElement('button');
    row.className = 'item' + (a.id === state.editingId ? ' selected' : '');
    const grow = document.createElement('div');
    grow.className = 'grow';
    const nm = document.createElement('div');
    nm.className = 'nm';
    nm.textContent = a.text || '(empty)';
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = `${a.t.toFixed(2)}s · ${KINDS[a.kind]?.label || a.kind}`;
    grow.append(nm, meta);
    const tag = document.createElement('span');
    tag.className = 'tag' + (a.scope === GLOBAL ? ' global' : '');
    tag.textContent =
      a.scope === GLOBAL
        ? 'score'
        : (state.project.parts.find((p) => p.id === a.scope)?.name || '?').slice(0, 10);
    row.append(grow, tag);
    row.onclick = () => {
      state.editingId = a.id;
      sheet.selectedId = a.id;
      if (sheet.view === 'galley' && (a.t < sheet.t0 || a.t > sheet.t0 + sheet.tSpan)) {
        sheet.t0 = Math.max(0, a.t - sheet.tSpan / 3);
      }
      sheet.draw();
      renderInspector();
      renderMarks();
    };
    box.append(row);
  }
}

$('filterAll').onclick = () => {
  state.filter = 'all';
  renderMarks();
};
$('filterGlobal').onclick = () => {
  state.filter = 'global';
  renderMarks();
};

/* ------------------------------------------------------------------ *
 * Engrave — spacing, breaks, furniture
 * ------------------------------------------------------------------ */

const spacing = [
  ['pxPerSecond', 'Horizontal spacing', (v) => `${v} px per second`],
  ['staffHeight', 'Staff height', (v) => `${v} px`],
  ['staffGap', 'Gap between parts', (v) => `${v} px`],
  ['systemGap', 'Gap between systems', (v) => `${v} px`],
  ['ribbonScale', 'Ribbon thickness', (v) => `${v} px at loudest`],
];
for (const [key, label, fmt] of spacing) {
  $(key).oninput = () => {
    const v = parseFloat($(key).value);
    editedLayout()[key] = v;
    $(`${key}Label`).textContent = `${label} — ${fmt(v)}`;
    afterLayoutChange();
  };
}

for (const key of ['showPartLabels', 'showStaffLines', 'showTitle', 'showPageNumbers']) {
  $(key).onchange = () => {
    editedLayout()[key] = $(key).checked;
    afterLayoutChange();
  };
}

/* ---- page setup ---- */

$('pageSize').innerHTML = Object.entries(PAGE_SIZES)
  .map(([k, v]) => `<option value="${k}">${v.label}</option>`)
  .join('');

$('pageSize').onchange = () => {
  editedLayout().pageSize = $('pageSize').value;
  afterLayoutChange();
};
$('orientation').onchange = () => {
  editedLayout().orientation = $('orientation').value;
  afterLayoutChange();
};
$('margin').oninput = () => {
  const v = parseFloat($('margin').value);
  editedLayout().margin = v;
  $('marginLabel').textContent = `Margins — ${v} px`;
  afterLayoutChange();
};

/**
 * Switching the edited layout also shows it, so the effect of a setting is
 * visible while it is being changed rather than after switching views.
 */
$('layoutProfile').onchange = () => {
  const key = editedProfile();
  if (key === 'score') {
    $('targetSelect').value = 'score';
  } else {
    const first = orderedParts(state.project.parts, layout())[0];
    if (first) $('targetSelect').value = first.id;
  }
  sheet.target = $('targetSelect').value;
  syncControls();
  sheet.draw();
  renderBreaks();
};

$('copyProfile').onclick = () => {
  const set = ensureLayouts();
  const from = editedProfile();
  const to = from === 'score' ? 'parts' : 'score';
  set[to] = { ...set[from] };
  markDirty();
  $('copyProfile').textContent = `Copied to ${to === 'score' ? 'Full Score' : 'Parts'}`;
  setTimeout(() => ($('copyProfile').textContent = 'Copy these settings to the other layout'), 1400);
};

function afterLayoutChange() {
  markDirty();
  $('pageDims').textContent = pageDimsText();
  sheet.draw();
}

function pageDimsText() {
  const g = pageGeometry(editedLayout());
  return `Page ${g.w} × ${g.h} px at 96 dpi · ${g.margin} px margins`;
}

sheet.addEventListener('placeBreak', (ev) => {
  openBreakModal(null, ev.detail.t);
});
sheet.addEventListener('selectBreak', (ev) => {
  state.editingBreakId = ev.detail;
  renderBreaks();
});
sheet.addEventListener('breakEdited', () => {
  markDirty();
  renderBreaks();
});

function openBreakModal(id, t) {
  const b = id ? (state.project.breaks || []).find((x) => x.id === id) : null;
  state.editingBreakId = id;
  $('breakTitle').textContent = b ? 'Edit break' : 'Create break';
  scopeOptions($('bScope'), b ? b.scope : $('breakScope').value || GLOBAL);
  $('bKind').value = b ? b.kind : 'system';
  $('bTime').value = (b ? b.t : t || 0).toFixed(2);
  $('bDelete').classList.toggle('hidden', !b);
  $('breakModal').classList.remove('hidden');
}

$('bSave').onclick = () => {
  const spec = {
    kind: $('bKind').value,
    scope: $('bScope').value,
    t: parseFloat($('bTime').value) || 0,
  };
  if (state.editingBreakId) {
    const b = (state.project.breaks || []).find((x) => x.id === state.editingBreakId);
    if (b) Object.assign(b, spec);
  } else {
    const made = addBreak(state.project, spec);
    state.editingBreakId = made.id;
    sheet.selectedBreakId = made.id;
  }
  $('breakModal').classList.add('hidden');
  touched();
};

$('bDelete').onclick = () => {
  if (state.editingBreakId) removeBreak(state.project, state.editingBreakId);
  state.editingBreakId = null;
  sheet.selectedBreakId = null;
  $('breakModal').classList.add('hidden');
  touched();
};

$('bCancel').onclick = () => $('breakModal').classList.add('hidden');

function breakTime() {
  // The selected mark is usually what the break is meant to sit against.
  const a = state.project.annotations.find((x) => x.id === state.editingId);
  return a ? a.t : sheet.cursorTime();
}

$('addSystemBreak').onclick = () => {
  addBreak(state.project, { kind: 'system', t: breakTime(), scope: $('breakScope').value });
  touched();
};
$('addPageBreak').onclick = () => {
  addBreak(state.project, { kind: 'page', t: breakTime(), scope: $('breakScope').value });
  touched();
};

function renderBreaks() {
  const box = $('breakList');
  box.innerHTML = '';
  const list = (state.project.breaks || []).slice().sort((a, b) => a.t - b.t);
  if (!list.length) {
    box.innerHTML = '<div class="hint">No breaks — the score casts off automatically.</div>';
    return;
  }
  for (const b of list) {
    const row = document.createElement('div');
    row.className = 'item' + (b.id === state.editingBreakId ? ' selected' : '');
    const grow = document.createElement('div');
    grow.className = 'grow';
    grow.onclick = () => {
      state.editingBreakId = b.id;
      sheet.selectedBreakId = b.id;
      if (sheet.view === 'galley' && (b.t < sheet.t0 || b.t > sheet.t0 + sheet.tSpan)) {
        sheet.t0 = Math.max(0, b.t - sheet.tSpan / 3);
      }
      sheet.draw();
      renderBreaks();
    };
    grow.ondblclick = () => openBreakModal(b.id);
    const nm = document.createElement('div');
    nm.className = 'nm';
    nm.textContent = b.kind === 'page' ? 'Page break' : 'System break';
    const meta = document.createElement('div');
    meta.className = 'meta';
    const who =
      b.scope === GLOBAL
        ? 'Full Score'
        : state.project.parts.find((p) => p.id === b.scope)?.name || '?';
    meta.textContent = `${b.t.toFixed(2)}s · ${who}`;
    grow.append(nm, meta);
    const del = document.createElement('button');
    del.className = 'sm';
    del.textContent = '✕';
    del.onclick = () => {
      removeBreak(state.project, b.id);
      touched();
    };
    row.append(grow, del);
    box.append(row);
  }
}

/* ------------------------------------------------------------------ *
 * View
 * ------------------------------------------------------------------ */

function setView(v) {
  sheet.view = v;
  $('pageViewBtn').classList.toggle('active', v === 'page');
  $('galleyViewBtn').classList.toggle('active', v === 'galley');
  $('zoomHint').textContent =
    v === 'page' ? 'scroll to page · ⌘-scroll to zoom' : 'scroll to zoom · shift-scroll to pan';
  sheet.fitAll();
}
$('pageViewBtn').onclick = () => setView('page');
$('galleyViewBtn').onclick = () => setView('galley');
$('fitBtn').onclick = () => sheet.fitAll();

/* ------------------------------------------------------------------ *
 * Save / open / export
 * ------------------------------------------------------------------ */

function markDirty() {
  state.dirty = true;
  document.title = 'Engraver •';
}

function touched() {
  markDirty();
  refresh();
}

function refresh() {
  sheet.setProject(state.project);
  renderParts();
  renderTargetSelect();
  scopeOptions($('breakScope'), $('breakScope').value || GLOBAL);
  renderInspector();
  renderMarks();
  renderBreaks();
  if (state.score) showIssues(validate(state.project, state.score));
  sheet.draw();
}

$('saveBtn').onclick = async () => {
  const name = $('projectName').value.trim() || 'untitled';
  const res = await fetch(`/api/projects/${encodeURIComponent(name)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(state.project),
  });
  if (res.ok) {
    state.dirty = false;
    document.title = 'Engraver';
    $('saveBtn').textContent = 'Saved';
    setTimeout(() => ($('saveBtn').textContent = 'Save'), 1200);
  } else {
    alert(`Could not save: ${(await res.json()).error}`);
  }
};

$('openBtn').onclick = async () => {
  const list = await (await fetch('/api/projects')).json();
  const box = $('projectList');
  box.innerHTML = list.length ? '' : '<div class="hint">No saved projects yet.</div>';
  for (const p of list) {
    const row = document.createElement('button');
    row.className = 'item';
    row.innerHTML = `<div class="grow"><div class="nm">${escapeHtml(p.name)}</div>
      <div class="meta">${escapeHtml(p.score || 'no score')} · ${p.parts} parts · ${p.annotations} marks</div></div>`;
    row.onclick = async () => {
      const doc = await (await fetch(`/api/projects/${encodeURIComponent(p.name)}`)).json();
      state.project = doc;
      if (!state.project.breaks) state.project.breaks = [];
      ensureLayouts();
      $('projectName').value = p.name;
      $('openModal').classList.add('hidden');
      syncControls();
      refresh();
      showIssues(
        state.score
          ? validate(doc, state.score)
          : [{ level: 'warn', message: 'Load the matching score to see the systems.' }]
      );
    };
    box.append(row);
  }
  $('openModal').classList.remove('hidden');
};
$('openCancel').onclick = () => $('openModal').classList.add('hidden');

function openExport(mode) {
  state.mode = mode;
  $('exportTitle').textContent = mode === 'print' ? 'Print' : 'Export';
  $('exportActions').classList.toggle('hidden', mode === 'print');
  $('expPrintGo').classList.toggle('hidden', mode !== 'print');
  $('exportModal').classList.remove('hidden');
}
$('exportBtn').onclick = () => openExport('export');
$('printBtn').onclick = () => {
  if (!state.score) return alert('Load the score first.');
  openExport('print');
};
$('expCancel').onclick = () => $('exportModal').classList.add('hidden');
$('expPrintGo').onclick = () => {
  openPrintView(state.score, state.project, $('expWhich').value, $('projectName').value.trim());
  $('exportModal').classList.add('hidden');
};

function download(obj, filename) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
const baseName = () => ($('projectName').value.trim() || 'engraving').replace(/\s+/g, '_');

$('expProject').onclick = () => {
  download(state.project, `${baseName()}.engraving.json`);
  $('exportModal').classList.add('hidden');
};
$('expPartMap').onclick = () => {
  download(toPartMap(state.project), `${baseName()}_parts.json`);
  $('exportModal').classList.add('hidden');
};
$('expSvg').onclick = () => {
  if (!state.score) return alert('Load the score first.');
  downloadSVG(state.score, state.project, $('expWhich').value, $('projectName').value.trim());
  $('exportModal').classList.add('hidden');
};

/** Push the edited profile's values back into the controls. */
function syncControls() {
  const l = editedLayout();
  for (const [key, label, fmt] of spacing) {
    if (l[key] != null) $(key).value = l[key];
    $(`${key}Label`).textContent = `${label} — ${fmt(parseFloat($(key).value))}`;
  }
  for (const key of ['showPartLabels', 'showStaffLines', 'showTitle', 'showPageNumbers']) {
    $(key).checked = !!l[key];
  }
  $('pageSize').value = l.pageSize || 'a4';
  $('orientation').value = l.orientation || 'landscape';
  $('margin').value = l.margin ?? 54;
  $('marginLabel').textContent = `Margins — ${l.margin ?? 54} px`;
  $('pageDims').textContent = pageDimsText();
  $('lowestAtBottom').checked = l.lowestAtBottom !== false;
}

window.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape') {
    for (const id of ['modal', 'openModal', 'exportModal', 'breakModal']) {
      $(id).classList.add('hidden');
    }
  }
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '')) return;
  if (ev.key === 'Delete' || ev.key === 'Backspace') {
    if (state.editingId) {
      removeAnnotation(state.project, state.editingId);
      state.editingId = null;
      sheet.selectedId = null;
      touched();
    } else if (state.editingBreakId) {
      removeBreak(state.project, state.editingBreakId);
      state.editingBreakId = null;
      sheet.selectedBreakId = null;
      touched();
    }
  }
  if (ev.key === 's' && (ev.metaKey || ev.ctrlKey)) {
    ev.preventDefault();
    $('saveBtn').click();
  }
});

window.addEventListener('beforeunload', (ev) => {
  if (state.dirty) {
    ev.preventDefault();
    ev.returnValue = '';
  }
});

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])
  );
}

syncControls();
refresh();
