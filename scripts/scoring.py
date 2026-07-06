"""
Tourtoto 2026 scoring engine.

Reads:
  - data/participants/*.json   (each participant's hoofdploeg/pannenkoeken picks + joker stage)
  - data/results/stage_*.json  (one file per finished stage; see data/results/README.md for schema)
  - data/results/final.json    (final GC/jersey classifications + bonus-question answers; appears once the Tour ends)

Writes:
  - data/computed/standings.json

Rule reference (from Tour toto 2026 regelement.docx):
  Daily etappe-uitslag: 1st..10th -> 10,9,8,7,6,5,4,3,2,1
  Daily geel (yellow) top 5:   5,4,3,2,1
  Daily groen (green) top 3:   3,2,1
  Daily bolletjes (polka) top 3: 3,2,1
  Daily wit (white) top 3:     3,2,1
  Jokeretappe: doubles that participant's TOTAL points for that stage.
    Applies to the hoofdploeg only - the pannenkoeken team has no joker.
  Pannenkoeken: identical daily scoring rules, but LOWEST total wins.
  Final classification bonus (added once, not doubled by joker):
    Geel:      10,9,8...  (top 10)
    Groen:     6,5,4...   (top 6)
    Bolletjes: 4,3,2...   (top 4)
    Wit:       3,2,1      (top 3)
"""
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

from names import build_resolver

ROOT = Path(__file__).resolve().parent.parent
PARTICIPANTS_DIR = ROOT / "data" / "participants"
RESULTS_DIR = ROOT / "data" / "results"
TEAMS_MASTER_PATH = ROOT / "data" / "teams_master.json"
OUT_PATH = ROOT / "data" / "computed" / "standings.json"

DAILY_SCALES = {
    "stage_result": 10,   # etappe uitslag, top 10 -> 10..1
    "gc": 5,               # geel, top 5 -> 5..1
    "points": 3,           # groen, top 3 -> 3..1
    "mountains": 3,        # bolletjes, top 3 -> 3..1
    "youth": 3,            # wit, top 3 -> 3..1
}

FINAL_SCALES = {
    "gc_final": 10,
    "points_final": 6,
    "mountains_final": 4,
    "youth_final": 3,
}

# --- PROVISIONAL bonus-question scoring ---------------------------------
# The regelement only specifies "max 25 punten" for these two guesses without
# stating the decay curve. Until the group confirms an exact formula, this
# uses linear decay: points = max(0, MAX - |guess - actual|).
# Adjust these constants (or the compute_bonus_points function) once agreed.
BONUS_PODIUM_POINTS_PER_RIDER = 10
BONUS_GAP_MAX_POINTS = 25
BONUS_DNF_MAX_POINTS = 25
# -------------------------------------------------------------------------


def rank_points(ordered_names, scale):
    """ordered_names[0] is 1st place. Returns {name: points}."""
    return {name: scale - i for i, name in enumerate(ordered_names) if name and i < scale}


def stage_points_by_rider(stage_data):
    """Combine all daily components into a single {rider: points} map for one stage."""
    totals = {}
    for key, scale in DAILY_SCALES.items():
        for rider, pts in rank_points(stage_data.get(key) or [], scale).items():
            totals[rider] = totals.get(rider, 0) + pts
    return totals


def team_stage_score(rider_names, stage_points):
    return sum(stage_points.get(name, 0) for name in rider_names)


