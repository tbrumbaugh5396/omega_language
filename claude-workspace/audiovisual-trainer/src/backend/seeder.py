"""Starter content, so a new account has something to read against.

Deliberately small: three pieces at different stages, a week of practice, a
few pulled theory items and one articulation rep. The point is to show the
shape of the loop — brief, make, break, pull theory — not to pretend you have
a history.
"""
import datetime as dt
import json

from . import briefs, db


def _ago(days: int) -> str:
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


def seed_user(con, uid: int) -> dict:
    """Insert starter rows for a user. Skips anything already present."""
    added = {"pieces": 0, "practice": 0, "progress": 0, "articulation": 0}
    now = db.now()

    have_pieces = con.execute("SELECT COUNT(*) c FROM pieces WHERE user_id=?",
                              (uid,)).fetchone()["c"]
    if not have_pieces:
        seed_pieces = [
            {
                "title": "Two-colour title card",
                "week": briefs.week_id(dt.date.today() - dt.timedelta(days=14)),
                "medium": "motion",
                "constraint_note": "Two colours only, plus paper.",
                "rubric": "Reads at 25% size. The motion has a reason. Nothing "
                          "on screen that isn't doing work.",
                "status": "shipped",
                "deadline": _ago(9),
                "shipped": _ago(9),
                "brief": {
                    "form": "A title card", "medium": "motion",
                    "bundle": "Swiss / International Typographic",
                    "bundle_features": "grid, asymmetric balance, objective "
                                       "photography, Helvetica lineage",
                    "constraint": "Two colours only, plus paper.",
                    "primitive": "easing and overshoot",
                    "primitive_lesson": "motion-grammar",
                    "budget_minutes": 90,
                },
                "pm_reads": "The type lands too hard and then sits still. It "
                            "reads as a slide, not a card.",
                "pm_why": "Linear-in, hard stop. No overshoot, so nothing "
                          "communicates mass — the eye reads it as a state "
                          "change rather than an object arriving.",
                "pm_study": "Easing curves; specifically what overshoot and "
                            "settle are doing.",
                "pm_slug": "motion-grammar",
            },
            {
                "title": "Sound-designed loop — dub bundle",
                "week": briefs.week_id(dt.date.today() - dt.timedelta(days=7)),
                "medium": "audio",
                "constraint_note": "Mono audio only.",
                "rubric": "Loops seamlessly. Three layers that stay separable. "
                          "Survives a phone speaker.",
                "status": "shipped",
                "deadline": _ago(2),
                "shipped": _ago(2),
                "brief": {
                    "form": "A sound-designed loop", "medium": "audio",
                    "bundle": "Dub",
                    "bundle_features": "offbeat skank, drop-outs, delay throws, "
                                       "mix-as-instrument",
                    "constraint": "Mono audio only.",
                    "primitive": "delay lines",
                    "primitive_lesson": "delay-lines",
                    "budget_minutes": 120,
                },
                "pm_reads": "Busy but not clear. The skank and the bass are "
                            "fighting and raising either one wrecks it.",
                "pm_why": "They occupy the same band around 200-400 Hz. It is "
                          "masking, not level — which is why the fader didn't "
                          "fix it.",
                "pm_study": "Critical bands and slotting.",
                "pm_slug": "masking",
            },
            {
                "title": "",
                "week": briefs.week_id(),
                "medium": "shader",
                "constraint_note": "Everything must be built from one primitive.",
                "rubric": "",
                "status": "briefed",
                "deadline": briefs.week_end(),
                "shipped": "",
                "brief": {
                    "form": "A shader sketch", "medium": "shader",
                    "bundle": "Op art",
                    "bundle_features": "perceptual vibration, moiré, "
                                       "high-frequency pattern",
                    "constraint": "Everything must be built from one primitive.",
                    "primitive": "signed distance fields",
                    "primitive_lesson": "sdf",
                    "budget_minutes": 180,
                },
                "pm_reads": "", "pm_why": "", "pm_study": "", "pm_slug": "",
            },
        ]
        for p in seed_pieces:
            con.execute(
                "INSERT INTO pieces(user_id,title,week,brief,medium,"
                "constraint_note,rubric,status,deadline,shipped,link,pm_reads,"
                "pm_why,pm_study,pm_slug,created,updated) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (uid, p["title"], p["week"], json.dumps(p["brief"]), p["medium"],
                 p["constraint_note"], p["rubric"], p["status"], p["deadline"],
                 p["shipped"], "", p["pm_reads"], p["pm_why"], p["pm_study"],
                 p["pm_slug"], now, now))
            added["pieces"] += 1

    have_practice = con.execute(
        "SELECT COUNT(*) c FROM practice_log WHERE user_id=?", (uid,)
    ).fetchone()["c"]
    if not have_practice:
        seed_practice = [
            (1, "tools", "Resolve", "", "Node graph without the mouse — "
             "keyboard only for one grade", 45, 3,
             "Still hunting for the qualifier. Not invisible yet."),
            (2, "perception", "", "masking", "eq-band-id at level 3", 15, 4,
             "Low mids are still a blur below 400."),
            (3, "make", "Reaper", "delay-lines", "Dub loop — delay throws", 120, 4,
             "The throw is easy. The restraint is not."),
            (4, "theory", "", "masking", "Read critical bands after the mix "
             "fought me", 25, 5,
             "Answered exactly the thing that broke. This is what pulled "
             "theory means."),
            (5, "tools", "Shadertoy", "sdf", "smin by hand, no reference", 40, 2,
             "Got the blend, lost an hour to a sign error."),
            (6, "perception", "", "", "Kerning drill, 3 rounds", 12, 3,
             "Better on tight pairs, still bad on round-to-straight."),
        ]
        for days, track, tool, slug, focus, minutes, rating, notes in seed_practice:
            con.execute(
                "INSERT INTO practice_log(user_id,day,track,tool,slug,focus,"
                "minutes,rating,notes,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (uid, _ago(days), track, tool, slug, focus, minutes, rating,
                 notes, now))
            added["practice"] += 1

    have_progress = con.execute("SELECT COUNT(*) c FROM progress WHERE user_id=?",
                                (uid,)).fetchone()["c"]
    if not have_progress:
        seed_progress = [
            ("motion-grammar", "applied", 3, 40,
             "Title card read as a slide — no overshoot, no mass."),
            ("masking", "reading", 2, 25,
             "Skank and bass fighting at 200-400 Hz; the fader didn't fix it."),
            ("delay-lines", "applied", 3, 55, "Dub loop throws."),
        ]
        for slug, status, conf, minutes, pulled in seed_progress:
            con.execute(
                "INSERT INTO progress(user_id,slug,status,confidence,minutes,"
                "pulled_by,started,updated) VALUES(?,?,?,?,?,?,?,?)",
                (uid, slug, status, conf, minutes, pulled, now, now))
            added["progress"] += 1

    have_art = con.execute("SELECT COUNT(*) c FROM articulation WHERE user_id=?",
                           (uid,)).fetchone()["c"]
    if not have_art:
        con.execute(
            "INSERT INTO articulation(user_id,kind,slug,prompt,body,predicted,"
            "actual,score,created) VALUES(?,?,?,?,?,?,?,?,?)",
            (uid, "teachback", "compositing-algebra",
             "Explain one technique as if to a novice, in writing, no jargon.",
             "Why edges go dark when you scale a cut-out: the transparent "
             "pixels still have a colour, usually black. When the software "
             "shrinks the image it averages neighbouring pixels together, so "
             "that black gets averaged into the edge. Multiplying the colour "
             "by its own transparency first means the invisible pixels carry "
             "no colour to leak. That is all premultiplied alpha is.\n\n"
             "Gap I noticed writing this: I can say what it does but I had to "
             "look up why compositing then needs a different formula.",
             "", "", 0, now))
        added["articulation"] += 1

    return added
