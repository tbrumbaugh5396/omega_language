"""A/B testing: auto-generated content variants, deterministic assignment,
conversion stats with a two-proportion z-test, and winner detection."""
import hashlib
import math
import random

from . import db

# Content pools the auto-generator draws from. {product} is filled from the
# top-selling product name so generated tests stay on-brand.
HEADLINES = {
    "purchase": [
        "Stock up on {product} — free shipping over $40",
        "{product}: the flavor your pantry is missing",
        "Limited run: {product} back in stock",
        "Family favorite. {product}, delivered.",
    ],
    "add_to_cart": [
        "Try {product} — small batch, big flavor",
        "New here? Start with {product}",
        "{product} — see why stores can't keep it shelved",
        "Real ingredients. Real {product}.",
    ],
}
CTAS = {
    "purchase": ["Shop now", "Get yours", "Order today", "Stock up"],
    "add_to_cart": ["Add to cart", "Try it", "Taste it first", "Start here"],
}
THEMES = ["default", "bold", "warm"]


def generate_variants(goal: str, product_name: str, n: int = 3) -> list[dict]:
    """Sample n variants with pairwise-distinct headlines and CTAs so every
    variant tests something visibly different; deterministic per (goal, product)."""
    goal = goal if goal in HEADLINES else "purchase"
    rng = random.Random(f"{goal}:{product_name}")
    n = min(n, len(HEADLINES[goal]), len(CTAS[goal]))
    heads = rng.sample(HEADLINES[goal], n)
    ctas = rng.sample(CTAS[goal], n)
    start = rng.randrange(len(THEMES))
    out = []
    for i in range(n):
        out.append({"name": f"variant-{chr(65 + i)}",
                    "headline": heads[i].format(product=product_name),
                    "cta": ctas[i],
                    "theme": THEMES[(start + i) % len(THEMES)]})
    return out


def assign(con, experiment_id: int, visitor_id: str):
    """Deterministic weighted bucket; persisted so results are attributable."""
    row = con.execute(
        "SELECT variant_id FROM assignments WHERE experiment_id=? AND visitor_id=?",
        (experiment_id, visitor_id)).fetchone()
    if row:
        return row["variant_id"]
    variants = con.execute(
        "SELECT id, weight FROM variants WHERE experiment_id=? ORDER BY id",
        (experiment_id,)).fetchall()
    if not variants:
        return None
    total = sum(v["weight"] for v in variants) or len(variants)
    h = int.from_bytes(hashlib.sha256(
        f"{experiment_id}:{visitor_id}".encode()).digest()[:8], "big")
    bucket = h % total
    acc = 0
    chosen = variants[-1]["id"]
    for v in variants:
        acc += v["weight"] or 1
        if bucket < acc:
            chosen = v["id"]
            break
    con.execute(
        "INSERT OR IGNORE INTO assignments(experiment_id, visitor_id, variant_id,"
        " assigned_at) VALUES(?,?,?,?)",
        (experiment_id, visitor_id, chosen, db.now()))
    con.commit()
    return chosen


def results(con, exp, cfg: dict) -> dict:
    """Per-variant exposures/conversions, z vs control (first variant), and a
    winner suggestion once every variant clears the exposure floor."""
    goal = exp["goal"] or "purchase"
    variants = con.execute(
        "SELECT * FROM variants WHERE experiment_id=? ORDER BY id",
        (exp["id"],)).fetchall()
    stats = []
    for v in variants:
        exposures = con.execute(
            "SELECT COUNT(*) c FROM assignments WHERE experiment_id=? AND variant_id=?",
            (exp["id"], v["id"])).fetchone()["c"]
        conversions = con.execute(
            "SELECT COUNT(DISTINCT visitor_id) c FROM events"
            " WHERE experiment_id=? AND variant_id=? AND step=?",
            (exp["id"], v["id"], goal)).fetchone()["c"]
        rate = conversions / exposures if exposures else 0.0
        stats.append({"variant": dict(v), "exposures": exposures,
                      "conversions": conversions, "rate": round(rate, 4)})

    min_n = cfg.get("ab_min_exposures", 30)
    zcrit = cfg.get("ab_significance_z", 1.96)
    if stats:
        control = stats[0]
        for s in stats[1:]:
            s["z_vs_control"] = round(
                _two_prop_z(control["conversions"], control["exposures"],
                            s["conversions"], s["exposures"]), 3)
    winner = None
    ready = stats and all(s["exposures"] >= min_n for s in stats)
    if ready:
        best = max(stats, key=lambda s: s["rate"])
        others = [s for s in stats if s is not best]
        significant = all(
            abs(_two_prop_z(best["conversions"], best["exposures"],
                            s["conversions"], s["exposures"])) >= zcrit
            for s in others if s["exposures"])
        winner = {"variant_id": best["variant"]["id"],
                  "name": best["variant"]["name"], "rate": best["rate"],
                  "significant": bool(significant and others)}
    return {"experiment": dict(exp), "goal": goal, "variants": stats,
            "min_exposures": min_n, "ready": bool(ready), "winner": winner}


def _two_prop_z(c1: int, n1: int, c2: int, n2: int) -> float:
    if not n1 or not n2:
        return 0.0
    p1, p2 = c1 / n1, c2 / n2
    p = (c1 + c2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) or 1e-9
    return (p2 - p1) / se
