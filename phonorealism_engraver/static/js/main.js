/*
 * main.js — engraver application wiring.
 *
 * The score is read in the browser by the shared reader, exactly as the
 * conductor page reads it, so partial numbering is guaranteed identical
 * between the two applications. The engraver owns the part map; the conductor
 * imports what this writes.
 */

import { loadScoreFile, defaultParts, partLabel } from '/shared/score.js';
import {
  GLOBAL, KINDS, KIND_ORDER, makeProject, validate,
  addAnnotation, removeAnnotation, updateAnnotation, explodeToParts,
  allSorted, toPartMap, fromPartMap,
} from '/shared/annotations.js';
import { EngraveCanvas } from './canvas.js';
import { openPrintView, downloadSVG } from './print.js';

const $ = (id) => document.getElementById(id);

const state = {
  score: null,
  project: makeProject(),
  filter: 'all',
  editingId: null,
  pendingPlace: null,
  dirty: false,
};

const sheet = new EngraveCanvas($('sheet'));

/* ------------------------------------------------------------------ *
 * Score loading
 * ------------------------------------------------------------------ */

$('loadScoreBtn').onclick = () => $('scoreFile').click();

$('scoreFile').onchange = async () => {
  const file = $('scoreFile').files[0];
  if (!file) return;
  try {
    const score = await loadScoreFile(file);
    state.score = score;
    // Keep an existing part map if one is loaded — the point of canonical
    // numbering is that a map survives a re-export of the same music.
    if (!state.project.parts.length) {
      state.project = makeProject(score, defaultParts(score).map(stripAuto));
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
    showIssues([{ level: 'error', message: err.message }]);
  }
};

const stripAuto = (p) => ({ id: p.id, name: p.name, partials: p.partials });

/* ------------------------------------------------------------------ *
 * Issues banner
 * ------------------------------------------------------------------ */

function showIssues(issues) {
  const box = $('issues');
  if (!issues.length) {
    box.classList.add('hidden');
    box.innerHTML = '';
    return;
  }
  box.classList.remove('hidden');
  box.innerHTML = issues
    .map((i) => `<div class="${i.level === 'warn' ? 'warn' : ''}">${i.message}</div>`)
    .join('');
}

/* ------------------------------------------------------------------ *
 * Parts
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
  for (const part of state.project.parts) {
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

function renderSoloSelect() {
  const sel = $('soloPart');
  const cur = sel.value;
  sel.innerHTML = '<option value="">All parts</option>';
  for (const p of state.project.parts) {
    const o = document.createElement('option');
    o.value = p.id;
    o.textContent = `Only: ${p.name}`;
    sel.append(o);
  }
  sel.value = cur;
}

$('soloPart').onchange = () => {
  sheet.soloPart = $('soloPart').value || null;
  sheet.draw();
};

/* ------------------------------------------------------------------ *
 * Annotations
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

function openModal(id) {
  const m = $('modal');
  const a = id ? state.project.annotations.find((x) => x.id === id) : null;
  state.editingId = id;

  $('modalTitle').textContent = a ? 'Edit annotation' : 'New annotation';
  $('mKind').innerHTML = KIND_ORDER.map(
    (k) => `<option value="${k}">${KINDS[k].label}</option>`
  ).join('');
  $('mScope').innerHTML =
    `<option value="${GLOBAL}">All parts at once</option>` +
    state.project.parts.map((p) => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');

  if (a) {
    $('mText').value = a.text;
    $('mKind').value = a.kind;
    $('mScope').value = a.scope;
    $('mTime').value = a.t.toFixed(2);
    $('mTime2').value = a.t2 == null ? '' : a.t2.toFixed(2);
    $('mPlace').value = a.place;
  } else {
    const p = state.pendingPlace;
    $('mText').value = '';
    $('mKind').value = 'lyric';
    $('mScope').value = p ? p.partId : GLOBAL;
    $('mTime').value = (p ? p.t : 0).toFixed(2);
    $('mTime2').value = '';
    $('mPlace').value = KINDS.lyric.place;
  }
  $('mDelete').classList.toggle('hidden', !a);
  $('mExplode').classList.toggle('hidden', !a || a.scope !== GLOBAL);

  m.classList.remove('hidden');
  $('mText').focus();
}

$('mKind').onchange = () => {
  const def = KINDS[$('mKind').value];
  if (def) $('mPlace').value = def.place;
};

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
    // Place it where the click landed, as an offset from the sounding line.
    if (state.pendingPlace) a.dy = 0;
    state.editingId = a.id;
    sheet.selectedId = a.id;
  }
  state.pendingPlace = null;
  $('modal').classList.add('hidden');
  touched();
};

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
      'Click an empty spot on a system to place a mark. Click a mark to select it, ' +
      'drag to move, double-click to retype.';
    return;
  }
  box.className = '';
  const scopeName =
    a.scope === GLOBAL
      ? 'all parts'
      : state.project.parts.find((p) => p.id === a.scope)?.name || 'unknown part';
  box.innerHTML = `
    <div class="item selected" style="cursor:default">
      <div class="grow">
        <div class="nm">${escapeHtml(a.text)}</div>
        <div class="meta">${KINDS[a.kind]?.label || a.kind} · ${escapeHtml(scopeName)} · ${a.t.toFixed(2)}s${
          a.t2 != null ? `–${a.t2.toFixed(2)}s` : ''
        } · ${a.place}</div>
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
        ? 'all'
        : (state.project.parts.find((p) => p.id === a.scope)?.name || '?').slice(0, 10);
    row.append(grow, tag);
    row.onclick = () => {
      state.editingId = a.id;
      sheet.selectedId = a.id;
      // Bring the mark into view if it is off-screen.
      if (a.t < sheet.t0 || a.t > sheet.t0 + sheet.tSpan) {
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
  renderSoloSelect();
  renderInspector();
  renderMarks();
  if (state.score) showIssues(validate(state.project, state.score));
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
      $('projectName').value = p.name;
      $('openModal').classList.add('hidden');
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

$('exportBtn').onclick = () => $('exportModal').classList.remove('hidden');
$('expCancel').onclick = () => $('exportModal').classList.add('hidden');

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
  downloadSVG(state.score, state.project, { title: $('projectName').value.trim() });
  $('exportModal').classList.add('hidden');
};

$('printBtn').onclick = () => {
  if (!state.score) return alert('Load the score first.');
  openPrintView(state.score, state.project, { title: $('projectName').value.trim() });
};

/* ------------------------------------------------------------------ *
 * View controls
 * ------------------------------------------------------------------ */

$('fitBtn').onclick = () => sheet.fitAll();
$('systemHeight').oninput = () => {
  sheet.systemHeight = parseFloat($('systemHeight').value);
  sheet.draw();
};
$('ribbonScale').oninput = () => {
  sheet.ribbonScale = parseFloat($('ribbonScale').value);
  sheet.draw();
};

window.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape') {
    $('modal').classList.add('hidden');
    $('openModal').classList.add('hidden');
    $('exportModal').classList.add('hidden');
  }
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
  if (typing) return;
  if ((ev.key === 'Delete' || ev.key === 'Backspace') && state.editingId) {
    removeAnnotation(state.project, state.editingId);
    state.editingId = null;
    sheet.selectedId = null;
    touched();
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

refresh();