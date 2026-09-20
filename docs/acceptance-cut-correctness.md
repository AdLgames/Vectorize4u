# Acceptance test: does it open at the right size?

§13 of the spec calls this **the one that matters most to the buyer**:

> SVG and DXF open at the user-specified physical size in Cricut Design
> Space and LightBurn — manual acceptance test.

It cannot be automated. It needs a person, the two applications, and about
an hour. This document is that hour.

## Before you start

```bash
make kit
```

That regenerates `benchmarks/acceptance/out/` and **measures every file
before you open anything**: the SVG's declared physical size, the DXF's
`$INSUNITS` and real extents, and whether the geometry came out mirrored.
If the self-check fails, stop — the bug is ours and there is nothing to
learn from a cutting app until it is fixed.

The self-check is not decorative. Reverting the Y-flip in
`engine/emit.py: to_dxf` makes it report *"DXF geometry is upside down"* on
the `letter-f-80mm` target, which is exactly the failure a human would
otherwise only notice after gluing a mirrored part to something.

## What each target is for

Every target is **full bleed** — the ink touches all four edges. That
matters: the emitted SVG's physical width is the width of the *canvas*, so
with a margin "100 mm" would measure less than 100 mm at the shape and the
test would fail for a reason that isn't a bug.

| Target | Expected | Catches |
|---|---|---|
| `ruler-100mm` | 100.0 × 20.0 mm, ticks every 10.0 mm, tall ticks at 0/50/100 | scale error, and stretching on one axis |
| `ruler-4in` | 4.000 × 0.800 in, ticks every 0.400 in | the imperial path, and mm/inch confusion |
| `square-100mm` | 100.0 × 100.0 mm, notch in the **top-left** corner | aspect-ratio error, 90° rotation |
| `letter-f-80mm` | 80.0 × 80.0 mm, reads as a normal F — arms at the **top**, pointing **right** | mirrored or upside-down import |
| `fine-detail-150mm` | 150.0 × 106.7 mm, 7 strokes and 6 holes | features lost to cleanup |

The ruler carries two independent numbers on purpose. A file that is
uniformly 4% small fails the total width and the tick spacing the same way;
a file stretched on one axis fails them differently. That is what tells the
two apart without guessing.

## The test

For **each** target, in **both** applications:

### Cricut Design Space — SVG

1. Upload the `.svg`.
2. Read the size Design Space reports for the imported shape.
3. Compare against the table above. It should match to within the app's own
   rounding — **0.2 mm at 100 mm**, not "about right".
4. For `square-100mm`, check the notch is top-left. For `letter-f-80mm`,
   check the F is not mirrored.

Record the number you actually see, not whether it looked right.

### LightBurn — DXF

1. Import the `.dxf`. **If LightBurn asks about units, note what it asked.**
   A file with `$INSUNITS` set correctly should not prompt; being asked is
   itself a finding.
2. Read the object size from the toolbar.
3. Same tolerance, same checks.
4. For `ruler-4in`, confirm it comes in as 4 inches and not 4 mm or
   101.6 mm-labelled-as-inches.

### Also worth ten minutes

- Open `square-100mm.pdf` in Illustrator or Inkscape and check the artboard
  is 100 × 100 mm.
- Import `letter-f-80mm.dxf` into Design Space too, if your plan supports
  DXF — the SVG and DXF paths through the emitter are separate code.

## What a failure means

| Symptom | Where to look |
|---|---|
| Everything is uniformly wrong by the same factor | `engine/emit.py: resolve_physical_size` — the mm/inch conversion, or `ASSUMED_DPI` |
| Width right, height wrong | aspect handling in `resolve_physical_size`; the SVG `viewBox` vs `width`/`height` |
| LightBurn asks which units to use | `$INSUNITS` is not being written — `engine/emit.py: to_dxf` |
| Inches come in as millimetres | `to_dxf`'s `scale` divides by `MM_PER_INCH` for `units="in"`; check `$MEASUREMENT` too |
| The F is mirrored or upside down | the Y flip in `to_dxf` — DXF's Y axis grows up, an image's grows down |
| Small strokes or holes missing | not necessarily a bug — see below |

## A measured fact about our own defaults

`fine-detail-150mm` is emitted **twice**:

- `fine-detail-150mm.svg` / `.dxf` — cleanup off. This is the measurement
  file: simplification, speckle removal and node spacing are disabled so
  nothing has moved the edges being measured.
- `fine-detail-150mm-defaults.svg` / `.dxf` — the settings a customer
  actually gets.

At 150 mm wide, comparing the two: **the 0.17 mm stroke and the 1.0 mm hole
are removed by our defaults.** Everything from 0.33 mm and 1.7 mm up
survives.

Dropping a 0.17 mm stroke is right — no blade cuts it, and leaving it in
produces a tear. **Dropping a 1.0 mm hole is a decision, not obviously
right.** A 1 mm hole is marginal on vinyl and entirely routine on a laser.
It comes from the sliver threshold in §3.7 step 1
(`SLIVER_AREA_FRACTION`, 0.0002 of the canvas), which is a fraction of the
*canvas* and therefore tightens as the artwork gets bigger.

Decide this deliberately rather than inheriting it:

- If it is wrong, the threshold should be expressed in **real millimetres**
  via the resolved physical size, the same way node spacing already is —
  not as a fraction of the canvas.
- If it is right, say so on the cut-intent pages, because someone will
  eventually ask where their holes went.

## Recording the result

Write the numbers you measured into `benchmarks/acceptance/results.md` —
app version, target, expected, actual. Re-run the whole thing whenever
`engine/emit.py` changes, because this is the promise the product's
positioning rests on and it has no automated guard beyond the self-check.