def optimal_hoofdploeg(stage_points, teams):
    """The theoretical best possible hoofdploeg score for one stage, per the
    draft rules: 2x rank-1 ("kopman", slots 1 and 9) + one each of rank 2-8
    (slots 2-8) + slot 10 (any rank 2-8 rider) - all 10 riders from 10
    distinct brand teams. Returns (score, [slot rows]), where each slot row
    is {"rank": 1..10, "rider": name, "points": pts} in a fixed slot order
    (always 10 rows, even where the assigned rider scored 0 that day).

    All 10 slots are solved as a SINGLE max-weight assignment problem (23
    teams x 10 slot-columns, each team usable for at most one slot) via the
    Hungarian algorithm. Slot 10 has no rank constraint (any rank 2-8 rider
    qualifies), so its column value for a given team is the best that team's
    rank 2-8 riders could contribute.

    Solving the 9 rank-constrained slots in isolation first and only then
    greedily assigning slot 10 from the leftover teams is NOT equivalent to
    this: a locally-suboptimal 9-slot split can free up a team whose slot-10
    contribution more than makes up the difference. Only a joint assignment
    over all 10 columns at once finds the true optimum."""
    team_names = list(teams.keys())
    n_cols = 10  # rank1, rank1(dup), rank2, rank3, rank4, rank5, rank6, rank7, rank8, extra(best of rank2-8)
    cost = np.zeros((len(team_names), n_cols))
    extra_rider = {}  # team -> best rank2-8 rider (name, points), for the slot-10 column
    for i, team in enumerate(team_names):
        roster = teams[team]
        for col in range(9):
            rank_idx = 0 if col < 2 else col - 1  # roster index for that rank (rank N -> index N-1)
            cost[i, col] = stage_points.get(roster[rank_idx], 0)
        best_rider, best_pts = None, -1
        for rider in roster[1:8]:  # ranks 2-8
            pts = stage_points.get(rider, 0)
            if pts > best_pts:
                best_rider, best_pts = rider, pts
        cost[i, 9] = best_pts
        extra_rider[team] = (best_rider, best_pts)

    row_ind, col_ind = linear_sum_assignment(cost, maximize=True)
    by_col = {}
    total = 0
    for r, c in zip(row_ind, col_ind):
        team = team_names[r]
        if c == 9:
            rider, pts = extra_rider[team]
        else:
            rank_idx = 0 if c < 2 else c - 1
            rider = teams[team][rank_idx]
            pts = stage_points.get(rider, 0)
        by_col[c] = (rider, pts)
        total += pts

    slots = [
        {"rank": col + 1, "rider": by_col[col][0], "points": by_col[col][1]}
        for col in range(n_cols)
    ]
    return total, slots


def stage_breakdown(stage_data, teams=None):
    """Per-stage debug view: every jersey/etappe-uitslag ranking with the
    points each rider got for it, plus a per-rider total across all of them
    (a rider can appear in multiple jerseys the same day). If `teams` (the
    master brand-team rosters) is given, also computes the theoretical best
    possible hoofdploeg score for the day."""
    components = {}
    totals = {}
    for key, scale in DAILY_SCALES.items():
        ranked_names = (stage_data.get(key) or [])[:scale]
        pts_map = rank_points(ranked_names, scale)
        components[key] = [
            {"rank": i + 1, "rider": name, "points": pts_map[name]}
            for i, name in enumerate(ranked_names) if name
        ]
        for name, pts in pts_map.items():
            totals[name] = totals.get(name, 0) + pts
    totals_sorted = [
        {"rider": name, "points": pts}
        for name, pts in sorted(totals.items(), key=lambda kv: -kv[1])
    ]

    result = {"components": components, "totals": totals_sorted}
    if teams:
        stage_points = stage_points_by_rider(stage_data)
        optimal_score, optimal_slots = optimal_hoofdploeg(stage_points, teams)
        result["optimal_hoofdploeg"] = {"score": optimal_score, "slots": optimal_slots}
    return result


