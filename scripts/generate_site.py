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


def main():
    if not STANDINGS_PATH.exists():
        raise SystemExit("data/computed/standings.json not found — run scoring.py first")

    standings = json.loads(STANDINGS_PATH.read_text(encoding="utf-8"))
    rosters = load_participant_rosters()
    rider_info = build_rider_info(rosters)

    hoofd_ranked = sorted(standings["participants"], key=lambda p: -p["hoofdploeg"]["total"])
    pannen_ranked = sorted(standings["participants"], key=lambda p: p["pannenkoeken"]["total"])

    stages_available = standings["stages_available"]

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
        generated_at=datetime.now().strftime("%d-%m-%Y %H:%M"),
    )

    SITE_DIR.mkdir(exist_ok=True)
    (SITE_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"Wrote {SITE_DIR / 'index.html'}")


if __name__ == "__main__":
    main()
