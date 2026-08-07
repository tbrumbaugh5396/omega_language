"""Openings state machine through the real API: the video slot must stay
locked until betting is sealed, and sealed videos must not be servable."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["EVERY_REWARD_DATA"] = tempfile.mkdtemp(prefix="er_test_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from backend import config, main  # noqa: E402

client = TestClient(main.app)
cfg = config.load()

# admin via dev login
r = client.post("/api/auth/dev",
                json={"nickname": "opener", "admin_key": cfg["admin_key"]})
assert r.status_code == 200 and r.json()["user"]["is_admin"] == 1
H = {"Authorization": "Bearer " + r.json()["token"]}

# bettor
r = client.post("/api/auth/dev", json={"nickname": "bettor"})
BH = {"Authorization": "Bearer " + r.json()["token"]}
bettor_id = client.get("/api/me", headers=BH).json()["user"]["id"]
client.post("/api/admin/grant", headers=H,
            json={"user_id": bettor_id, "amount": 1000})

# create opening + linked market
oid = client.post("/api/openings", headers=H,
                  json={"title": "test break", "game": "pokemon"}).json()["id"]
m = client.post("/api/markets", headers=H, json={
    "title": "Hit in pack 1?", "mechanism": "parimutuel", "opening_id": oid,
    "outcomes": [{"label": "Hit"}, {"label": "Whiff"}]}).json()
mid, hit_id = m["id"], m["outcomes"][0]["id"]

# bettor stakes while open
r = client.post(f"/api/markets/{mid}/bet", headers=BH,
                json={"outcome_id": hit_id, "stake": 200})
assert r.status_code == 200, r.text

FAKE_VIDEO = ("file", ("reveal.webm", b"\x1aE\xdf\xa3fakewebm", "video/webm"))

# CORE RULE: upload refused while betting is open
r = client.post(f"/api/openings/{oid}/video", headers=H, files=[FAKE_VIDEO])
assert r.status_code == 400 and "seal betting" in r.json()["detail"].lower()
# and no video is servable
assert client.get(f"/api/openings/{oid}/video").status_code == 404

# seal: linked market closes, betting refused
assert client.post(f"/api/openings/{oid}/seal", headers=H).status_code == 200
assert client.get(f"/api/markets/{mid}").json()["status"] == "closed"
r = client.post(f"/api/markets/{mid}/bet", headers=BH,
                json={"outcome_id": hit_id, "stake": 100})
assert r.status_code == 400, "betting must be dead after seal"
# double-seal rejected; late market attach rejected
assert client.post(f"/api/openings/{oid}/seal", headers=H).status_code == 400
r = client.post("/api/markets", headers=H, json={
    "title": "late", "mechanism": "parimutuel", "opening_id": oid,
    "outcomes": [{"label": "a"}, {"label": "b"}]})
assert r.status_code == 400 and "sealed" in r.json()["detail"]

# now the upload works, and only video/* is accepted
r = client.post(f"/api/openings/{oid}/video", headers=H,
                files=[("file", ("x.txt", b"nope", "text/plain"))])
assert r.status_code == 400
r = client.post(f"/api/openings/{oid}/video", headers=H, files=[FAKE_VIDEO])
assert r.status_code == 200, r.text

# revealed: video serves, opening reports it
r = client.get(f"/api/openings/{oid}/video")
assert r.status_code == 200 and r.content.startswith(b"\x1aE\xdf\xa3")
ops = client.get("/api/openings").json()["openings"]
op = next(o for o in ops if o["id"] == oid)
assert op["status"] == "revealed" and op["has_video"]
assert op["markets"][0]["id"] == mid

# resolve from the video, winner paid from the pot
r = client.post(f"/api/markets/{mid}/resolve", headers=H,
                json={"winner_outcome_id": hit_id})
assert r.status_code == 200, r.text
bal = client.get("/api/me", headers=BH).json()["balance"]
assert bal == 1000 - 200 + 196, bal  # sole winner: pot minus 2% rake

# ---- pull-rate presets ----
r = client.get("/api/presets").json()
assert r["margin_bps"] == 700
hit = next(p for p in r["presets"] if p["key"] == "poke_pack_hit")
# p=0.25 -> fair 4.0, shaved 7% -> 3.72
assert hit["outcomes"][0]["odds"] == 3.72, hit
for p in r["presets"]:
    assert abs(sum(o["probability"] for o in p["outcomes"]) - 1.0) < 1e-6, p["key"]
    for o in p["outcomes"]:
        assert o["odds"] > 1.0

# ---- leaderboard: bettor staked 200, won 196 -> net -4, 1/1 wins ----
leaders = client.get("/api/leaderboard").json()["leaders"]
row = next(l for l in leaders if l["nickname"] == "bettor")
assert (row["net"], row["wins"], row["settled"]) == (-4, 1, 1), row

print("test_openings: OK")
