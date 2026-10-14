"""교체 포켓몬을 누가 고르는가: 유턴/탈출버튼/레드카드/울부짖기/막말내뱉기/드래곤테일/위기회피 (Showdown 의 requestState 대 우리 엔진의 switch_policy 호출).
사용: python -m verify.switch_choice [--runs 60]
각 사례에서 '턴이 끝난 뒤 교체 포켓몬을 골라야 하는 쪽'의 비율과, 끌려나온 포켓몬이 무작위인지(여러 시드에서 달라지는지) 를 비교한다."""
import argparse
import collections
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from ai.battle import Engine
from ai.gamedata import GameData, connect

SP = {"hp": 32, "atk": 16, "def": 8, "spa": 16, "spd": 8, "spe": 16}


def mon(sid, ability, moves, item="", hp=32, dfn=8):
    return dict(sid=sid, ability=ability, item=item, nature="Serious", sp=dict(SP, hp=hp, **{"def": dfn, "spd": dfn}), moves=moves)


def bench(i):
    return [mon("clefable", "Magic Guard", ["softboiled"]), mon("torkoal", "White Smoke", ["yawn"])][i]


def team(lead):
    return [lead, bench(0), bench(1)]


IDLE = ["swordsdance"]
CASES = {
    "유턴(사용자가 고른다)": (team(mon("scizor", "Technician", ["uturn"])), team(mon("garchomp", "Rough Skin", IDLE)), [("m", 0), ("m", 0)]),
    "탈출버튼(맞은 쪽이 고른다)": (team(mon("garchomp", "Rough Skin", ["dragonclaw"])), team(mon("incineroar", "Blaze", IDLE, "Eject Button")), [("m", 0), ("m", 0)]),
    "레드카드(공격자가 무작위로 끌려감)": (team(mon("garchomp", "Rough Skin", ["dragonclaw"])), team(mon("incineroar", "Blaze", IDLE, "Red Card")), [("m", 0), ("m", 0)]),
    "울부짖기(무작위)": (team(mon("salamence", "Intimidate", ["roar"])), team(mon("garchomp", "Rough Skin", IDLE)), [("m", 0), ("m", 0)]),
    "막말내뱉기(사용자가 고른다)": (team(mon("grimmsnarl", "Prankster", ["partingshot"])), team(mon("garchomp", "Rough Skin", IDLE)), [("m", 0), ("m", 0)]),
    "막말내뱉기 vs 클리어바디": (team(mon("grimmsnarl", "Prankster", ["partingshot"])), team(mon("metagross", "Clear Body", IDLE)), [("m", 0), ("m", 0)]),
    "막말내뱉기 vs 미러아머": (team(mon("grimmsnarl", "Prankster", ["partingshot"])), team(mon("corviknight", "Mirror Armor", IDLE)), [("m", 0), ("m", 0)]),
    "막말내뱉기 vs 매직미러": (team(mon("grimmsnarl", "Prankster", ["partingshot"])), team(mon("hatterene", "Magic Bounce", IDLE)), [("m", 0), ("m", 0)]),
    "드래곤테일(무작위 끌어냄)": (team(mon("dragonite", "Multiscale", ["dragontail"])), team(mon("garchomp", "Rough Skin", IDLE)), [("m", 0), ("m", 0)]),
    "드래곤테일로 기절(쓰러진 쪽이 고른다)": (team(mon("dragonite", "Multiscale", ["dragontail"], "Life Orb")), team(mon("pikachu", "Static", IDLE, hp=0, dfn=0)), [("m", 0), ("m", 0)]),
    "위기회피(발동한 쪽이 고른다)": (team(mon("garchomp", "Rough Skin", ["outrage"], "Life Orb")), team(mon("golisopod", "Emergency Exit", IDLE, hp=0, dfn=0)), [("m", 0), ("m", 0)]),
}


def run_sd(sc, runs):
    fin, fout = os.path.join(HERE, "out", "req_in.json"), os.path.join(HERE, "out", "req_out.json")
    json.dump([dict(id=k, teams=[v[0], v[1]], turns=[v[2]], runs=runs) for k, v in sc.items()], open(fin, "w", encoding="utf-8"))
    subprocess.run(["node", os.path.join(HERE, "sd_req.js"), os.path.join(HERE, "..", "showdown"), fin, fout], check=True)
    return json.load(open(fout, encoding="utf-8"))


def run_ours(eng, v, runs):
    rows = []
    for r in range(runs):
        rng = random.Random(1000 + r)
        st = eng.new_state(v[0], v[1], rng=rng)
        asked = set()

        def pol(s, side):
            asked.add(side)
            return [j for j in s.sides[side].alive_idx() if j != s.sides[side].active][-1]      # 마지막 후보 (기본값과 구분)
        acts = []
        for i in (0, 1):
            a = tuple(v[2][i])
            legal = eng.legal_actions(st, i)
            acts.append(a if a in legal else legal[0])
        eng.step(st, acts, rng, pol)
        rows.append(dict(asked=sorted(asked), act=[s.active for s in st.sides]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=60)
    a = ap.parse_args()
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    eng = Engine(GameData(connect()))
    sd = run_sd(CASES, a.runs)
    for k, v in CASES.items():
        sdr = sd[k]
        n = len(sdr)
        sd_need = [sum(r["need"][i] for r in sdr) / n for i in (0, 1)]
        ours = run_ours(eng, v, a.runs)
        our_need = [sum(i in r["asked"] for r in ours) / n for i in (0, 1)]
        sd_act = collections.Counter(tuple(r["act"]) for r in sdr)
        our_act = collections.Counter(tuple(r["act"]) for r in ours)
        same = all(abs(x - y) < 0.2 for x, y in zip(sd_need, our_need))
        print(f"{'OK ' if same else '불일치'} {k}")
        print(f"    교체 선택 요청 비율 (0쪽,1쪽): Showdown {sd_need[0]:.2f},{sd_need[1]:.2f}  /  우리 {our_need[0]:.2f},{our_need[1]:.2f}")
        print(f"    최종 출전(0쪽,1쪽) Showdown {dict(sd_act)}  /  우리 {dict(our_act)}")


if __name__ == "__main__":
    main()
