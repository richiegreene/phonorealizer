# Phonorealism Engraver

Sets text against a phonorealism score — lyrics, expression markings, rehearsal
marks — on one part at a time or on every part at once, and engraves the result
either to printed pages or into the performers' scrolling display.

Reads justidraw `.sav` and phonorealizer CSV. Owns the part map that
[`phonorealism_web`](../phonorealism_web) imports.

```bash
cd phonorealism_engraver
./run.command                 # http://127.0.0.1:8200
```

Local only by default — this is a desk tool, not something performers join.

---

## Two decisions worth knowing

**Annotations live in a sidecar, never in the `.sav`.** Your justidraw files are
the one irreplaceable artifact in this project, and round-tripping them through
a foreign writer risks corrupting a composition for no benefit. A sidecar also
survives re-exporting the score from the modifier.

**Everything is anchored in time and cents, not pixels.** Seconds, so a mark
stays correct when the engraver zooms, when the performer app scrolls at a
different rate, and when a printed page breaks somewhere else. Cents for the
vertical nudge, so a lyric glued to a line travels with it as the pitch scale
changes — a pixel offset would drift off its partial the moment the view
rescaled.

## Three modes

Organised as Dorico is, because the vocabulary is already in use: what you are
doing decides what the panel offers.

**Setup** names the parts. Load a score and every partial becomes its own part;
replace those with real ones — *New part…* takes `3, 7, 12-14`. Each part gets a
**staff**: a band showing its partials in the same ribbon notation the players
read, height as pitch and thickness as amplitude.

Parts are laid out **lowest at the bottom** by default, so partial 1 sits on the
bottom staff and the spectrum reads upward as in a conventional score.

Each staff scales its pitch axis to its own part. A score spanning partial 1 at
400 Hz and partial 32 at 19 kHz covers five octaves; one shared axis would
compress every line into a flat thread.

**Write** places the marks. Click anywhere on a staff and the mark lands exactly
there — nothing is auto-positioned, because where a mark sits is an engraving
decision. Click to select, drag to move, double-click to retype. *Applies to*
chooses one part or **Full Score**; Full Score marks are drawn on every staff in
green, so "simultaneously" is visible rather than implied. *Split to parts* turns
one into editable copies when they need to diverge. An **Until** time makes it a
span with a continuation line, for *cresc.* or a held direction.

**Engrave** controls how it sits on the page:

| | |
| --- | --- |
| **Page setup** | paper size, orientation, margins |
| **Note spacing** | how much width a second of music occupies — wider casts off into more systems |
| **Staff spacing** | staff height, gap between parts, gap between systems, ribbon thickness |
| **Breaks** | *Create System Break* / *Create Page Break*, scoped to Full Score or one part |
| **Page furniture** | part names, staff rules, title, page numbers — all off but part names |

### Two layouts, engraved separately

Everything in Page setup and the spacing groups belongs to **one layout**, chosen
by *Editing layout* at the top of the tab. A conductor's score and a player's
part are engraved differently on purpose: the score has to fit every part on a
page and can afford to be tight, while a part is read from a stand at a distance
and wants room. Sharing one set of values would force a compromise that suits
neither.

So the score can be tight landscape while the parts are spacious portrait, and a
single export run emits each at its own size. Defaults reflect that — the score
starts at 64 px staves with 8 px between them, the parts at 132 and 14.

*Copy these settings to the other layout* pushes one profile onto the other when
you do want them to match. Changing the edited layout also switches the view to
it, so a setting shows its effect as you change it rather than afterwards.

Profiles are keyed by target, so giving one individual part its own profile later
needs no change to the file format. Part ordering is deliberately not per-layout:
it describes the work, not one view of it.

Marks are clamped into their own staff. A part sitting low would otherwise push a
"below" lyric past the clip and out of existence, and an annotation you cannot
see is worse than one slightly crowded.

## Galley and Page view

**Galley** is one continuous strip per part with no pagination — what you write
in, because nothing reflows while you are placing marks. **Page** is the actual
cast-off pages, laid out as they will print — what you engrave in, because breaks
and spacing show their real effect.

Both run through the same casting-off engine as the export
([`shared/layout.js`](../phonorealism_shared/js/layout.js)), so a page break you
place lands in the same place on paper. Two layout implementations would
eventually disagree, and the disagreement would only surface after printing.

With no breaks the score casts off automatically, filling each system before
wrapping. A break overrides that; it never merely suggests.

## Output

Both **Print** and **Export → SVG** offer three layout choices: **Full Score**,
**individual parts** (one file each), or both. Each honours the breaks scoped to
it and is engraved with its own layout profile — page size, orientation and
spacing — exactly as shown on screen.

| Export | What it is |
| --- | --- |
| **SVG pages** | Vector pages, editable in Illustrator or Inkscape |
| **Engraving project** | Parts, marks and breaks — what the conductor page imports |
| **Part map only** | Just the named groupings, interchangeable with the conductor's own export |
| **Print** | The same pages in the browser's print dialogue → Save as PDF |

Print and SVG come from one renderer, so they cannot disagree with each other.
Output carries no title, running head, page count or rules unless *Page
furniture* asks for them — what comes out is the music.

### Getting it to the performers

In the conductor page, **Import engraving / part map** and choose the exported
project. It adopts the parts *and* the marks in one step — they have to travel
together, since marks are addressed by part id. Each player then sees the marks
for their own part plus every global one, scrolling with their ribbon.

## Why partial numbering is safe

The score reader is shared with the performer app rather than copied
([`phonorealism_shared/js`](../phonorealism_shared/js)). Both renumber partials
canonically by ascending median frequency, which is what lets a part map survive
re-export from the modifier — a justidraw export comes out in frequency order
while the CSV carries SPEAR's arbitrary `harmonic_index`, and the two describe
the same music with different labels.

If the engraver carried its own copy and they ever drifted, a part map saying
"partial 7" would silently name different lines in the two applications. Hence
one implementation. Opening a project against a changed score reports what no
longer lines up rather than dropping it quietly.

## Planned: staff notation via LilyPond

The intended next phase is optional staves with **floating noteheads** — pitch
and placement without rhythmic notation, avoiding the problem that this music
has no meter to notate against.

This is well-trodden in LilyPond: `\cadenzaOn` removes barlines and metric
grouping, `\override NoteHead.stem-attachment` / stemless heads drop the rhythmic
apparatus, and proportional spacing places heads by time rather than by duration.
The seam is already in place — annotations are time-anchored with a kind and a
scope, which is what a LilyPond `\markup` or lyric line needs. `GET /api/lilypond`
reports whether the binary is on `PATH`, so the UI can show the feature as
pending rather than broken.

The re-export path back into this file format, or out to conventional paginated
PDF, reuses the same time anchors.

## Layout

```
server/app.py          project files on disk; LilyPond later
static/js/
  canvas.js            the engraving surface — Galley and Page view
  print.js             paginated SVG for print and export
  main.js              Setup / Write / Engrave wiring
../phonorealism_shared/js/
  score.js             both score formats -> one model, canonical numbering
  lib/binser.js        justidraw .sav reader
  annotations.js       the sidecar format, shared with the performer app
  ribbon.js            notation geometry, shared so both apps draw identically
  layout.js            casting off — breaks, note and staff spacing, pagination
```

No score parsing happens in Python. There is one justidraw reader in this
repository and it is JavaScript; a second would be another thing to keep correct.

Project names are reduced to bare filenames before touching the filesystem —
they arrive from a text field and are used to build a path, and there is no
legitimate project called `../../.ssh/id_rsa`.
