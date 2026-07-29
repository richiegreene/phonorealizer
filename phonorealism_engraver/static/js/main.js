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

import { loadScoreFile, defaultParts, partLabel, partPartials } from '/shared/score.js';
import {
  GLOBAL, KINDS, KIND_ORDER, PLACES, ALIGNMENTS, makeProject, validate,
  addAnnotation, removeAnnotation, updateAnnotation, explodeToParts,
  setPlacement, allSorted, toPartMap,
} from '/shared/annotations.js';
import {
  defaultLayouts, layoutFor, profileKeyFor, pageGeometry, PAGE_SIZES,
  addBreak, removeBreak, orderedParts,
} from '/shared/layout.js';
import {
  ScorePlayer, scheduleCountIn, timbreName, drawTimbreWave, TIMBRE_MAX,
} from '/shared/synth.js';
import { EngraveCanvas } from './canvas.js';
import { openPrintView, downloadSVG } from './print.js';

const $ = (id) => document.getElementById(id);

const state = {
  score: null,
  project: makeProject(),
  filter: 'all',
  editingId: null,
  /** Every selected mark. `editingId` is the one the panel describes. */
  selection: [],
  pendingPlace: null,
  editingBreakId: null,
  dirty: false,
  mode: 'export', // or 'print', for the shared dialogue

  /* --- playback --- */
  timbre: 100, // 0 sine, 100 triangle, 200 saw, 300 square
  balance: 0, // 0 the engraved layout alone, 1 everything else
  volume: 0.8,
  playing: false,
  /** Where the playhead sits when stopped, and where Play resumes from. */
  playFrom: 0,
  /** What the rendered buffers were rendered for; see renderKey(). */
  renderedFor: null,
  rendering: false,
  /** How much of the score got rendered — capped on very long works. */
  playDuration: 0,
  /** Whether there is anything on the far side of the balance fader. */
  hasEnsemble: false,
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
      {
        write: 'click to place a mark · shift-click to select several',
        engrave: 'click to place a break · drag a flag to move it',
        play: 'click the score to play from there · space to start and stop',
      }[tab.dataset.tab] ||
      (sheet.view === 'page'
        ? 'scroll to page · ⌘-scroll to zoom'
        : 'scroll to zoom · shift-scroll to pan');
    // The wave preview cannot be drawn while its pane is hidden — a canvas with
    // no layout has no size to draw into.
    if (tab.dataset.tab === 'play') {
      drawWave();
      updateMixControls();
      updateClock();
    }
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
    // Anything rendered for the previous score is now wrong, and playback of it
    // has to stop before its buffers are replaced.
    if (state.playing) pausePlayback();
    scoreEpoch += 1;
    state.renderedFor = null;
    state.playDuration = 0;
    state.playFrom = 0;
    sheet.playhead = null;
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
    setPlayHint('Press Play to hear this through the performers’ own synthesis.');
    updateClock();
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
  const nick = prompt(
    'Nickname, used from the second system on (optional)',
    suggestNick(name)
  );
  const spec = prompt(
    `Which partials? 1–${state.score.partials.length}. Ranges allowed, e.g. "3, 7, 12-14"`
  );
  if (!spec) return;
  const partials = parseSpec(spec, state.score.partials.length);
  if (!partials.length) return alert('No valid partial numbers in that.');
  state.project.parts.push({
    id: `g${Date.now().toString(36)}`,
    name: name.trim(),
    nick: (nick || '').trim(),
    partials,
  });
  touched();
};

/**
 * A plausible short form to offer for a nickname: the head of the word, plus
 * any number that distinguishes one desk from another. Only a suggestion —
 * abbreviating an instrument name properly is a judgement, not a rule.
 */
