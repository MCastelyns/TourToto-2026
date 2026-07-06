"""
Renders data/computed/standings.json (produced by scoring.py) plus the raw
participant/results data into a single static site/index.html.

Run `python scoring.py` first (or use build.py to do both in order).
"""
import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from names import build_resolver

ROOT = Path(__file__).resolve().parent.parent
STANDINGS_PATH = ROOT / "data" / "computed" / "standings.json"
PARTICIPANTS_DIR = ROOT / "data" / "participants"
TEAMS_MASTER_PATH = ROOT / "data" / "teams_master.json"
WITHDRAWN_PATH = ROOT / "data" / "withdrawn_riders.json"
TEMPLATES_DIR = ROOT / "templates"
SITE_DIR = ROOT / "docs"  # GitHub Pages serves from a "docs/" folder on the main branch

TOTAL_STAGES = 21


def load_participant_rosters():
    rosters = {}
    for path in sorted(PARTICIPANTS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        rosters[data["name"]] = data
    return rosters


def load_withdrawn():
    if WITHDRAWN_PATH.exists():
        return set(json.loads(WITHDRAWN_PATH.read_text(encoding="utf-8")))
    return set()


def all_raw_picks(rosters):
    names = set()
    for data in rosters.values():
        names |= {r["rider"] for r in data["hoofdploeg"]}
        names |= {r["rider"] for r in data["pannenkoeken"]}
    return names


def count_owners(rosters, resolve):
    """How many participants have each rider (by canonical name) on their
    hoofdploeg specifically - pannenkoeken picks don't count here, since
    that's a different pool with a different (lowest-wins) purpose. Resolves
    each pick first so spelling variants of the same rider (e.g. "Philipsen"
    vs the canonical "J. Philipsen") aren't double-counted as two different
    riders."""
    counts = {}
    for data in rosters.values():
        raw_names = {r["rider"] for r in data["hoofdploeg"]}
        canonical_names = {resolve(n) or n for n in raw_names}
        for name in canonical_names:
            counts[name] = counts.get(name, 0) + 1
    return counts


def build_rider_info(rosters):
    """Enriches the master roster's {team, slot} per rider with fun-diagnostic
    fields for the tooltip: how many participants picked them, and whether
    they're currently marked as withdrawn."""
    rider_info = json.loads(TEAMS_MASTER_PATH.read_text(encoding="utf-8"))["riders"]
    resolve = build_resolver(list(rider_info.keys()))

    owner_counts = count_owners(rosters, resolve)
    withdrawn = load_withdrawn()
    n_participants = len(rosters)
    for name, info in rider_info.items():
        info["n_owners"] = owner_counts.get(name, 0)
        info["n_participants"] = n_participants
        info["withdrawn"] = name in withdrawn

    # Let template lookups (roster display, tooltips) succeed for whatever
    # spelling a participant actually typed, not just the exact canonical
    # form - otherwise e.g. "Philipsen" silently shows no team while
    # "J. Philipsen" would.
    for raw_name in all_raw_picks(rosters):
        if raw_name in rider_info:
            continue
        canonical = resolve(raw_name)
        if canonical:
            rider_info[raw_name] = rider_info[canonical]

    return rider_info


def rank_changes_by_stage(participants, team_key, stages_available, best_is_high):
    """{stage_num: {participant_name: delta}} comparing cumulative rank after
    each stage to the rank after the one before it. Positive = moved up
    (better). The first stage in stages_available has no entry (nothing to
    compare against yet)."""
    def ranks_at(stage_num):
        key = str(stage_num)
        cumulatives = [(p["name"], p[team_key]["by_stage"][key]["cumulative"]) for p in participants]
        cumulatives.sort(key=lambda x: x[1], reverse=best_is_high)
        return {name: i + 1 for i, (name, _) in enumerate(cumulatives)}

    result = {}
    for i in range(1, len(stages_available)):
        stage_num, previous_num = stages_available[i], stages_available[i - 1]
        stage_ranks, previous_ranks = ranks_at(stage_num), ranks_at(previous_num)
        result[stage_num] = {name: previous_ranks[name] - stage_ranks[name] for name in stage_ranks}
    return result


def find_highest_dagscore(participants, stages_available):
    """The "Hoogste dagscore" prize: the single highest hoofdploeg score
    anyone got on any one day, using the base (pre-joker-doubling) score per
    the rules ("no 2x"). Returns (record_value, {(participant_name, stage)}
    - a set since ties are possible and all of them should be marked."""
    best = 0
    cells = set()
    for p in participants:
        for stage_str, st in p["hoofdploeg"]["by_stage"].items():
            score = st["base_score"]
            if score > best:
                best = score
                cells = {(p["name"], int(stage_str))}
            elif score == best and score > 0:
                cells.add((p["name"], int(stage_str)))
    return best, cells


def find_optimal_matches(participants, stage_breakdowns):
    """Cells where a participant's actual hoofdploeg score for a stage exactly
    matches that day's theoretical optimal score (i.e. they drafted the
    literal best possible legal team for that stage) - vanishingly unlikely,
    but worth marking if it ever happens. Returns {(participant_name, stage)}."""
    cells = set()
    for p in participants:
        for stage_str, st in p["hoofdploeg"]["by_stage"].items():
            breakdown = stage_breakdowns.get(stage_str)
            optimal = breakdown.get("optimal_hoofdploeg") if breakdown else None
            if optimal and st["base_score"] > 0 and st["base_score"] == optimal["score"]:
                cells.add((p["name"], int(stage_str)))
    return cells


def main():
    if not STANDINGS_PATH.exists():
        raise SystemExit("data/computed/standings.json not found - run scoring.py first")

    standings = json.loads(STANDINGS_PATH.read_text(encoding="utf-8"))
    rosters = load_participant_rosters()
    rider_info = build_rider_info(rosters)

    hoofd_ranked = sorted(standings["participants"], key=lambda p: -p["hoofdploeg"]["total"])
    pannen_ranked = sorted(standings["participants"], key=lambda p: p["pannenkoeken"]["total"])

    stages_available = standings["stages_available"]

    hoofd_rank_changes_by_stage = rank_changes_by_stage(standings["participants"], "hoofdploeg", stages_available, best_is_high=True)
    pannen_rank_changes_by_stage = rank_changes_by_stage(standings["participants"], "pannenkoeken", stages_available, best_is_high=False)
    hoofd_rank_changes = hoofd_rank_changes_by_stage.get(stages_available[-1], {}) if stages_available else {}
    pannen_rank_changes = pannen_rank_changes_by_stage.get(stages_available[-1], {}) if stages_available else {}

    dagscore_record, dagscore_cells = find_highest_dagscore(standings["participants"], stages_available)
    optimal_cells = find_optimal_matches(standings["participants"], standings.get("stage_breakdowns", {}))

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("index.html.j2")

    html = template.render(
        hoofd_ranked=hoofd_ranked,
        pannen_ranked=pannen_ranked,
        rosters=rosters,
        stages_available=stages_available,
        total_stages=TOTAL_STAGES,
        final_available=standings["final_available"],
        unresolved_names=set(standings.get("unresolved_names", [])),
        stage_breakdowns=standings.get("stage_breakdowns", {}),
        rider_info=rider_info,
        hoofd_rank_changes=hoofd_rank_changes,
        pannen_rank_changes=pannen_rank_changes,
        hoofd_rank_changes_by_stage=hoofd_rank_changes_by_stage,
        pannen_rank_changes_by_stage=pannen_rank_changes_by_stage,
        dagscore_record=dagscore_record,
        dagscore_cells=dagscore_cells,
        optimal_cells=optimal_cells,
        generated_at=datetime.now().strftime("%d-%m-%Y %H:%M"),
    )

    SITE_DIR.mkdir(exist_ok=True)
    (SITE_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"Wrote {SITE_DIR / 'index.html'}")


if __name__ == "__main__":
    main()
