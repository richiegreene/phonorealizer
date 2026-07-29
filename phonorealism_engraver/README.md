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

## Four modes

Organised as Dorico is, because the vocabulary is already in use: what you are
doing decides what the panel offers.

**Setup** names the parts. Load a score and every partial becomes its own part;
replace those with real ones — *New part…* takes `3, 7, 12-14`. Each part gets a
**staff**: a band showing its partials in the same ribbon notation the players
read, height as pitch and thickness as amplitude.

A part can also carry a **nickname**. Where part names are shown, the full name
is set on the system where the part first appears and the nickname on every
system after it, as an orchestral score does — a name repeated in full down forty
systems is a gutter of text rather than information. A part without a nickname
keeps its full name throughout, rather than going unlabelled from the second
system on.

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

**Shift-click** gathers several marks, on the score or in the list — the two are
interchangeable, so a run of lyrics can be collected from whichever is easier to
hit. Dragging any one of them moves the whole selection, keeping the spacing
between them: the delta is applied in seconds and cents, not pixels, so a group
does not come apart when the staff height changes.

*Vertical alignment* is what a selection is mostly for. A mark's placement is two
decisions, and both are wanted:

| | |
| --- | --- |
| **place** | the zone — above the staff, within it, or below it |
| **align** | what that zone is measured from |

Aligned to the **sounding line**, a mark hangs off its partial and travels with
it as the pitch scale changes — right for something naming a moment in one line.
Aligned to the **staff**, it sits at a fixed height in its zone, and every mark
placed there shares one baseline. Lyrics need the second: text that rode the
melody up and down is not readable as a line of words.

So the **Above / Within / Below** buttons do both at once — they move the
selection into the zone *and* align it there, clearing the hand-set nudge that
would otherwise be the one thing keeping the marks out of line. *Follow the line*
puts them back on their partials. The modal sets the two independently when a
single mark wants a zone without the alignment.

Where the zone physically is depends on the staff. An un-normalised staff has a
fixed height and its marks are clamped inside it, so above and below mean the
head and foot of the staff — an annotation you cannot see is worse than one
slightly crowded. Turn on *Normalise height per system* and the staff is only as
tall as its music, so above and below become genuinely outside the ribbon, in
rows the staff reserves room for. Either way marks that would collide are stacked
into further rows rather than printed on top of each other.

**Engrave** controls how it sits on the page:

| | |
| --- | --- |
| **Page setup** | paper size, orientation, margins |
| **Note spacing** | how much width a second of music occupies — wider casts off into more systems |
| **Staff spacing** | staff height, gaps between parts and between systems, ribbon thickness, *Normalise height per system* |
| **Grid rules** | a vertical grid in time and a horizontal one in pitch |
| **Breaks** | *Create System Break* / *Create Page Break*, scoped to Full Score or one part |
| **Page furniture** | part names and their size, title, page numbers — all off but part names |

### Grid rules

Two axes, because they answer different questions. The **vertical** grid is a
time reference: this music has no metre, so nothing derives a barline for us, and
the rate is given as a tempo — 60 for a marker a second — because that is the
unit the music is actually cued against. *Ticks* draws one short row rather than
marks at both staff edges, and a slider raises that row anywhere from the foot of
the staff to its head, since which edge is clear of the notation depends on the
music.

The **horizontal** grid reads pitch off the same cents-from-A440 scale the ribbon
is drawn against, so it lines up with the notation rather than approximating it.
*Semitone guidelines* puts a rule at each semitone, emphasised at every C, and a
partial's pitch reads off the line it sits on. *Piano roll* instead shades the
chromatic regions, each one a semitone tall and centred on its black note, at an
opacity you set — so a partial in the middle of a dark band is on that black
note. Both together give the lines with the regions behind them.

Below about five pixels a semitone the lines stop reading as separate rules and
thin to the octaves, then stop; shading survives closer spacing, since
alternating light and dark still reads as a pattern where a comb of lines does
not.