def load_participants(resolve):
    """Loads participants and resolves rider names to the master roster's
    canonical spelling in place. Unresolvable names are left as-is (they will
    simply never match a result) and reported."""
    participants = []
    unresolved = {}
    for path in sorted(PARTICIPANTS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for team_key in ("hoofdploeg", "pannenkoeken"):
            for entry in data[team_key]:
                canonical = resolve(entry["rider"])
                if canonical:
                    entry["rider"] = canonical
                else:
                    unresolved.setdefault(entry["rider"], []).append(data["name"])
        participants.append(data)
    if unresolved:
        print(f"WARNING: {len(unresolved)} rider name(s) could not be resolved to the master "
              f"roster and will score 0 until fixed (fix at /admin, run scripts/app.py, or "
              f"run scripts/check_name_matches.py to just list them):")
        for raw, who in sorted(unresolved.items()):
            print(f"    {raw!r} (picked by {', '.join(who)})")
    return participants, sorted(unresolved.keys())


def load_stage_results():
    stages = {}
    for path in sorted(RESULTS_DIR.glob("stage_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        stages[data["stage"]] = data
    return stages


def load_final_results():
    final_path = RESULTS_DIR / "final.json"
    if final_path.exists():
        return json.loads(final_path.read_text(encoding="utf-8"))
    return None


def compute_bonus_points(participant, final):
    answers = participant.get("bonus_answers") or {}
    result = {"podium": 0, "gap_seconds": None, "dnf_count": None, "total": 0}
    if not final:
        return result

    guess_podium = set(answers.get("podium") or [])
    actual_podium = set(final.get("podium") or [])
    n_correct = len(guess_podium & actual_podium)
    result["podium"] = n_correct * BONUS_PODIUM_POINTS_PER_RIDER

    guess_gap = answers.get("gap_seconds")
    actual_gap = final.get("winner_gap_seconds")
    if guess_gap is not None and actual_gap is not None:
        result["gap_seconds"] = max(0, BONUS_GAP_MAX_POINTS - abs(guess_gap - actual_gap))

    guess_dnf = answers.get("dnf_count")
    actual_dnf = final.get("dnf_count")
    if guess_dnf is not None and actual_dnf is not None:
        result["dnf_count"] = max(0, BONUS_DNF_MAX_POINTS - abs(guess_dnf - actual_dnf))

    result["total"] = result["podium"] + (result["gap_seconds"] or 0) + (result["dnf_count"] or 0)
    return result


def compute_team(participant, team_key, stages, joker_stage, final, final_key_map, apply_joker):
    riders = [r["rider"] for r in participant[team_key]]
    by_stage = {}
    running_total = 0
    for stage_num in sorted(stages.keys()):
        stage_points = stage_points_by_rider(stages[stage_num])
        base_score = team_stage_score(riders, stage_points)
        is_joker = apply_joker and joker_stage is not None and stage_num == joker_stage
        score = base_score * 2 if is_joker else base_score
        running_total += score
        rider_breakdown = sorted(
            [{"rider": r, "points": stage_points.get(r, 0)} for r in riders],
            key=lambda x: -x["points"],
        )
        tooltip_lines = [f"{r['rider']}: {r['points']}" for r in rider_breakdown if r["points"] > 0]
        tooltip_lines.append(f"Totaal: {base_score}")
        by_stage[stage_num] = {
            "score": score,
            "base_score": base_score,
            "cumulative": running_total,
            "joker": is_joker,
            "rider_breakdown": rider_breakdown,
            "tooltip": "\n".join(tooltip_lines),
        }

    final_bonus = 0
    final_breakdown = {}
    if final:
        for result_key, final_key in final_key_map.items():
            scale = FINAL_SCALES[final_key]
            pts = rank_points(final.get(final_key) or [], scale)
            component_total = sum(pts.get(r, 0) for r in riders)
            final_breakdown[result_key] = component_total
            final_bonus += component_total
        running_total += final_bonus

    return {
        "riders": riders,
        "by_stage": by_stage,
        "stage_total": running_total - final_bonus,
        "final_bonus": final_bonus,
        "final_breakdown": final_breakdown,
        "total": running_total,
    }


FINAL_KEY_MAP = {
    "geel": "gc_final",
    "groen": "points_final",
    "bolletjes": "mountains_final",
    "wit": "youth_final",
}


def main():
    master = json.loads(TEAMS_MASTER_PATH.read_text(encoding="utf-8"))
    resolve = build_resolver(list(master["riders"].keys()))
    participants, unresolved_names = load_participants(resolve)
    stages = load_stage_results()
    final = load_final_results()

    standings = {
        "stages_available": sorted(stages.keys()),
        "final_available": final is not None,
        "unresolved_names": unresolved_names,
        "stage_breakdowns": {
            stage_num: stage_breakdown(stages[stage_num], master["teams"]) for stage_num in sorted(stages.keys())
        },
        "participants": [],
    }

    for p in participants:
        hoofd = compute_team(p, "hoofdploeg", stages, p.get("joker_stage"), final, FINAL_KEY_MAP, apply_joker=True)
        pannen = compute_team(p, "pannenkoeken", stages, p.get("joker_stage"), final, FINAL_KEY_MAP, apply_joker=False)
        bonus = compute_bonus_points(p, final)

        standings["participants"].append({
            "name": p["name"],
            "hoofdploeg": hoofd,
            "pannenkoeken": pannen,
            "bonus": bonus,
            "joker_stage": p.get("joker_stage"),
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(standings, indent=2, ensure_ascii=False), encoding="utf-8")

    ranked_hoofd = sorted(standings["participants"], key=lambda x: -x["hoofdploeg"]["total"])
    ranked_pannen = sorted(standings["participants"], key=lambda x: x["pannenkoeken"]["total"])
    print(f"Computed standings for {len(participants)} participants, "
          f"{len(stages)} stage(s) loaded, final={'yes' if final else 'no'}")
    print("\nHoofdpoule (high score wins):")
    for i, p in enumerate(ranked_hoofd, 1):
        print(f"  {i:2d}. {p['name']:10s} {p['hoofdploeg']['total']}")
    print("\nPannenkoeken (low score wins):")
    for i, p in enumerate(ranked_pannen, 1):
        print(f"  {i:2d}. {p['name']:10s} {p['pannenkoeken']['total']}")


if __name__ == "__main__":
    main()
