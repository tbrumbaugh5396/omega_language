"""The weekly brief generator (Part 9, module 1).

A brief is a cross-product draw: form × constraint × feature bundle ×
primitive-to-practise, plus a deadline. Constraints generate and freedom
paralyses (Part 6), so every brief carries one.

Ambition escalates with `level`, which the caller derives from how many pieces
the user has actually shipped — not from how long they have been here.
"""
import datetime as dt
import random

from . import curriculum as cur


def week_id(day: dt.date | None = None) -> str:
    """ISO week label, e.g. 2026-W33. The unit the MAKE track runs on."""
    d = day or dt.date.today()
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def week_end(day: dt.date | None = None) -> str:
    """Sunday of the current ISO week — the deadline that makes it real."""
    d = day or dt.date.today()
    return (d + dt.timedelta(days=7 - d.isoweekday())).isoformat()


def _weighted(rng: random.Random, forms: list[dict], level: int) -> dict:
    """Pick a form, biased toward more ambitious ones as level rises.

    level 0 keeps weight-1 forms likely; by level 4 the heavy forms dominate.
    """
    scored = []
    for f in forms:
        # A weight-1 form starts likely and decays; weight-3 does the reverse.
        bias = 1.0 + (f["weight"] - 1) * (level / 4.0) - (3 - f["weight"]) * 0.1 * level
        scored.append(max(0.1, bias))
    return rng.choices(forms, weights=scored, k=1)[0]


def generate(seed: int, level: int = 0, craft: str = "any",
             avoid: list[str] | None = None) -> dict:
    """Build one brief. Deterministic in `seed` so a week's brief is stable.

    craft: 'any' | 'audio' | 'visual' — filters the forms.
    avoid: media the user has done recently; softly excluded to force range.
    """
    rng = random.Random(seed)
    avoid = avoid or []

    forms = cur.BRIEF_FORMS
    if craft == "audio":
        forms = [f for f in forms if f["medium"] == "audio"]
    elif craft == "visual":
        forms = [f for f in forms if f["medium"] != "audio"]
    fresh = [f for f in forms if f["medium"] not in avoid]
    form = _weighted(rng, fresh or forms, max(0, min(4, level)))

    constraint = rng.choice(cur.BRIEF_CONSTRAINTS)
    bundle = rng.choice(cur.BRIEF_BUNDLES)
    primitive = rng.choice(cur.BRIEF_PRIMITIVES)
    minutes = [90, 120, 180, 240, 300][max(0, min(4, level))]

    return {
        "seed": seed,
        "level": level,
        "form": form["label"],
        "form_id": form["id"],
        "medium": form["medium"],
        "spec": form["spec"],
        "constraint": constraint,
        "bundle": bundle["label"],
        "bundle_features": bundle["features"],
        "primitive": primitive["label"],
        "primitive_lesson": primitive["lesson"],
        "budget_minutes": minutes,
        "week": week_id(),
        "deadline": week_end(),
        "line": (f"{form['label']} in the {bundle['label']} bundle "
                 f"({bundle['features']}), practising {primitive['label']}. "
                 f"Constraint: {constraint}"),
    }
