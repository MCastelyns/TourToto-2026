"""
Scrapes one stage's results from the Race Center API and writes
data/results/stage_NN.json in the schema scoring.py expects.

Usage:
    python scrape_results.py --stage 1
    python scrape_results.py --stage 1 --year 2026

Ranking-type -> our schema field:
    ite (individual time, etappe)    -> stage_result  (daily etappe uitslag, top 10)
    itg (individual time, general)   -> gc            (yellow jersey standings, top 5)
    ipg (individual points, general) -> points         (green jersey standings, top 3)
    img (individual mountains, gen.) -> mountains      (polka dot standings, top 3)
    ijg (individual jersey, general) -> youth          (white jersey standings, top 3)

Known gap: on a Team Time Trial stage there is no "ite" (individual stage
result) from the API - only team-level results exist. Exception: on STAGE 1
specifically, the general classification ("itg") is mathematically identical
to the stage result (nothing has accumulated yet), so we fall back to "itg"
for "stage_result" on stage 1 only. This does NOT generalize to a TTT on any
later stage - there, GC is cumulative and no longer equals that day's time,
so `stage_result` is left empty and it's a rules question for the group.

Any jersey ranking where every rider in it is tied at 0 (e.g. green/polka on
a stage with no intermediate sprints or climbs, like a TTT) is written as an
empty list instead of the API's arbitrary tie-break order - there's no real
achievement behind that ranking, so no points should be handed out for it.

Riders are identified by bib number via data/rider_bib_map.json (built by
build_bib_map.py). A handful of riders may not be in that map yet (typos /
data-corruption on the API side - see the WARNING output); their placings are
still written using the API's own "Firstname LASTNAME" as a fallback name so
the ranking isn't silently missing an entry, but they won't match any
participant's pick until bib-mapped properly.
"""
import argparse
import json
from pathlib import Path

from api_client import get_ranking_types

ROOT = Path(__file__).resolve().parent.parent
BIB_MAP_PATH = ROOT / "data" / "rider_bib_map.json"
RESULTS_DIR = ROOT / "data" / "results"

TYPE_TO_FIELD = {
    "ite": ("stage_result", 10),
    "itg": ("gc", 5),
    "ipg": ("points", 3),
    "img": ("mountains", 3),
    "ijg": ("youth", 3),
}

FIELD_LABELS = {
    "stage_result": "dag-uitslag",
    "gc": "gele trui",
    "points": "groene trui",
    "mountains": "bergtrui",
    "youth": "witte trui",
}


def build_bib_to_name(bib_map):
    bib_to_name = {}
    for name, bib in bib_map.items():
        bib_to_name[bib] = name
    return bib_to_name


def ranked_names(entry, bib_to_name, limit):
    rankings = sorted(entry["rankings"], key=lambda r: r["position"])[:limit]
    if rankings and all(r.get("absolute", 0) == 0 for r in rankings):
        # Everyone tied at 0 (e.g. green/polka after a stage with no intermediate
        # sprints or climbs, like a TTT) - the "top N" the API returns is just
        # whatever arbitrary order it breaks ties with, not a real achievement.
        # Awarding jersey points for that would be handing them out for nothing.
        return [], [], True
    names = []
    unresolved_bibs = []
    for r in rankings:
        bib = r["bib"]
        name = bib_to_name.get(bib)
        if name is None:
            unresolved_bibs.append(bib)
            name = f"[bib {bib}]"
        names.append(name)
    return names, unresolved_bibs, False


def scrape_stage(stage, year=2026):
    """Fetches one stage's results and writes data/results/stage_NN.json.
    Returns (result_dict, notes, warnings) - notes/warnings are plain-text
    lines a caller can print or show in a UI; nothing here raises for
    "expected" data quirks (missing ite, all-zero jerseys), only for real
    failures (network error, bad response)."""
    notes = []
    warnings = []

    bib_map = json.loads(BIB_MAP_PATH.read_text(encoding="utf-8"))
    bib_to_name = build_bib_to_name(bib_map)

    entries = get_ranking_types(year, stage)
    by_type = {}
    for e in entries:
        by_type.setdefault(e["type"], e)

    result = {"stage": stage}
    all_unresolved = set()
    for type_code, (field, limit) in TYPE_TO_FIELD.items():
        entry = by_type.get(type_code)
        if entry is None:
            result[field] = []
            continue
        names, unresolved, all_tied_zero = ranked_names(entry, bib_to_name, limit)
        result[field] = names
        all_unresolved.update(unresolved)
        if all_tied_zero:
            notes.append(f"Iedereen op 0 punten voor {FIELD_LABELS[field]} op etappe {stage} "
                         f"(nog niets gescoord voor dat klassement) - geen punten toegekend.")

    if not by_type.get("ite"):
        if stage == 1 and by_type.get("itg"):
            names, unresolved, _ = ranked_names(by_type["itg"], bib_to_name, 10)
            result["stage_result"] = names
            all_unresolved.update(unresolved)
            notes.append("Geen individuele dag-uitslag ('ite') voor etappe 1 (ploegentijdrit) - "
                         "'itg' (algemeen klassement) gebruikt in plaats daarvan, wat identiek is "
                         "aan de dag-uitslag op etappe 1 specifiek (er is nog niets opgeteld).")
        else:
            notes.append(f"Geen individuele dag-uitslag ('ite') voor etappe {stage} "
                         f"(waarschijnlijk een ploegentijdrit) - 'dag-uitslag' blijft leeg.")

    if all_unresolved:
        warnings.append(f"{len(all_unresolved)} rugnummer(s) niet in rider_bib_map.json, "
                        f"getoond als '[bib N]': {sorted(all_unresolved)}. "
                        f"Los op via /admin/bib-review.")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"stage_{stage:02d}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result, notes, warnings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument("--year", type=int, default=2026)
    args = parser.parse_args()

    result, notes, warnings = scrape_stage(args.stage, args.year)
    for note in notes:
        print(f"NOTE: {note}")
    for warning in warnings:
        print(f"WARNING: {warning}")

    out_path = RESULTS_DIR / f"stage_{args.stage:02d}.json"
    print(f"\nWrote {out_path}")
    for field in ("stage_result", "gc", "points", "mountains", "youth"):
        print(f"  {field}: {result[field]}")


if __name__ == "__main__":
    main()
