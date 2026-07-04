"""
One-time (per season) build of the rider <-> official bib number review queue.

Why this exists: the scraper reports results by bib number (the only truly
unambiguous ID). Everything downstream (scoring.py) works with our existing
master-roster rider names, so this mapping is the ONE place bib<->name
matching needs to happen — and it needs to be exactly right, once, forever.

This script does NOT commit anything by itself. It only computes a
best-guess suggestion per rider (via formatting-tolerant surname matching:
initials, hyphens, glued names, compound surnames) and writes
data/rider_bib_map_candidates.json for every one of the ~184 riders, each
with its suggestion (if any) plus the full list of that rider's teammates to
pick from. Nothing is trusted blindly - review and confirm each one at
`/admin` (run `python scripts/app.py`) in the "Koppeling met startlijst"
section. Only confirmed entries end up in data/rider_bib_map.json /
data/rider_bib_map_overrides.json.

Re-running this script is always safe: it never overwrites an already
confirmed mapping (data/rider_bib_map_overrides.json), it only regenerates
suggestions for whatever isn't confirmed yet.
"""
import json
import re
import unicodedata
from pathlib import Path

from api_client import get_all_competitors, get_teams

ROOT = Path(__file__).resolve().parent.parent
TEAMS_MASTER_PATH = ROOT / "data" / "teams_master.json"
BIB_MAP_PATH = ROOT / "data" / "rider_bib_map.json"
OVERRIDES_PATH = ROOT / "data" / "rider_bib_map_overrides.json"
CANDIDATES_PATH = ROOT / "data" / "rider_bib_map_candidates.json"
YEAR = 2026

# Our master roster team name -> Race Center API team code.
# Built by hand-matching the 23 teams (data/teams_master.json) against the
# `team-2026` API response - both lists have exactly 23 teams for 2026.
TEAM_CODE_MAP = {
    "ALPECIN": "APT",
    "Pinarello Q36.5": "PQT",
    "BAHRAIN": "TBV",
    "COFIDIS": "COF",
    "DECATHLON": "DCT",
    "EF EDUCATION": "EFE",
    "GROUPAMA FDJ": "GFC",
    "Netcompany INEOS": "NCI",
    "Caja Rural Serguros RGA": "CJR",
    "NSN Cycling": "NSN",
    "LIDL TREK": "LTK",
    "LOTTO Intermarche": "LOI",
    "MOVISTAR": "MOV",
    "RED BULL BORA": "RBH",
    "SOUDAL QUICKSTEP": "SOQ",
    "JAYCO ALULA": "JAY",
    "PICNIC POSTNL": "TPP",
    "VISMA LEASE A BIKE": "TVL",
    "TUDOR PRO CYCLING": "TUD",
    "UAE TEAM EMIRATES": "UEX",
    "UNO X MOBILITY": "UXM",
    "XDS ASTANA": "XAT",
    "TOTAL ENERGIES": "TEN",
}


_INITIAL_PREFIX = re.compile(r"^[a-z]\.\s*")
_PARTICLES = {"van", "der", "den", "de", "la", "le", "dos", "du", "al", "el", "da"}


def strip_diacritics(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s):
    s = strip_diacritics(s).lower().strip()
    s = _INITIAL_PREFIX.sub("", s)  # drop a leading "j." / "i." style initial
    return s


def tokens(s):
    return [t for t in re.split(r"[\s\-]+", norm(s)) if t]


def lastname_match(master_name, competitor_lastname):
    """Formatting-tolerant match only (initials, hyphen/space variance, glued
    names, compound surnames where the API has extra name parts we don't
    carry). This produces a SUGGESTION only - it is never auto-committed."""
    m_tokens, c_tokens = tokens(master_name), tokens(competitor_lastname)
    if not c_tokens:
        return False
    # e.g. "vanMechelen" (no space) vs "Van Mechelen" -> compare with all spaces stripped
    if "".join(m_tokens) == "".join(c_tokens):
        return True
    # shared distinctive (3+ char, non-particle) word, e.g. "Vd Poel"/"Van Der Poel"
    # both contain "poel", "A.Paret-Pientre"/"Paret Peintre" both contain "paret",
    # "Cees Bol"/"Cees Bol" both contain "bol"
    m_sig = _signature(m_tokens)
    c_sig = _signature(c_tokens)
    return bool(m_sig & c_sig)


def _signature(toks):
    sig = {t for t in toks if len(t) >= 3 and t not in _PARTICLES}
    # "vdBerg" glued shorthand for "Van Den Berg" -> also register "berg"
    for t in toks:
        if t.startswith("vd") and len(t) > 4:
            sig.add(t[2:])
    return sig


def main():
    print("Fetching competitors + teams from Race Center API...")
    competitors = get_all_competitors(YEAR)
    teams = get_teams(YEAR)
    master = json.loads(TEAMS_MASTER_PATH.read_text(encoding="utf-8"))

    team_id_to_code = {f"team-{YEAR}:{t['_id']}": t["code"] for t in teams}
    competitors_by_team_code = {}
    for c in competitors:
        team_id = c.get("$team")
        code = team_id_to_code.get(team_id)
        competitors_by_team_code.setdefault(code, []).append(c)

    overrides = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8")) if OVERRIDES_PATH.exists() else {}

    candidates_out = []
    for master_team, roster in master["teams"].items():
        code = TEAM_CODE_MAP.get(master_team)
        if not code:
            print(f"WARNING: no API team code mapped for master team {master_team!r} - skipping")
            continue
        team_competitors = sorted(competitors_by_team_code.get(code, []), key=lambda c: c["bib"])
        for slot, rider in enumerate(roster, start=1):
            if not rider:
                continue
            matches = [c for c in team_competitors if lastname_match(rider, c["lastname"])]
            suggested_bib = matches[0]["bib"] if len(matches) == 1 else None
            candidates_out.append({
                "master_rider": rider,
                "master_team": master_team,
                "slot": slot,
                "confirmed_bib": overrides.get(rider),
                "suggested_bib": suggested_bib,
                "candidates": [
                    {"bib": c["bib"], "name": f"{c['firstname']} {c['lastname']}"}
                    for c in team_competitors
                ],
            })

    CANDIDATES_PATH.write_text(json.dumps(candidates_out, indent=2, ensure_ascii=False), encoding="utf-8")

    # rider_bib_map.json only ever holds human-confirmed entries
    BIB_MAP_PATH.write_text(json.dumps(overrides, indent=2, ensure_ascii=False), encoding="utf-8")

    n_confirmed = sum(1 for c in candidates_out if c["confirmed_bib"])
    n_unconfirmed = [c for c in candidates_out if not c["confirmed_bib"]]
    n_unconfirmed_with_suggestion = sum(1 for c in n_unconfirmed if c["suggested_bib"])
    print(f"\n{len(candidates_out)} riders total, {n_confirmed} confirmed")
    if n_unconfirmed:
        print(f"  {len(n_unconfirmed)} still awaiting confirmation "
              f"({n_unconfirmed_with_suggestion} have a formatting-match suggestion, "
              f"{len(n_unconfirmed) - n_unconfirmed_with_suggestion} have no suggestion at all)")
    if n_unconfirmed:
        print(f"\nReview & confirm the rest at /admin/bib-review "
              f"(run `python scripts/app.py`) before scraping any results.")
    else:
        print("\nAll riders confirmed - ready to scrape results.")


if __name__ == "__main__":
    main()
