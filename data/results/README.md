# Results data schema

Drop one `stage_NN.json` file per finished stage in this folder (zero-padded,
e.g. `stage_01.json`, `stage_02.json`...). The scraper (built later) just
needs to produce files matching this schema — the scoring engine and site
don't care where the data came from.

Rider names must match the names used in `data/participants/*.json` and
`data/teams_master.json` exactly (same spelling). If the results source uses
different spellings (e.g. "Van der Poel" vs "Vd Poel"), add a name-alias
mapping before this becomes a real problem — not needed yet.

## Per-stage file: `stage_NN.json`

```json
{
  "stage": 1,
  "stage_result": ["Rider 1st", "Rider 2nd", "...up to 10th"],
  "gc": ["Yellow jersey top 1", "...", "top 5"],
  "points": ["Green jersey top 1", "...", "top 3"],
  "mountains": ["Polka dot top 1", "...", "top 3"],
  "youth": ["White jersey top 1", "...", "top 3"]
}
```

All lists are ordered best-to-worst (index 0 = 1st place). Shorter lists are
fine (e.g. fewer than 10 finishers recorded) — missing ranks just score 0.

## Final file: `final.json` (appears once, at the end of the Tour)

```json
{
  "gc_final": ["...top 10 overall"],
  "points_final": ["...top 6 green jersey"],
  "mountains_final": ["...top 4 polka dot"],
  "youth_final": ["...top 3 white jersey"],
  "podium": ["1st overall", "2nd overall", "3rd overall"],
  "winner_gap_seconds": 123,
  "dnf_count": 27
}
```

See `stage_01.json.example` and `final.json.example` for filled-in samples
using real 2026 rider names (fictional placements, just to demonstrate the
shape). Copy to `stage_01.json` / `final.json` (drop the `.example`) and fill
with real data to activate — the scoring engine ignores any `*.example` file.
