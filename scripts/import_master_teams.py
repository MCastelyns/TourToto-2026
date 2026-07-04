"""
One-time import of the official brand-team rider rankings (1-8 per team) from
'Merkploegen 2026.docx' into data/teams_master.json.

This is reference data used to validate hoofdploeg draft legality (max 1 rider
per brand team in slots 1-8, etc.) and to browse rosters. It is NOT used
directly for scoring (scoring works off of the participants' picks + race
results, matched by rider name).
"""
import json
import re
from pathlib import Path

import docx

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DOCX = ROOT / "source_files" / "Merkploegen 2026.docx"
OUT_PATH = ROOT / "data" / "teams_master.json"


def clean(s):
    return re.sub(r"\s+", " ", s.replace("\n", " ")).strip()


def main():
    d = docx.Document(SOURCE_DOCX)
    teams = {}  # team_name -> [rider names in slot order 1-8]

    for table in d.tables[:3]:  # the 3 tables that hold the 24 brand teams
        rows = [[clean(c.text) for c in row.cells] for row in table.rows]
        i = 0
        while i < len(rows):
            row = rows[i]
            # a header row: first cell blank/non-numeric, other cells are team names
            if row[0] == "" and any(cell for cell in row[1:]):
                team_names = row[1:]
                for name in team_names:
                    if name:
                        teams[name] = [None] * 8
                # next 8 rows are riders 1-8
                for slot in range(1, 9):
                    if i + slot >= len(rows):
                        break
                    rider_row = rows[i + slot]
                    for col, name in enumerate(team_names):
                        if not name:
                            continue
                        rider = rider_row[col + 1] if col + 1 < len(rider_row) else ""
                        if rider:
                            teams[name][slot - 1] = rider
                i += 9
            else:
                i += 1

    riders_master = {}
    for team, roster in teams.items():
        for slot, rider in enumerate(roster, start=1):
            if rider:
                riders_master[rider] = {"team": team, "slot": slot}

    OUT_PATH.write_text(
        json.dumps({"teams": teams, "riders": riders_master}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Parsed {len(teams)} brand teams, {len(riders_master)} riders -> {OUT_PATH}")
    for team, roster in teams.items():
        missing = sum(1 for r in roster if not r)
        if missing:
            print(f"  WARNING: {team} missing {missing}/8 riders: {roster}")


if __name__ == "__main__":
    main()
