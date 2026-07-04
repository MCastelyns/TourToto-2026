"""
Run this after import_from_excel.py / import_master_teams.py to find picked
rider names that don't resolve to the master roster, with fuzzy-match
suggestions. Review the output and add confirmed corrections to
data/name_aliases.json as {"as typed in sheet": "canonical master name"}.
"""
import difflib
import json
from pathlib import Path

from names import build_resolver, load_aliases

ROOT = Path(__file__).resolve().parent.parent


def main():
    master = json.loads((ROOT / "data" / "teams_master.json").read_text(encoding="utf-8"))
    master_riders = list(master["riders"].keys())
    resolve = build_resolver(master_riders)
    aliases = load_aliases()

    unresolved = {}  # raw_name -> [participant names that used it]
    for path in sorted((ROOT / "data" / "participants").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        picks = [r["rider"] for r in data["hoofdploeg"]] + [r["rider"] for r in data["pannenkoeken"]]
        for raw in picks:
            if resolve(raw) is None:
                unresolved.setdefault(raw, []).append(data["name"])

    print(f"{len(unresolved)} unresolved rider name(s) (out of names picked by any participant):\n")
    for raw, participants in sorted(unresolved.items()):
        suggestions = difflib.get_close_matches(raw, master_riders, n=3, cutoff=0.6)
        picked_by = ", ".join(participants)
        print(f"  {raw!r:25s} picked by [{picked_by}]")
        print(f"      suggestions: {suggestions}")

    print(f"\n{len(aliases)} alias(es) already recorded in data/name_aliases.json")
    print("Add confirmed fixes there as: \"raw name\": \"canonical master name\"")


if __name__ == "__main__":
    main()
