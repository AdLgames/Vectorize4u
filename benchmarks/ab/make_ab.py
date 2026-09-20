"""`make ab` — blind, randomised A/B pairs, voted by humans (§3.9, §12).

This, not `make bench`, is the evidence the kill switch uses. Best-of-N
selected by a score always beats a single call *on that score*: a benchmark
that grades our own selector cannot fail, which is exactly why the v2 kill
switch was worthless.

Comparators:
  vtracer-default — one default `vtracer` call, no search, no post-process.
  external        — drop SVGs from a competitor (e.g. Vectorizer.AI,
                    obtained through a normal paid account, terms checked)
                    into benchmarks/ab/external/<image-name>.svg.

Output is a static page. Each pair is randomised left/right, the labels are
hidden until the vote is cast, and votes are appended to votes.json.
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import fixtures
from engine.pipeline import run
from engine.trace import trace_one
from engine.types import Options, Params

OUT = HERE / "out"
EXTERNAL = HERE / "external"


def _ours(data: bytes) -> str:
    return run(data, Options(quality_tier="standard")).svg


def _vtracer_default(data: bytes) -> str:
    """A single default call — no search, no scoring, no post-processing."""
    from engine.ingest import ingest

    result = trace_one(ingest(data).rgba, Params())
    if result.svg is None:
        raise RuntimeError(result.error or "vtracer failed")
    return result.svg


def build(comparator: str, seed: int) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    pairs = []

    for fixture in fixtures.all_fixtures():
        try:
            ours = _ours(fixture.data)
        except Exception as exc:  # noqa: BLE001 - a failed side is still a result
            print(f"{fixture.name}: ours failed: {exc}", file=sys.stderr)
            continue

        if comparator == "external":
            path = EXTERNAL / f"{fixture.name}.svg"
            if not path.exists():
                continue
            theirs = path.read_text()
        else:
            try:
                theirs = _vtracer_default(fixture.data)
            except Exception as exc:  # noqa: BLE001
                print(f"{fixture.name}: comparator failed: {exc}", file=sys.stderr)
                continue

        # Randomise sides so a voter cannot learn "ours is always on the left".
        flip = rng.random() < 0.5
        left, right = (theirs, ours) if flip else (ours, theirs)
        pairs.append(
            {
                "name": fixture.name,
                "source": "data:image/png;base64," + base64.b64encode(fixture.data).decode(),
                "left": left,
                "right": right,
                "ours_side": "right" if flip else "left",
            }
        )

    rng.shuffle(pairs)
    return {"comparator": comparator, "seed": seed, "pairs": pairs}


PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Blind A/B — vectorizer</title>
<style>
 body{font:15px/1.5 system-ui,sans-serif;margin:0;background:#111;color:#eee}
 header{padding:12px 20px;background:#1b1b1b;position:sticky;top:0;display:flex;
        gap:16px;align-items:center;border-bottom:1px solid #333}
 .wrap{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:20px}
 .cell{background:#fff;border-radius:8px;min-height:340px;display:flex;
       align-items:center;justify-content:center;padding:12px}
 .cell svg,.cell img{max-width:100%;max-height:60vh}
 button{font:inherit;padding:10px 18px;border-radius:6px;border:1px solid #444;
        background:#222;color:#eee;cursor:pointer}
 button:hover{background:#2c2c2c}
 .src{padding:0 20px 20px;opacity:.75}
 .src img{max-height:180px;background:#fff;padding:8px;border-radius:6px}
 #done{padding:40px 20px}
 code{background:#222;padding:2px 6px;border-radius:4px}
</style>
<header>
  <strong>Which is better?</strong>
  <span id="progress"></span>
  <button onclick="vote('left')">← Left</button>
  <button onclick="vote('tie')">Tie</button>
  <button onclick="vote('right')">Right →</button>
  <button onclick="download()">Download votes</button>
</header>
<div class="src"><div>Source:</div><img id="source"></div>
<div class="wrap"><div class="cell" id="left"></div><div class="cell" id="right"></div></div>
<div id="done" hidden>
  <h2>Done</h2>
  <p>Click <strong>Download votes</strong> and save the file as
     <code>benchmarks/ab/votes.json</code>, then run <code>make ab-report</code>.</p>
</div>
<script>
const DATA = __DATA__;
let i = 0;
const votes = [];
function render(){
  if(i >= DATA.pairs.length){
    document.querySelector('.wrap').hidden = true;
    document.querySelector('.src').hidden = true;
    document.getElementById('done').hidden = false;
    document.getElementById('progress').textContent = 'all ' + votes.length + ' pairs voted';
    return;
  }
  const p = DATA.pairs[i];
  document.getElementById('source').src = p.source;
  document.getElementById('left').innerHTML = p.left;
  document.getElementById('right').innerHTML = p.right;
  document.getElementById('progress').textContent = (i+1) + ' / ' + DATA.pairs.length;
}
function vote(side){
  const p = DATA.pairs[i];
  // The label is resolved here, after the vote, never shown in the DOM.
  const winner = side === 'tie' ? 'tie' : (side === p.ours_side ? 'ours' : 'comparator');
  votes.push({name: p.name, comparator: DATA.comparator, choice: winner});
  i++; render();
}
function download(){
  const blob = new Blob([JSON.stringify({comparator: DATA.comparator, votes}, null, 2)],
                        {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'votes.json'; a.click();
}
document.addEventListener('keydown', e => {
  if(e.key === 'ArrowLeft') vote('left');
  if(e.key === 'ArrowRight') vote('right');
  if(e.key === ' ') { e.preventDefault(); vote('tie'); }
});
render();
</script>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make ab")
    parser.add_argument("--comparator", default="vtracer-default",
                        choices=["vtracer-default", "external"])
    parser.add_argument("--seed", type=int, default=20240101)
    args = parser.parse_args(argv)

    data = build(args.comparator, args.seed)
    if not data["pairs"]:
        print("no pairs built", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    page = OUT / f"ab-{args.comparator}.html"
    page.write_text(PAGE.replace("__DATA__", json.dumps(data)))
    print(f"wrote {page} ({len(data['pairs'])} pairs)")
    print("Open it, have 2–3 people who did not write the code vote, save votes.json,")
    print("then run: make ab-report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
