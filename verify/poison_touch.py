"""독수(Poison Touch) vs 에써르(Indeedee): 접촉 기술 30% 중독 확률 - Showdown 과 분포 비교"""
import json, subprocess, sys, itertools
sys.path.insert(0, ".")
import verify.verify_turns as vt
from ai.gamedata import GameData, connect
from ai.battle import Engine
SP = {"hp": 32, "atk": 16, "def": 8, "spa": 16, "spd": 8, "spe": 16}
def mon(sid, ab, moves, item=""): return dict(sid=sid, ability=ab, item=item, nature="Serious", sp=SP, moves=moves)
bench = [mon("clefable", "Magic Guard", ["moonblast"]), mon("torkoal", "White Smoke", ["yawn"])]
eng = Engine(GameData(connect()))
bad_all = 0
for ab in ("Psychic Surge", "Inner Focus", "Synchronize"):
    for mv in ("closecombat", "direclaw", "knockoff", "firepunch", "throatchop"):
        for item in ("", "Focus Sash"):
            sc = dict(id="p", teams=[[mon("sneasler", "Poison Touch", [mv, "fakeout", "closecombat", "knockoff"], item)] + bench,
                                     [mon("indeedee", ab, ["psychicterrain", "hypervoice", "protect", "dazzlinggleam"], "")] + bench],
                      turns=[[["m", 0], ["m", 0]], [["m", 0], ["m", 1]]], runs=300, seed=5)
            json.dump([sc], open("verify/out/pt_in.json", "w"))
            subprocess.run(["node", "verify/sd_turns.js", "showdown", "verify/out/pt_in.json", "verify/out/pt_out.json"], check=True)
            sd = json.load(open("verify/out/pt_out.json", encoding="utf-8"))["p"]["results"]
            ours = vt.run_ours(eng, sc, 300, 5)
            bad = vt.compare(ours, sd, 1e-5)
            n_sd = sum(r["mons"][1][0]["st"] in ("psn", "tox") for r in sd)
            n_us = sum(r["mons"][1][0]["st"] in ("psn", "tox") for r in ours)
            print(f"{ab:14s} {mv:10s} {item or '-':10s} 중독 SD {n_sd:3d}/300  우리 {n_us:3d}/300  {'불일치' if bad else '일치'}")
            bad_all += bool(bad)
print("불일치 조합", bad_all)