function suggestNick(name) {
  const s = String(name).trim();
  const num = s.match(/\d+\s*$/);
  const word = s.replace(/\s*\d+\s*$/, '').trim();
  if (!word) return s;
  const short = word.length <= 4 ? word : `${word.slice(0, 3)}.`;
  return num ? `${short} ${num[0].trim()}` : short;
}

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
    const bits = [];
    if (part.nick) bits.push(`“${part.nick}” after the first system`);
    bits.push(part.partials.join(', '));
    if (state.score) bits.push(partLabel(state.score, part));
    meta.textContent = bits.join(' · ');
    grow.append(nm, meta);
    grow.onclick = () => {
      const n = prompt('Part name', part.name);
      if (n) part.name = n.trim();
      const k = prompt(
        'Nickname, used from the second system on (blank to keep the full name)',
        part.nick || suggestNick(part.name)
      );
      if (k != null) part.nick = k.trim();
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
  // Playback follows viewing too: what is auditioned is the layout on screen.
  // The mix is re-rendered on the next Play rather than mid-note.
  updateMixControls();
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
  state.editingId = ev.detail?.id ?? null;
  state.selection = ev.detail?.ids ?? [];
  renderInspector();
  renderMarks();
});
sheet.addEventListener('edited', () => {
  markDirty();
  renderInspector();
  renderMarks();
});

/** Select one mark from the panel side, keeping the canvas and state in step. */
function selectOnly(id) {
  sheet.selectedId = id;
  state.editingId = id;
  state.selection = id ? [id] : [];
}

/** The selected marks, in time order. */
function selectedMarks() {
  const ids = new Set(
    state.selection.length ? state.selection : state.editingId ? [state.editingId] : []
  );
  return allSorted(state.project).filter((a) => ids.has(a.id));
}

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
    $('mAlign').value = a.align || 'line';
  } else {
    const p = state.pendingPlace;
    $('mText').value = '';
    $('mKind').value = 'lyric';
    $('mTime').value = (p ? p.t : 0).toFixed(2);
    $('mTime2').value = '';
    $('mPlace').value = 'on';
    $('mAlign').value = 'line';
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
    align: $('mAlign').value,
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
    selectOnly(a.id);
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
  selectOnly(null);
  $('modal').classList.add('hidden');
  touched();
};
$('mExplode').onclick = () => {
  if (state.editingId) explodeToParts(state.project, state.editingId);
  selectOnly(null);
  $('modal').classList.add('hidden');
  touched();
};
$('mCancel').onclick = () => {
  state.pendingPlace = null;
  $('modal').classList.add('hidden');
};

/* ---- vertical alignment, on any number of marks at once ---- */

const ZONE_BUTTONS = [
  ['placeAbove', 'above'],
  ['placeWithin', 'on'],
  ['placeBelow', 'below'],
];

for (const [id, place] of ZONE_BUTTONS) {
  // A zone button both moves the marks into the zone and aligns them there:
  // asking for "below the staff" on a line of lyrics means one baseline, not
  // each word at its own height under its own partial.
  $(id).onclick = () => applyPlacement({ place, align: 'staff' });
}
$('alignStaff').onclick = () => applyPlacement({ align: 'staff' });
$('alignLine').onclick = () => applyPlacement({ align: 'line' });

function applyPlacement(spec) {
  const marks = selectedMarks();
  if (!marks.length) return;
  setPlacement(state.project, marks.map((m) => m.id), spec);
  touched();
}

/** Say what the alignment buttons would act on, and put them out of use if nothing. */
function renderAlignPanel(marks) {
  const n = marks.length;
  for (const [id] of ZONE_BUTTONS) $(id).disabled = !n;
  $('alignStaff').disabled = !n;
  $('alignLine').disabled = !n;

  if (!n) {
    $('alignScope').textContent =
      'Nothing selected. Shift-click marks on the score, or in the list below, ' +
      'to place several at once.';
    return;
  }
  const zones = [...new Set(marks.map((m) => PLACES[m.place] || m.place))];
  const aligns = [...new Set(marks.map((m) => ALIGNMENTS[m.align || 'line']))];
  $('alignScope').textContent =
    `${n === 1 ? 'One mark' : `${n} marks`} · ${zones.join(', ')} · ${aligns.join(', ')}` +
    // Where the zone actually is depends on whether the staff has slack to
    // spare, and it is worth saying which regime is in force rather than
    // leaving the difference to be discovered.
    (layout().normalizeHeights
      ? ' — this layout normalises heights, so above and below sit clear of the ribbon.'
      : ' — above and below sit at the head and foot of the staff. Normalise ' +
        'height per system to put them outside it.');
}

