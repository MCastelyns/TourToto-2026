"""
Thin client for the Tour de France Race Center API (racecenter.letour.fr).

This is an undocumented backend discovered by inspecting the Race Center SPA's
JS bundles (it's a Vue/Quasar app with a `LiveData.fetch(bindName)` -> GET
`/api/{bindName}` pattern). Known binds:

  allCompetitors-{year}    -> full startlist: bib, firstname, lastname, $team
  team-{year}              -> the 23 trade teams: code, name, _id
  rankingType-{year}-{n}   -> ALL classifications after stage n, as a list of
                              {"type": <code>, "rankings": [...]} objects.

Ranking type codes (found in chunk-common.js):
  ite = individual time, etappe (daily stage result)      -> our "stage_result"
  itg = individual time, general (yellow/GC)               -> our "gc"
  ipe/ipg = individual points, etappe/general (green)       -> our "points"
  ime/img = individual mountains, etappe/general (polka)    -> our "mountains"
  ije/ijg = individual jersey(youth), etappe/general (white)-> our "youth"
  ete/etg = team time, etappe/general (not used by us)
On a Team Time Trial stage there is no separate "ite" (individual stage result
equals the team's ("ete") result) - handle that as a known gap for now.
"""
import requests

BASE = "https://racecenter.letour.fr/api"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def _get(path):
    r = requests.get(f"{BASE}/{path}", headers=HEADERS, timeout=20)
    r.raise_for_status()
    if r.status_code == 204 or not r.text:
        return None
    return r.json()


def get_all_competitors(year):
    return _get(f"allCompetitors-{year}")


def get_teams(year):
    return _get(f"team-{year}")


def get_ranking_types(year, stage):
    """Returns the raw list of ranking-type entries for a stage. Each entry
    with a real `type` (itg/ipg/img/ijg/ite/... ) has a `rankings` list of
    {"bib": int, "position": int, ...}. Other entries in the list (checkpoint
    weather, etc.) are irrelevant and can be ignored."""
    data = _get(f"rankingType-{year}-{stage}")
    return [e for e in (data or []) if e.get("type")]
