"""
Unified Tourtoto 2026 web app - runs locally only.

  /            local preview of the public dashboard (docs/index.html)
  /admin       password-protected admin panel (fix rider names, edit picks,
               confirm bib mappings, load new etappe results, publish)

Run locally:
    python scripts/app.py
    -> http://127.0.0.1:5000            (public site preview)
    -> http://127.0.0.1:5000/admin      (first visit asks you to set a password)

The actual public site is GitHub Pages, serving docs/ on the main branch -
"Publish" in /admin commits + pushes docs/index.html there. Everything else
(scraping, editing picks, rebuilding) stays local; nothing is hosted
publicly except the static docs/index.html GitHub Pages serves.

The admin password is stored in plain text in data/admin_password.json
(gitignored - never commit it). That's an explicit, accepted trade-off: this
protects against a stranger stumbling onto the URL, not against a determined
attacker, and that's all it needs to do here.
"""
import difflib
import functools
import json
import secrets
import subprocess
from pathlib import Path

from flask import Flask, redirect, render_template, request, session, url_for

import scoring
import generate_site
import scrape_results
from names import build_resolver, load_aliases

ROOT = Path(__file__).resolve().parent.parent
PARTICIPANTS_DIR = ROOT / "data" / "participants"
ALIASES_PATH = ROOT / "data" / "name_aliases.json"
DISMISSED_PATH = ROOT / "data" / "name_dismissed.json"
TEAMS_MASTER_PATH = ROOT / "data" / "teams_master.json"
BIB_MAP_PATH = ROOT / "data" / "rider_bib_map.json"
BIB_MAP_OVERRIDES_PATH = ROOT / "data" / "rider_bib_map_overrides.json"
BIB_CANDIDATES_PATH = ROOT / "data" / "rider_bib_map_candidates.json"
RESULTS_DIR = ROOT / "data" / "results"
SITE_DIR = ROOT / "docs"  # GitHub Pages serves from a "docs/" folder on the main branch
PASSWORD_PATH = ROOT / "data" / "admin_password.json"
SECRET_KEY_PATH = ROOT / "data" / "flask_secret_key.txt"

app = Flask(__name__, template_folder=str(ROOT / "templates"))

if not SECRET_KEY_PATH.exists():
    SECRET_KEY_PATH.write_text(secrets.token_hex(32), encoding="utf-8")
app.secret_key = SECRET_KEY_PATH.read_text(encoding="utf-8").strip()


# --- auth --------------------------------------------------------------

