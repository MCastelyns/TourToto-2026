"""
Shared rider-name resolution.

Participant picks were typed by hand across 21 spreadsheets and have
inconsistent casing, missing initials, and outright typos compared to the
master roster (Merkploegen 2026.docx). Silently fuzzy-matching these against
whatever a future results feed calls the rider is how you accidentally credit
the wrong person's points. So: resolve deterministically via normalization +
an explicit, human-reviewed alias file. Anything left over is reported loudly
instead of guessed.
"""
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALIASES_PATH = ROOT / "data" / "name_aliases.json"

_INITIAL_PREFIX = re.compile(r"^[a-z]\.\s*")
_LEADING_INITIAL = re.compile(r"^\s*([a-z])\.", re.IGNORECASE)
_APOSTROPHES = str.maketrans("", "", "'’‘`")


def normalize(name):
    n = name.strip().lower()
    n = re.sub(r"\s+", " ", n)
    n = _INITIAL_PREFIX.sub("", n)  # drop a leading "j. " / "v." style initial
    n = n.translate(_APOSTROPHES)  # fold straight/curly apostrophe variants away
    return n


def leading_initial(name):
    """The first initial letter of a "V. Surname" / "T.H. Surname" style name,
    lowercased, or None if the name doesn't start with one. This is the bit
    normalize() throws away - kept here so the resolver can still use it to
    tell same-surname riders apart (e.g. the Paret-Peintre / Johannessen
    brothers) and to reject a match whose initial contradicts the pick."""
    m = _LEADING_INITIAL.match(name)
    return m.group(1).lower() if m else None


def load_aliases():
    if ALIASES_PATH.exists():
        return json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    return {}


def build_resolver(master_riders):
    """master_riders: iterable of canonical rider names (from teams_master.json).
    Returns resolve(raw_name) -> canonical name or None.

    Resolution order: exact canonical name, then explicit alias, then a
    normalized-surname match. normalize() deliberately drops initials so a
    bare "Philipsen" still finds "J. Philipsen" - but that means several
    master riders can share one normalized surname (brothers, and the case
    normalize() only strips the *first* initial so "T.H." and "A.H."
    Johannessen collapse together). The old code stored these in a dict, so
    one rider silently overwrote the other and every bare-surname pick
    resolved to whichever won. Here we keep ALL of them and lean on the pick's
    leading initial to disambiguate, refusing to guess rather than crediting
    the wrong rider's points."""
    aliases = load_aliases()
    master_set = set(master_riders)
    by_normalized = defaultdict(list)
    for name in master_riders:
        by_normalized[normalize(name)].append(name)

    def resolve(raw_name):
        if raw_name in master_set:
            return raw_name
        if raw_name in aliases:
            return aliases[raw_name]

        candidates = by_normalized.get(normalize(raw_name))
        if not candidates:
            return None

        pick_initial = leading_initial(raw_name)
        if len(candidates) == 1:
            only = candidates[0]
            cand_initial = leading_initial(only)
            # A stated initial that contradicts the sole surname-match means
            # the surname was mistyped into a different rider's (e.g. Paul's
            # "V. Paret-Pientre" landing on "A.Paret-Pientre"). Don't guess -
            # report it so a human adds the right alias.
            if pick_initial and cand_initial and pick_initial != cand_initial:
                return None
            return only

        # Several master riders share this normalized surname - only an
        # initial can single one out. If it doesn't (or there isn't one),
        # leave it unresolved rather than pick arbitrarily.
        if pick_initial:
            matches = [c for c in candidates if leading_initial(c) == pick_initial]
            if len(matches) == 1:
                return matches[0]
        return None

    return resolve
