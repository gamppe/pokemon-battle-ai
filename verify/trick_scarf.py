import json, os, subprocess, sys, collections
sys.path.insert(0, ".")
import verify.verify_turns as vt
from ai.gamedata import GameData, connect
from ai.battle import Engine
SP = {"hp": 32, "atk": 16, "def": 8, "spa": 16, "spd": 8, "spe": 16}
def mon(sid, ab, moves, item): return dict(sid=sid, ability=ab, item=item, nature="Serious", sp=SP, moves=moves)
bench = [mon("clefable", "Magic Guard", ["moonblast"], ""), mon("torkoal", "White Smoke", ["yawn"], "")]
cases = {
 "스카프 vs 스카프": ([mon("gholdengo", "Good as Gold", ["trick", "shadowball", "makeitrain", "recover"], "Choice Scarf")] + bench,
                      [mon("garchomp", "Rough Skin", ["earthquake", "dragonclaw", "rocktomb", "swordsdance"], "Choice Scarf")] + bench),
 "스카프 vs 스카프(상대가 먼저 고정)": ([mon("gholdengo", "Good as Gold", ["trick", "shadowball", "makeitrain", "recover"], "Choice Scarf")] + bench,
                      [mon("garchomp", "Rough Skin", ["earthquake", "dragonclaw", "rocktomb", "swordsdance"], "Choice Scarf")] + bench),
}
eng = Engine(GameData(connect()))
for name, teams in cases.items():
    sc = dict(id="t", teams=list(teams), turns=[[["m", 0], ["m", 0]], [["m", 1], ["m", 1]], [["m", 2], ["m", 2]]], runs=200, seed=3)
    json.dump([sc], open("verify/out/t_in.json", "w"))
    subprocess.run(["node", "verify/sd_turns.js", "showdown", "verify/out/t_in.json", "verify/out/t_out.json"], check=True)
    sd = json.load(open("verify/out/t_out.json"))["t"]["results"]
    ours = vt.run_ours(eng, sc, 200, 3)
    bad = vt.compare(ours, sd, 1e-5)
    print(name, "불일치" if bad else "일치")
    for b in (bad or [])[:6]: print("  ", b)
    c1 = collections.Counter((r["mons"][0][0]["it"], r["mons"][1][0]["it"], r["mons"][0][0]["pp"][0]) for r in sd)
    c2 = collections.Counter((r["mons"][0][0]["it"], r["mons"][1][0]["it"], r["mons"][0][0]["pp"][0]) for r in ours)
    print("  SD  (A도구,B도구,A트릭PP):", c1.most_common(3)); print("  우리:", c2.most_common(3))
    print("  PP(A 기술 4개) SD", collections.Counter(tuple(r["mons"][0][0]["pp"]) for r in sd).most_common(2), "우리", collections.Counter(tuple(r["mons"][0][0]["pp"]) for r in ours).most_common(2))