function renderInspector() {
  const box = $('inspector');
  const marks = selectedMarks();
  renderAlignPanel(marks);

  if (!marks.length) {
    box.className = 'hint';
    box.textContent =
      'Click anywhere on a part to place a mark exactly there. Click a mark to ' +
      'select it, drag to move, double-click to retype. Shift-click to select ' +
      'several and move or align them together.';
    return;
  }

  if (marks.length > 1) {
    // Deliberately no text or time field: the one thing that is safe to do to a
    // group is move it or format it, and both are gestures rather than fields.
    box.className = '';
    const from = marks[0].t;
    const to = marks[marks.length - 1].t;
    const kinds = [...new Set(marks.map((m) => KINDS[m.kind]?.label || m.kind))];
    box.innerHTML = `
      <div class="item selected" style="cursor:default">
        <div class="grow">
          <div class="nm">${marks.length} marks selected</div>
          <div class="meta">${from.toFixed(2)}–${to.toFixed(2)}s · ${escapeHtml(kinds.join(', '))}</div>
        </div>
      </div>
      <div class="row wrap" style="margin-top:8px">
        <button class="sm" id="insDup">Duplicate</button>
        <button class="sm danger" id="insDel">Delete all</button>
      </div>
      <div class="hint" style="margin-top:8px">
        Drag any one of them on the score to move the whole selection.
      </div>`;
    $('insDup').onclick = () => {
      const copies = marks.map((m) => addAnnotation(state.project, { ...m, t: m.t + 0.5 }));
      sheet.selectMany(copies.map((c) => c.id));
      state.selection = copies.map((c) => c.id);
      state.editingId = state.selection[state.selection.length - 1];
      touched();
    };
    $('insDel').onclick = () => {
      for (const m of marks) removeAnnotation(state.project, m.id);
      selectOnly(null);
      touched();
    };
    return;
  }

  const a = marks[0];
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
    selectOnly(copy.id);
    touched();
  };
  $('insDel').onclick = () => {
    removeAnnotation(state.project, a.id);
    selectOnly(null);
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
    row.className = 'item' + (state.selection.includes(a.id) ? ' selected' : '');
    const grow = document.createElement('div');
    grow.className = 'grow';
    const nm = document.createElement('div');
    nm.className = 'nm';
    nm.textContent = a.text || '(empty)';
    const meta = document.createElement('div');
    meta.className = 'meta';
    const zone = (a.align || 'line') === 'staff' ? `${PLACES[a.place]}, aligned` : PLACES[a.place];
    meta.textContent = `${a.t.toFixed(2)}s · ${KINDS[a.kind]?.label || a.kind} · ${zone}`;
    grow.append(nm, meta);
    const tag = document.createElement('span');
    tag.className = 'tag' + (a.scope === GLOBAL ? ' global' : '');
    tag.textContent =
      a.scope === GLOBAL
        ? 'score'
        : (state.project.parts.find((p) => p.id === a.scope)?.name || '?').slice(0, 10);
    row.append(grow, tag);
    row.onclick = (ev) => {
      // Shift-click here does what it does on the score, so a run of lyrics can
      // be gathered from whichever of the two is easier to hit.
      if (ev.shiftKey) {
        sheet.select(a.id, true);
      } else {
        selectOnly(a.id);
      }
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

/** The marks the list is currently showing — what Select all takes. */
function listedMarks() {
  const marks = allSorted(state.project);
  return state.filter === 'global' ? marks.filter((a) => a.scope === GLOBAL) : marks;
}

$('filterAll').onclick = () => {
  state.filter = 'all';
  renderMarks();
};
$('filterGlobal').onclick = () => {
  state.filter = 'global';
  renderMarks();
};
$('selectAllMarks').onclick = () => {
  sheet.selectMany(listedMarks().map((a) => a.id));
  renderMarks();
};

/* ------------------------------------------------------------------ *
 * Engrave — spacing, breaks, furniture
 * ------------------------------------------------------------------ */

const sliders = [
  ['pxPerSecond', 'Horizontal spacing', (v) => `${v} px per second`],
  ['staffHeight', 'Staff height', (v) => `${v} px`],
  ['staffGap', 'Gap between parts', (v) => `${v} px`],
  ['systemGap', 'Gap between systems', (v) => `${v} px`],
  ['ribbonScale', 'Ribbon thickness', (v) => `${v} px at loudest`],
  ['partLabelSize', 'Part name size', (v) => `${v} px`],
  ['labelWidth', 'Part name gutter', (v) => (v ? `${v} px` : 'none — names set over the music')],
];
for (const [key, label, fmt] of sliders) {
  $(key).oninput = () => {
    const v = parseFloat($(key).value);
    editedLayout()[key] = v;
    $(`${key}Label`).textContent = `${label} — ${fmt(v)}`;
    afterLayoutChange();
  };
}

for (const key of [
  'showPartLabels', 'showStaffOutline', 'showTitle', 'showPageNumbers',
  'normalizeHeights',
]) {
  $(key).onchange = () => {
    editedLayout()[key] = $(key).checked;
    updateSpacingHint();
    afterLayoutChange();
  };
}

function updateSpacingHint() {
  $('normalizeHint').textContent = $('normalizeHeights').checked
    ? 'Each staff is cropped to the pitch its part actually reaches in that ' +
      'system, and annotations stack in rows outside the ribbon so they cannot ' +
      'sit on it. The pitch scale itself is unchanged — only empty register goes.'
    : 'Every staff takes the full staff height, whether its part uses that ' +
      'much register or not.';
}

/* ---- grid rules ---- */

for (const key of ['rulesStyle', 'rulesLabels', 'pitchGrid']) {
  $(key).onchange = () => {
    editedLayout()[key] = $(key).value;
    updateGridLabels();
    afterLayoutChange();
  };
}
for (const key of ['rulesRate', 'rulesGroup', 'rulesTickPos', 'pitchGridOpacity']) {
  $(key).oninput = () => {
    editedLayout()[key] = parseFloat($(key).value);
    updateGridLabels();
    afterLayoutChange();
  };
}

/**
 * Describe the grid in the terms that matter: the vertical rate as a tempo and
 * the interval it implies, and which reading of the pitch lattice is drawn.
 * Controls that govern a style not currently chosen are put away rather than
 * left to be adjusted with no visible effect.
 */
function updateGridLabels() {
  const rate = parseFloat($('rulesRate').value) || 60;
  const group = parseFloat($('rulesGroup').value) || 0;
  const interval = 60 / rate;
  const style = $('rulesStyle').value;
  const pitch = $('pitchGrid').value;

  $('rulesRateLabel').textContent =
    `Rate — ${rate} bpm · a marker every ${interval < 1 ? `${(interval * 1000).toFixed(0)} ms` : `${interval.toFixed(2)} s`}`;
  $('rulesGroupLabel').textContent = group
    ? `Emphasise every ${group} · an accent every ${(interval * group).toFixed(2)} s`
    : 'Emphasise — off, an even grid';

  const pos = parseFloat($('rulesTickPos').value) || 0;
  $('rulesTickPosLabel').textContent = `Tick height — ${
    pos <= 0.001
      ? 'at the foot of the staff'
      : pos >= 0.999
        ? 'at the head of the staff'
        : `${Math.round(pos * 100)}% up the staff`
  }`;
  $('tickPosField').classList.toggle('hidden', style !== 'ticks');

  const alpha = parseFloat($('pitchGridOpacity').value) || 0;
  $('pitchGridOpacityLabel').textContent =
    `Chromatic region darkness — ${Math.round(alpha * 100)}%`;
  $('pitchOpacityField').classList.toggle(
    'hidden',
    pitch !== 'piano' && pitch !== 'pianoLines'
  );

  $('pitchGridHint').textContent =
    pitch === 'none'
      ? 'No pitch reference is drawn.'
      : pitch === 'semitones'
        ? 'A rule at every semitone, emphasised at each C: a partial’s pitch ' +
          'reads off the line it sits on.'
        : 'Chromatic regions shaded, each centred on its black note as on a ' +
          'piano roll' +
          (pitch === 'pianoLines'
            ? ', with a guideline down the middle of each at the semitone itself.'
            : '.');

  $('rulesHint').textContent =
    style === 'none' && $('rulesLabels').value === 'none'
      ? 'No time reference is drawn.'
      : 'Timestamps appear on the top staff of each system, at emphasised markers only.';
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
 * Play — auditioning the layout on screen
 *
 * Re-synthesis, the timbre morph and the scheduling all come from the shared
 * synth the performers hear through (`/shared/synth.js`), so what is auditioned
 * at the desk is what will be in their ears. A second renderer here would
 * eventually disagree with theirs, and the disagreement would surface as the
 * composer and the players hearing different music.
 *
 * Modelled on Dorico's Play mode: a transport, a playhead that travels through
 * the score, a view that follows it, and clicking the music to move it.
 * ------------------------------------------------------------------ */

/** Lazily built: an AudioContext may only be created from a user gesture. */
let audio = null;

/** Bumped when a different score is loaded, so rendered audio is not reused. */
let scoreEpoch = 0;

let wireScore = null;
let wireFor = null;
let raf = null;
let scrubbing = false;

function ensureAudio() {
  if (!audio) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    audio = { ctx, player: new ScorePlayer(ctx) };
    audio.player.setBalance(state.balance);
    audio.player.setVolume(state.volume);
  }
  if (audio.ctx.state === 'suspended') audio.ctx.resume();
  return audio;
}

/**
 * The score in the shape the renderer reads.
 *
 * Only the breakpoints: passing the parsed model would copy fields the worker
 * has no use for across the thread boundary on every render.
 */
function playbackScore() {
  if (!state.score) return null;
  if (wireFor !== state.score) {
    wireScore = {
      duration: state.score.duration,
      partials: state.score.partials.map((p) => ({ i: p.index, t: p.t, f: p.f, a: p.a })),
    };
    wireFor = state.score;
  }
  return wireScore;
}

/**
 * The partials the layout on screen is made of.
 *
 * Full Score plays everything. A part layout plays that part, with the rest of
 * the score on the far side of the balance fader — the same "me against
 * everyone else" split the performers' monitor mix is built from, which is why
 * the fader exists at all.
 */
function playedIndices() {
  if (!state.score) return [];
  if (sheet.target === 'score') return state.score.partials.map((p) => p.index);
  const part = state.project.parts.find((p) => p.id === sheet.target);
  return part ? partPartials(state.score, part).map((p) => p.index) : [];
}

/**
 * What the rendered buffers would have to match to still be usable.
 *
 * Keyed by what the sound actually depends on, so switching layout or timbre
 * re-renders and editing an annotation does not.
 */
function renderKey() {
  return `${scoreEpoch}|${state.timbre}|${playedIndices().join(',')}`;
}

function playDuration() {
  return state.playDuration || state.score?.duration || 0;
}

async function prepareAudio() {
  const wire = playbackScore();
  if (!wire || state.rendering) return false;
  const key = renderKey();
  if (state.renderedFor === key) return true;

  const { player } = ensureAudio();
  state.rendering = true;
  // Synthesis is roughly real-time-over-30, so a long score takes visible
  // seconds. Say so rather than appearing to hang.
  setPlayHint('Rendering the playback mix…');
  try {
    const r = await player.prepare(wire, playedIndices(), 0, state.timbre);
    state.renderedFor = key;
    state.playDuration = r.duration;
    state.hasEnsemble = r.ensemble;
    const notes = [];
    if (r.truncated) {
      notes.push(`Playback stops at ${Math.round(r.duration / 60)} minutes — the score is longer.`);
    }
    if (r.ensembleDropped) notes.push('The rest of the score was left out; it would not fit in memory.');
    setPlayHint(notes.join(' ') || `Ready · ${r.megabytes} MB rendered.`);
    updateMixControls();
    return true;
  } catch (err) {
    setPlayHint(`Could not render the playback mix: ${err.message}`);
    return false;
  } finally {
    state.rendering = false;
  }
}

/** Position in the score, taken from the audio clock rather than a timer. */
function playPosition() {
  const p = audio?.player;
  if (!p || p.startedAtCtxTime == null) return state.playFrom;
  return p.startOffset + (audio.ctx.currentTime - p.startedAtCtxTime);
}

async function startPlayback() {
  if (!state.score) return setPlayHint('Load a score to play it.');
  if (!(await prepareAudio())) return;
  const { ctx, player } = ensureAudio();

  // Reaching the end and pressing Play again starts over, rather than doing
  // nothing at a playhead already parked on the final barline.
  const from = state.playFrom >= playDuration() - 0.05 ? 0 : state.playFrom;
  const countIn = $('playCountIn').checked;
  const at = ctx.currentTime + (countIn ? 3 * 0.6 + 0.1 : 0.06);
  player.start(at, from);
  if (countIn) scheduleCountIn(ctx, at, 3, 0.6, player.master);

  state.playing = true;
  sheet.playhead = from;
  updateTransport();
  if (!raf) loop();
}

function pausePlayback() {
  if (audio) audio.player.stop();
  state.playing = false;
  updateTransport();
  sheet.draw();
}

/** Stop and leave the playhead where the sound got to, so Play resumes there. */
function stopPlayback() {
  state.playFrom = Math.max(0, Math.min(playDuration(), playPosition()));
  pausePlayback();
}

function finishPlayback() {
  state.playFrom = playDuration();
  sheet.playhead = state.playFrom;
  pausePlayback();
  updateClock();
}

async function seekTo(t) {
  const dur = playDuration();
  state.playFrom = Math.max(0, Math.min(dur || t, t));
  sheet.playhead = state.playFrom;
  if (state.playing && audio) {
    audio.player.stop();
    audio.player.start(audio.ctx.currentTime + 0.05, state.playFrom);
  }
  updateClock();
  sheet.draw();
}

function loop() {
  // Torn down rather than left spinning on every frame doing nothing, so a
  // stopped transport lets the tab idle.
  if (!state.playing) {
    raf = null;
    return;
  }
  raf = requestAnimationFrame(loop);
  const dur = playDuration();
  const pos = playPosition();
  if (dur && pos >= dur) return finishPlayback();

  // Negative while a count-in is running: the playhead waits at the downbeat
  // rather than reversing into the previous system.
  const shown = Math.max(0, pos);
  state.playFrom = shown;
  sheet.playhead = shown;
  if ($('playFollow').checked) sheet.followPlayhead();
  sheet.draw();
  updateClock(pos);
}

const clockText = (s) => {
  const t = Math.max(0, s);
  const m = Math.floor(t / 60);
  return `${m}:${(t - m * 60).toFixed(1).padStart(4, '0')}`;
};

function updateClock(raw = null) {
  const dur = playDuration();
  const pos = state.playFrom;
  $('playClock').textContent =
    raw != null && raw < 0 ? `–${Math.ceil(-raw)}` : clockText(pos);
  $('playOf').textContent = `/ ${clockText(dur)}`;
  if (!scrubbing) $('playScrub').value = dur > 0 ? pos / dur : 0;
}

function updateTransport() {
  $('playBtn').textContent = state.playing ? 'Pause' : 'Play';
  $('playBtn').classList.toggle('playing', state.playing);
}

function setPlayHint(text) {
  $('playHint').textContent = text;
}

/**
 * The balance fader only means something when there is something else to
 * balance against — playing the full score, there is not.
 */
function updateMixControls() {
  const solo = sheet.target !== 'score';
  $('playBalance').disabled = !solo || !state.hasEnsemble;
  const name =
    solo
      ? state.project.parts.find((p) => p.id === sheet.target)?.name || 'this part'
      : null;
  $('playBalanceLabel').textContent = solo
    ? `Balance — ${Math.round((1 - state.balance) * 100)}% ${name} / ${Math.round(state.balance * 100)}% the rest`
    : 'Balance — the full score is playing';
  $('playVolumeLabel').textContent = `Volume — ${Math.round(state.volume * 100)}%`;
  $('playMixHint').textContent = solo
    ? 'Fade the rest of the score in behind the part being engraved.'
    : 'Choose a part below the score to hear it against the rest.';
}

$('playBtn').onclick = () => (state.playing ? pausePlayback() : startPlayback());
$('stopBtn').onclick = () => stopPlayback();
$('rewindBtn').onclick = () => seekTo(0);

$('playScrub').oninput = () => {
  scrubbing = true;
  const dur = playDuration();
  state.playFrom = parseFloat($('playScrub').value) * dur;
  sheet.playhead = state.playFrom;
  updateClock();
  sheet.draw();
};
$('playScrub').onchange = () => {
  scrubbing = false;
  seekTo(state.playFrom);
};

$('playFollow').onchange = () => {
  if ($('playFollow').checked) {
    sheet.followPlayhead();
    sheet.draw();
  }
};

sheet.addEventListener('seek', (ev) => seekTo(ev.detail));

/* ---- timbre ---- */

const drawWave = () =>
  drawTimbreWave($('waveView'), state.timbre, { line: '#7ee0c0', axis: '#222a34' });

$('timbre').oninput = () => {
  state.timbre = parseFloat($('timbre').value);
  $('timbreLabel').textContent = timbreName(state.timbre);
  drawWave();
};

/**
 * Re-render on release rather than while dragging: each render is a pass over
 * the whole score, and a dragged slider would queue dozens of them.
 */
$('timbre').onchange = async () => {
  if (!state.score) return;
  if (!state.playing) return void prepareAudio();
  // Pick playback up where it left off, so the change is heard rather than
  // described.
  const at = Math.max(0, playPosition());
  audio.player.stop();
  if (await prepareAudio()) {
    if (state.playing) audio.player.start(audio.ctx.currentTime + 0.05, at);
  }
};

$('playBalance').oninput = () => {
  state.balance = parseFloat($('playBalance').value);
  if (audio) audio.player.setBalance(state.balance);
  updateMixControls();
};
$('playVolume').oninput = () => {
  state.volume = parseFloat($('playVolume').value);
  if (audio) audio.player.setVolume(state.volume);
  updateMixControls();
};

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
  // Drop anything that has gone since the selection was made — a mark deleted
  // from the list, or a whole project opened over the top of this one.
  const live = new Set((state.project.annotations || []).map((a) => a.id));
  state.selection = state.selection.filter((id) => live.has(id));
  if (state.editingId && !live.has(state.editingId)) state.editingId = null;
  sheet.selection = new Set(state.selection);

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
  for (const [key, label, fmt] of sliders) {
    if (l[key] != null) $(key).value = l[key];
    $(`${key}Label`).textContent = `${label} — ${fmt(parseFloat($(key).value))}`;
  }
  for (const key of [
    'showPartLabels', 'showStaffOutline', 'showTitle', 'showPageNumbers',
    'normalizeHeights',
  ]) {
    $(key).checked = !!l[key];
  }
  updateSpacingHint();
  // 'grid' has been withdrawn; a project saved with it reads as barlines.
  $('rulesStyle').value = l.rulesStyle === 'grid' ? 'barlines' : l.rulesStyle || 'none';
  $('rulesRate').value = l.rulesRate ?? 60;
  $('rulesGroup').value = l.rulesGroup ?? 4;
  $('rulesTickPos').value = l.rulesTickPos ?? 0;
  $('rulesLabels').value = l.rulesLabels || 'seconds';
  $('pitchGrid').value = l.pitchGrid || 'none';
  $('pitchGridOpacity').value = l.pitchGridOpacity ?? 0.1;
  updateGridLabels();
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
  // Space starts and stops playback, as it does in Dorico. Only in Play mode, so
  // it cannot surprise anyone mid-edit.
  if (ev.key === ' ' && sheet.mode === 'play') {
    ev.preventDefault();
    if (state.playing) pausePlayback();
    else startPlayback();
    return;
  }
  if (ev.key === 'a' && (ev.metaKey || ev.ctrlKey) && sheet.mode === 'write') {
    ev.preventDefault();
    sheet.selectMany(listedMarks().map((a) => a.id));
    renderMarks();
    return;
  }
  if (ev.key === 'Delete' || ev.key === 'Backspace') {
    const marks = selectedMarks();
    if (marks.length) {
      for (const m of marks) removeAnnotation(state.project, m.id);
      selectOnly(null);
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
$('timbreLabel').textContent = timbreName(state.timbre);
updateTransport();
updateClock();
updateMixControls();