def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/admin/setup", methods=["GET", "POST"])
def admin_setup():
    if PASSWORD_PATH.exists():
        return redirect(url_for("admin_login"))
    error = None
    if request.method == "POST":
        pw = request.form.get("password", "")
        pw2 = request.form.get("password2", "")
        if len(pw) < 4:
            error = "Kies een wachtwoord van minstens 4 tekens."
        elif pw != pw2:
            error = "Wachtwoorden komen niet overeen."
        else:
            PASSWORD_PATH.write_text(json.dumps({"password": pw}), encoding="utf-8")
            session["admin_logged_in"] = True
            return redirect(url_for("admin_index"))
    return render_template("admin_login.html.j2", mode="setup", error=error)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not PASSWORD_PATH.exists():
        return redirect(url_for("admin_setup"))
    error = None
    if request.method == "POST":
        stored = json.loads(PASSWORD_PATH.read_text(encoding="utf-8"))["password"]
        if secrets.compare_digest(request.form.get("password", ""), stored):
            session["admin_logged_in"] = True
            return redirect(url_for("admin_index"))
        error = "Onjuist wachtwoord."
    return render_template("admin_login.html.j2", mode="login", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


# --- public site ---------------------------------------------------------

@app.route("/")
def public_site():
    index_path = SITE_DIR / "index.html"
    if not index_path.exists():
        return "Nog geen site gegenereerd.", 503
    return index_path.read_text(encoding="utf-8")


# --- admin: data loading helpers -----------------------------------------

def load_master_riders():
    master = json.loads(TEAMS_MASTER_PATH.read_text(encoding="utf-8"))
    return sorted(master["riders"].keys())


def load_dismissed():
    if DISMISSED_PATH.exists():
        return set(json.loads(DISMISSED_PATH.read_text(encoding="utf-8")))
    return set()


def save_dismissed(dismissed):
    DISMISSED_PATH.write_text(json.dumps(sorted(dismissed), indent=2, ensure_ascii=False), encoding="utf-8")


def find_unresolved(master_riders):
    """Raw rider names picked by anyone that don't resolve to the master roster,
    with fuzzy suggestions, excluding ones already dismissed."""
    resolve = build_resolver(master_riders)
    dismissed = load_dismissed()
    unresolved = {}
    for path in sorted(PARTICIPANTS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        picks = [r["rider"] for r in data["hoofdploeg"]] + [r["rider"] for r in data["pannenkoeken"]]
        for raw in picks:
            if raw in dismissed:
                continue
            if resolve(raw) is None:
                unresolved.setdefault(raw, {"picked_by": [], "suggestions": []})
                unresolved[raw]["picked_by"].append(data["name"])
    for raw, info in unresolved.items():
        info["suggestions"] = difflib.get_close_matches(raw, master_riders, n=5, cutoff=0.5)
    return unresolved


def participant_status(data):
    missing = []
    if len(data["hoofdploeg"]) < 10:
        missing.append(f"hoofdploeg {len(data['hoofdploeg'])}/10")
    if len(data["pannenkoeken"]) < 15:
        missing.append(f"pannenkoeken {len(data['pannenkoeken'])}/15")
    if not data.get("joker_stage"):
        missing.append("geen jokeretappe")
    b = data.get("bonus_answers") or {}
    if not b.get("podium"):
        missing.append("bonus: podium")
    if b.get("gap_seconds") is None:
        missing.append("bonus: tijdsverschil")
    if b.get("dnf_count") is None:
        missing.append("bonus: uitvallers")
    return missing


def load_all_participants():
    out = []
    for path in sorted(PARTICIPANTS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_missing"] = participant_status(data)
        data["_hoofd_lines"] = riders_to_lines(data["hoofdploeg"], with_team=True)
        data["_pannen_lines"] = riders_to_lines(data["pannenkoeken"], with_team=False)
        out.append(data)
    return out


def riders_to_lines(entries, with_team=False):
    lines = []
    for e in entries:
        if with_team and e.get("team"):
            lines.append(f"{e['rider']} | {e['team']}")
        else:
            lines.append(e["rider"])
    return "\n".join(lines)


def lines_to_riders(text, with_team=False):
    entries = []
    for i, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if with_team and "|" in line:
            rider, team = line.split("|", 1)
            entries.append({"slot": i, "rider": rider.strip(), "team": team.strip() or None})
        else:
            entry = {"slot": i, "rider": line}
            if with_team:
                entry["team"] = None
            entries.append(entry)
    # renumber slots contiguously
    for i, e in enumerate(entries, start=1):
        e["slot"] = i
    return entries


def load_bib_candidates():
    if BIB_CANDIDATES_PATH.exists():
        return json.loads(BIB_CANDIDATES_PATH.read_text(encoding="utf-8"))
    return []


# --- admin: routes ---------------------------------------------------------

@app.route("/admin")
@login_required
def admin_index():
    master_riders = load_master_riders()
    unresolved = find_unresolved(master_riders)
    participants = load_all_participants()
    # incomplete ones first
    participants.sort(key=lambda d: (len(d["_missing"]) == 0, d["name"]))
    message = request.args.get("msg")

    bib_candidates = load_bib_candidates()
    n_bib_confirmed = sum(1 for c in bib_candidates if c.get("confirmed_bib"))

    return render_template(
        "admin.html.j2",
        unresolved=unresolved,
        participants=participants,
        master_riders=master_riders,
        n_bib_total=len(bib_candidates),
        n_bib_confirmed=n_bib_confirmed,
        message=message,
    )


@app.route("/admin/bib-review")
@login_required
def bib_review():
    candidates = load_bib_candidates()
    teams = {}
    for c in candidates:
        teams.setdefault(c["master_team"], []).append(c)
    for riders in teams.values():
        riders.sort(key=lambda c: c["slot"])
    return render_template("bib_review.html.j2", teams=teams, message=request.args.get("msg"))


@app.route("/admin/confirm-bib-map", methods=["POST"])
@login_required
def confirm_bib_map():
    """The whole review form is the source of truth at submit time: every
    non-blank dropdown becomes a confirmed mapping, replacing whatever was
    confirmed before (so explicitly clearing a dropdown un-confirms it)."""
    confirmed = {}
    for key, value in request.form.items():
        if not key.startswith("bib__") or not value:
            continue
        rider = request.form.get(f"rider__{key[len('bib__'):]}")
        if rider:
            confirmed[rider] = int(value)

    BIB_MAP_OVERRIDES_PATH.write_text(json.dumps(confirmed, indent=2, ensure_ascii=False), encoding="utf-8")
    BIB_MAP_PATH.write_text(json.dumps(confirmed, indent=2, ensure_ascii=False), encoding="utf-8")

    # keep the candidates file's confirmed_bib in sync so the review page
    # reopens showing what's already confirmed
    candidates = load_bib_candidates()
    for c in candidates:
        c["confirmed_bib"] = confirmed.get(c["master_rider"])
    BIB_CANDIDATES_PATH.write_text(json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8")

    return redirect(url_for("bib_review", msg=f"{len(confirmed)}/{len(candidates)} renners bevestigd"))


@app.route("/admin/resolve-name", methods=["POST"])
@login_required
def resolve_name():
    raw = request.form["raw_name"]
    canonical = request.form["canonical"].strip()
    aliases = load_aliases()
    aliases[raw] = canonical
    ALIASES_PATH.write_text(json.dumps(aliases, indent=2, ensure_ascii=False), encoding="utf-8")
    return redirect(url_for("admin_index", msg=f"'{raw}' -> '{canonical}' opgeslagen als alias"))


@app.route("/admin/dismiss-name", methods=["POST"])
@login_required
def dismiss_name():
    raw = request.form["raw_name"]
    dismissed = load_dismissed()
    dismissed.add(raw)
    save_dismissed(dismissed)
    return redirect(url_for("admin_index", msg=f"'{raw}' genegeerd (blijft 0 punten scoren tot opgelost)"))


@app.route("/admin/save-participant/<name>", methods=["POST"])
@login_required
def save_participant(name):
    path = PARTICIPANTS_DIR / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    data["hoofdploeg"] = lines_to_riders(request.form.get("hoofdploeg", ""), with_team=True)
    data["pannenkoeken"] = lines_to_riders(request.form.get("pannenkoeken", ""), with_team=False)

    joker_raw = request.form.get("joker_stage", "").strip()
    data["joker_stage"] = int(joker_raw) if joker_raw else None

    podium_raw = request.form.get("bonus_podium", "").strip()
    data["bonus_answers"]["podium"] = (
        [p.strip() for p in podium_raw.split(",") if p.strip()] if podium_raw else None
    )
    gap_raw = request.form.get("bonus_gap", "").strip()
    data["bonus_answers"]["gap_seconds"] = int(gap_raw) if gap_raw else None
    dnf_raw = request.form.get("bonus_dnf", "").strip()
    data["bonus_answers"]["dnf_count"] = int(dnf_raw) if dnf_raw else None

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return redirect(url_for("admin_index", msg=f"{name} opgeslagen"))


@app.route("/admin/rebuild", methods=["POST"])
@login_required
def rebuild():
    scoring.main()
    generate_site.main()
    return redirect(url_for("admin_index", msg="Site herbouwd - bekijk hem op /"))


@app.route("/admin/publish", methods=["POST"])
@login_required
def publish():
    """Commits + pushes docs/index.html to GitHub, which GitHub Pages serves
    publicly. Relies on git already being able to push from this machine
    (whatever credential helper/SSH key you normally use for git push)."""
    def run(*args):
        return subprocess.run(args, cwd=ROOT, capture_output=True, text=True)

    add = run("git", "add", "docs/index.html")
    if add.returncode != 0:
        return redirect(url_for("admin_index", msg=f"git add mislukt: {add.stderr.strip()}"))

    # returncode 0 = nothing staged (docs/index.html unchanged), 1 = there is a staged diff
    staged_diff = run("git", "diff", "--cached", "--quiet", "--", "docs/index.html")
    if staged_diff.returncode == 0:
        return redirect(url_for("admin_index", msg="Niets nieuws om te publiceren - docs/index.html is ongewijzigd."))

    commit = run("git", "commit", "-m", "Update results", "--", "docs/index.html")
    if commit.returncode != 0:
        return redirect(url_for("admin_index", msg=f"git commit mislukt: {(commit.stdout + commit.stderr).strip()}"))

    push = run("git", "push")
    if push.returncode != 0:
        return redirect(url_for("admin_index", msg=f"git push mislukt: {push.stderr.strip()}"))

    return redirect(url_for("admin_index", msg="Gepubliceerd - live over ~1 minuut op GitHub Pages."))


@app.route("/admin/scrape-stage", methods=["POST"])
@login_required
def scrape_stage_route():
    """Attempts to fetch a stage's results directly from this server. Works
    only if the host's outbound internet can reach racecenter.letour.fr - on
    some free hosts (e.g. PythonAnywhere's free tier) that's blocked, in which
    case use the upload fallback below instead."""
    stage_raw = request.form.get("stage", "").strip()
    if not stage_raw.isdigit():
        return redirect(url_for("admin_index", msg="Ongeldig etappenummer"))
    stage = int(stage_raw)

    try:
        result, notes, warnings = scrape_results.scrape_stage(stage)
    except Exception as e:
        return redirect(url_for(
            "admin_index",
            msg=f"Ophalen van etappe {stage} mislukt: {e}. Kan de server geen internet bereiken? "
                f"Gebruik dan de upload-optie hieronder.",
        ))

    # Results occasionally get adjusted shortly after a stage finishes (time
    # penalties, a photo-finish review, a late jury decision) - re-fetch the
    # previous stage too so those corrections aren't stuck with whatever the
    # API returned right after it finished.
    previous_path = RESULTS_DIR / f"stage_{stage - 1:02d}.json"
    if stage > 1 and previous_path.exists():
        try:
            scrape_results.scrape_stage(stage - 1)
            notes.append(f"Etappe {stage - 1} ook opnieuw opgehaald (voor eventuele "
                         f"naderhand aangepaste tijdstraffen/uitslagen).")
        except Exception:
            pass  # non-fatal - the new stage's own data still gets saved either way

    scoring.main()
    generate_site.main()
    msg = f"Etappe {stage} opgehaald en site herbouwd."
    if notes:
        msg += " " + " ".join(notes)
    if warnings:
        msg += " " + " ".join(warnings)
    return redirect(url_for("admin_index", msg=msg))


@app.route("/admin/upload-stage", methods=["POST"])
@login_required
def upload_stage():
    """Fallback for when the server can't reach the Tour's API directly: run
    `python scripts/scrape_results.py --stage N` on your own PC, then upload
    the resulting data/results/stage_NN.json file here."""
    file = request.files.get("stage_file")
    if not file or not file.filename:
        return redirect(url_for("admin_index", msg="Geen bestand gekozen"))

    try:
        data = json.loads(file.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return redirect(url_for("admin_index", msg="Bestand is geen geldig JSON-bestand"))

    stage = data.get("stage")
    if not isinstance(stage, int):
        return redirect(url_for("admin_index", msg="JSON mist een geldig 'stage' veld"))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"stage_{stage:02d}.json"
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    scoring.main()
    generate_site.main()
    return redirect(url_for("admin_index", msg=f"Etappe {stage} geupload en site herbouwd."))


if __name__ == "__main__":
    import os
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
