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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALIASES_PATH = ROOT / "data" / "name_aliases.json"

_INITIAL_PREFIX = re.compile(r"^[a-z]\.\s*")
_APOSTROPHES = str.maketrans("", "", "'’‘`")


def normalize(name):
    n = name.strip().lower()
    n = re.sub(r"\s+", " ", n)
    n = _INITIAL_PREFIX.sub("", n)  # drop a leading "j. " / "v." style initial
    n = n.translate(_APOSTROPHES)  # fold straight/curly apostrophe variants away
    return n


def load_aliases():
    if ALIASES_PATH.exists():
        return json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    return {}


def build_resolver(master_riders):
    """master_riders: iterable of canonical rider names (from teams_master.json).
    Returns resolve(raw_name) -> canonical name or None."""
    aliases = load_aliases()
    by_normalized = {normalize(name): name for name in master_riders}

    def resolve(raw_name):
        if raw_name in master_riders:
            return raw_name
        if raw_name in aliases:
            return aliases[raw_name]
        norm = normalize(raw_name)
        if norm in by_normalized:
            return by_normalized[norm]
        return None

    return resolve
