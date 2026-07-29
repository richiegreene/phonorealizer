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

## Using it

**Load a score**, and every partial becomes its own part. Replace those with
real ones — *New part…* takes `3, 7, 12-14`. Each part gets a **system**: a
horizontal band showing its partials in the same ribbon notation the players
read, where height is pitch and thickness is amplitude.

Each system scales its pitch axis to its own part. A score spanning partial 1 at
400 Hz and partial 32 at 19 kHz covers five octaves; one shared axis would
compress every individual line into a flat thread. Cross-part pitch comparison
is what the *All parts / Only:* selector is for.

**Click an empty spot on a system** to place a mark; click one to select, drag to
move, double-click to retype. *Applies to* decides whether it belongs to that one
part or to **all parts at once** — global marks are drawn on every system in
green, so "simultaneously" is visible rather than implied. *Split to parts*
turns a global mark into an editable copy on each part when they need to diverge.

Setting an **Until** time turns a mark into a span, drawn with a continuation
line — for *cresc.*, *sempre*, or a held direction.

Marks are clamped into their own system band. A part sitting low would otherwise
push a "below" lyric past the clip and out of existence, and an annotation you
cannot see is worse than one slightly crowded.

## Output

| Export | What it is |
| --- | --- |
| **Engraving project** | Parts and marks together — what the conductor page imports |
| **Part map only** | Just the named groupings, interchangeable with the conductor's own export |
| **SVG pages** | Vector pages, editable in Illustrator or Inkscape |
| **Print** | The same pages in the browser's print dialogue → Save as PDF |

Print and SVG come from one renderer, so they cannot disagree with each other.

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
  canvas.js            the engraving surface — systems, ribbons, mark placement
  print.js             paginated SVG for print and export
  main.js              application wiring
../phonorealism_shared/js/
  score.js             both score formats -> one model, canonical numbering
  lib/binser.js        justidraw .sav reader
  annotations.js       the sidecar format, shared with the performer app
  ribbon.js            notation geometry, shared so both apps draw identically
```

No score parsing happens in Python. There is one justidraw reader in this
repository and it is JavaScript; a second would be another thing to keep correct.

Project names are reduced to bare filenames before touching the filesystem —
they arrive from a text field and are used to build a path, and there is no
legitimate project called `../../.ssh/id_rsa`.
