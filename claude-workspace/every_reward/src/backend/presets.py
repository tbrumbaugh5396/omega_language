"""Pull-rate presets for fixed-odds markets.

Probabilities are community-documented approximations — real rates vary by
set and print run, and the admin can edit the filled-in odds before creating
the market. Offered odds = fair odds (1/p) shaved by fixed_odds_margin_bps,
the house's edge for carrying fixed-odds book risk.
"""

PULL_RATE_PRESETS = [
    {"key": "poke_pack_hit", "game": "pokemon",
     "label": "Pokémon — hit in one pack (ex / Illustration Rare or better)",
     "outcomes": [("Hit", 0.25), ("No hit", 0.75)]},
    {"key": "poke_pack_ir", "game": "pokemon",
     "label": "Pokémon — Illustration Rare in one pack",
     "outcomes": [("IR pulled", 0.13), ("No IR", 0.87)]},
    {"key": "poke_box_sir", "game": "pokemon",
     "label": "Pokémon — Special Illustration Rare in a 36-pack booster box",
     "outcomes": [("SIR in the box", 0.55), ("None", 0.45)]},
    {"key": "ygo_pack_secret", "game": "yugioh",
     "label": "Yu-Gi-Oh! — Secret Rare in one pack (~1 in 12)",
     "outcomes": [("Secret Rare", 0.083), ("None", 0.917)]},
    {"key": "ygo_box_starlight", "game": "yugioh",
     "label": "Yu-Gi-Oh! — Starlight Rare in a 24-pack booster box",
     "outcomes": [("Starlight!", 0.04), ("No Starlight", 0.96)]},
    {"key": "baseball_blaster_hit", "game": "baseball",
     "label": "Baseball — auto or relic in a retail blaster box",
     "outcomes": [("Auto/relic", 0.2), ("Neither", 0.8)]},
]


def offered_odds(probability: float, margin_bps: int) -> float:
    """Decimal odds for an outcome: fair 1/p shaved by the house margin."""
    fair = 1.0 / probability
    return max(1.01, round(fair * (10000 - margin_bps) / 10000, 2))


def presets_with_odds(cfg: dict) -> list:
    margin = int(cfg.get("fixed_odds_margin_bps", 700))
    out = []
    for p in PULL_RATE_PRESETS:
        out.append({
            "key": p["key"], "game": p["game"], "label": p["label"],
            "outcomes": [{"label": label, "probability": prob,
                          "odds": offered_odds(prob, margin)}
                         for label, prob in p["outcomes"]],
        })
    return out