### Normalise height per system

Off, every staff takes the full staff height whether its part uses that register
or not. On, each staff is cropped to the pitch its part actually reaches in that
system — a partial sitting still for a system earns a sliver, not a whole staff,
and pages hold more music without anything being made smaller.

The pitch axis is cropped, not rescaled. Choosing a new scale per system would
make the same glissando steeper on one system than the next, which would be a
lie about the music rather than a saving of space.

Annotations are what makes this more than arithmetic: a staff only as tall as its
ribbon has no slack inside it to hold text. So above and below marks are stacked
in rows outside the ribbon, as many as it takes for none of them to collide, and
those rows are what the staff reserves room for — including the vertical nudge,
so dragging a mark further out still leaves it inside its own staff rather than
over its neighbour's. Past a few rows the crowding is a spacing problem to solve
horizontally, and the staff stops growing to accommodate it.

**Play** auditions it. A transport, a playhead that travels through the score,
and clicking the music to play from there — Dorico's Play mode, and space to
start and stop.

### Playing through the performers' own synthesis

The renderer is not a preview built for this application. It is
[`shared/synth.js`](../phonorealism_shared/js/synth.js), the same additive
re-synthesis the performers hear in their earbuds, moved into the shared
directory when this mode was added rather than copied into it. Two
re-synthesisers would eventually disagree about what the score sounds like, and
the disagreement would surface as the composer and the players hearing different
music — the same reason there is one score reader and one casting-off engine.

So **Playback timbre** is the performers' timbre: the 0–300 morph through sine,
triangle, sawtooth and square from the desktop modifier's *Basic Shapes* preset,
band-limited so that a partial at 19 kHz does not fold its harmonics back down
into the range the players are tuning against. What is auditioned at the desk is
what will be in their ears.

Playback follows the view rather than having a target of its own. On **Full
Score** the whole spectrum sounds. On a part, that part sounds with the rest of
the score on the far side of a **Balance** fader — the same "me against everyone
else" crossfade the monitor mix is built from, which is what makes it possible to
hear whether a part is findable inside the texture.

Position comes from the AudioContext clock rather than a timer, so the playhead
cannot drift from the sound it is reporting. Changing timbre mid-playback
re-renders and picks up where it left off, because a timbre you have to stop and
restart to hear is one you will not audition properly. Rendering happens on a
worker thread and is keyed to what the sound actually depends on — the layout's
partials and the timbre — so editing an annotation does not throw away a render,
and switching layout does.

**Follow the playhead** pages the view along. Page view jumps to the page the
playhead is on and keeps it in the upper part of the window, so there is music
visible ahead of it; galley moves its window a screenful at a time rather than
scrolling continuously, because a strip sliding under a fixed line is much harder
to read from than a static one the line crosses.

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

Part names are **centred on the part's contents**, so they stay against the music
whichever way *Normalise height per system* is set, and their size on screen is
the size in *Page furniture* rather than the zoom's — a name that grew and shrank
with the view could not be judged against the page it will be printed on.

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
  main.js              Setup / Write / Engrave / Play wiring
../phonorealism_shared/js/
  score.js             both score formats -> one model, canonical numbering
  lib/binser.js        justidraw .sav reader
  annotations.js       the sidecar format, shared with the performer app
  ribbon.js            notation geometry, shared so both apps draw identically
  layout.js            casting off — breaks, spacing, pagination, staff and grid geometry
  synth.js             re-synthesis and the timbre morph, shared with the performers' ears
  render-worker.js     additive synthesis off the main thread
```

No score parsing happens in Python. There is one justidraw reader in this
repository and it is JavaScript; a second would be another thing to keep correct.

Project names are reduced to bare filenames before touching the filesystem —
they arrive from a text field and are used to build a path, and there is no
legitimate project called `../../.ssh/id_rsa`.
