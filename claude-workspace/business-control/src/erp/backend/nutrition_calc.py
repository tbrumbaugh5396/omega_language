"""Nutrition arithmetic, pure. Ported from macro-kitchen.

No database, no clock, no framework: callers hand in the profile, the
weigh-ins and the logged intake; this module answers with numbers. The
rules of the source survive intact:

- BMR is Mifflin-St Jeor; maintenance (TDEE) is BMR x activity factor.
- A goal maps to a daily adjustment through 7700 kcal per kg of body
  weight per week; the daily target never drops below 1000 kcal.
- Macro targets are percentage splits of the target (protein/carbs at
  4 kcal per gram, fat at 9).
- Observed maintenance is measured, not modelled: mean logged intake
  minus the calories represented by the weight slope over the same
  window. Partial logging days (< 800 kcal) are excluded so an honest
  gap deflates confidence, not the estimate; thin data returns None
  rather than a guess.
"""
from __future__ import annotations

import datetime

KCAL_PER_KG = 7700.0
TARGET_FLOOR = 1000.0

# observed-maintenance guardrails, same as the source
_WINDOW_DAYS = 35          # look back at most this far
_MIN_SPAN_DAYS = 12        # first-to-last weigh-in stretch that counts
_MIN_LOGGED_DAYS = 10      # fully-logged days required inside the span
_HONEST_DAY_KCAL = 800.0   # below this a day reads as a partial log
_SANE_LO, _SANE_HI = 800.0, 6000.0

DEFAULT_PROFILE = {
    "units": "metric", "sex": "male", "birth_year": 1990,
    "height_cm": 175.0, "activity": 1.55, "goal": "maintain",
    "rate_kg_week": 0.45, "goal_weight_kg": None,
    "protein_pct": 30, "carbs_pct": 40, "fat_pct": 30,
    "water_goal_ml": 2500, "fiber_goal_g": 30,
    "sodium_limit_mg": 2300, "sugar_limit_g": 50,
    "tdee_override": None,
}


def mifflin_bmr(kg: float, height_cm: float, age: int, sex: str) -> float:
    """Resting burn. The sex constant is the formula's, not a judgement."""
    return (10.0 * kg + 6.25 * height_cm - 5.0 * age
            + (-161.0 if sex == "female" else 5.0))


def daily_adjust(goal: str, rate_kg_week: float) -> float:
    """kcal/day the goal asks for: negative deficit, positive surplus."""
    if goal not in ("lose", "gain"):
        return 0.0
    sign = -1.0 if goal == "lose" else 1.0
    return sign * max(0.0, float(rate_kg_week or 0)) * KCAL_PER_KG / 7.0


def targets(profile: dict, latest_kg: float | None,
            today: datetime.date) -> dict:
    """Everything the app derives from a profile, in one place.

    Returns bmr/tdee/target as None when there is no weight to compute
    from (and no adopted observed maintenance); macro grams fall back to
    a 2000 kcal placeholder so the UI always has bars to draw.
    """
    p = {**DEFAULT_PROFILE, **{k: v for k, v in (profile or {}).items()
                               if v is not None or k == "goal_weight_kg"}}
    age = max(10, today.year - int(p["birth_year"] or 1990))
    override = p.get("tdee_override")
    override = float(override) if override and float(override) > 500 else None

    bmr = tdee = target = None
    adjust = 0.0
    if latest_kg:
        bmr = mifflin_bmr(float(latest_kg), float(p["height_cm"] or 175),
                          age, p["sex"])
        tdee = bmr * float(p["activity"] or 1.55)
    if override is not None:
        tdee = override           # measured maintenance beats the formula
    if tdee is not None:
        adjust = daily_adjust(p["goal"], p["rate_kg_week"])
        target = max(TARGET_FLOOR, tdee + adjust)

    t = target or 2000.0
    return {
        "profile": p, "age": age, "latest_kg": latest_kg,
        "bmr": round(bmr) if bmr is not None else None,
        "tdee": round(tdee) if tdee is not None else None,
        "target": round(target) if target is not None else None,
        "adjust": round(adjust),
        "override": round(override) if override is not None else None,
        "protein_g": round(t * (p["protein_pct"] / 100.0) / 4.0),
        "carbs_g": round(t * (p["carbs_pct"] / 100.0) / 4.0),
        "fat_g": round(t * (p["fat_pct"] / 100.0) / 9.0),
        "has_numbers": bool(latest_kg or override),
    }


def observed_tdee(weighins: list, intake_by_day: dict,
                  today: datetime.date) -> dict | None:
    """Real-world maintenance from (day, kg) weigh-ins and day->kcal logs.

    None means "not enough honest data yet" - never a shaky number.
    """
    if len(weighins) < 4:
        return None
    cutoff = (today - datetime.timedelta(days=_WINDOW_DAYS)).isoformat()
    win = sorted((d, kg) for d, kg in weighins if d >= cutoff)
    if len(win) < 4:
        return None

    def _daynum(s: str) -> int:
        return datetime.date.fromisoformat(s).toordinal()

    head, tail = win[:3], win[-3:]
    d0 = sum(_daynum(d) for d, _ in head) / 3.0
    d1 = sum(_daynum(d) for d, _ in tail) / 3.0
    span = d1 - d0
    if span < _MIN_SPAN_DAYS:
        return None
    slope = (sum(kg for _, kg in tail) / 3.0
             - sum(kg for _, kg in head) / 3.0) / span   # kg per day

    cals = [kcal for day, kcal in intake_by_day.items()
            if d0 <= _daynum(day) <= d1 and kcal >= _HONEST_DAY_KCAL]
    if len(cals) < _MIN_LOGGED_DAYS:
        return None
    intake = sum(cals) / len(cals)
    tdee = intake - slope * KCAL_PER_KG
    if not (_SANE_LO < tdee < _SANE_HI):
        return None
    return {"tdee": round(tdee), "days": round(span), "logged": len(cals)}


def day_on_target(kcal: float, target: float | None, goal: str) -> bool:
    """Adherence classifier: the rule bends to the goal's direction."""
    if not kcal or kcal <= 0 or not target:
        return False
    if goal == "lose":
        return kcal <= target * 1.05
    if goal == "gain":
        return kcal >= target * 0.95
    return abs(kcal - target) <= target * 0.10


def streaks(logged_days: set, today: datetime.date) -> dict:
    """Current run (an unlogged today doesn't break it yet) and best ever."""
    cur, d = 0, today
    if d.isoformat() not in logged_days:
        d = d - datetime.timedelta(days=1)
    while d.isoformat() in logged_days:
        cur += 1
        d = d - datetime.timedelta(days=1)
    best = run = 0
    prev = None
    for s in sorted(logged_days):
        day = datetime.date.fromisoformat(s)
        run = run + 1 if prev and (day - prev).days == 1 else 1
        best = max(best, run)
        prev = day
    return {"current": cur, "best": best}
