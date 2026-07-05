"""
Renders data/computed/standings.json (produced by scoring.py) plus the raw
participant/results data into a single static site/index.html.

Run `python scoring.py` first (or use build.py to do both in order).
"""
import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

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


def count_owners(rosters):
    """How many participants have each rider somewhere on their hoofdploeg or
    pannenkoeken (counted once per participant, even if on both)."""
    counts = {}
    for data in rosters.values():
        riders_this_participant = {r["rider"] for r in data["hoofdploeg"]} | {r["rider"] for r in data["pannenkoeken"]}
        for rider in riders_this_participant:
            counts[rider] = counts.get(rider, 0) + 1
    return counts


def build_rider_info(rosters):
    """Enriches the master roster's {team, slot} per rider with fun-diagnostic
    fields for the tooltip: how many participants picked them, and whether
    they're currently marked as withdrawn."""
    rider_info = json.loads(TEAMS_MASTER_PATH.read_text(encoding="utf-8"))["riders"]
    owner_counts = count_owners(rosters)
    withdrawn = load_withdrawn()
    n_participants = len(rosters)
    for name, info in rider_info.items():
        info["n_owners"] = owner_counts.get(name, 0)
        info["n_participants"] = n_participants
        info["withdrawn"] = name in withdrawn
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
