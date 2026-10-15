"""한 시나리오의 우리 엔진 로그 vs Showdown 로그 (사용: python verify/dbg_turn.py s43 [시드])"""
import json, os, random, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ai.gamedata import GameData, connect, norm
from ai.battle import Engine
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "out")
sid = sys.argv[1]; seed = int(sys.argv[2]) if len(sys.argv) > 2 else 0
sc = next(s for s in json.load(open(os.path.join(OUT, os.environ.get("DBG_IN","turns_in.json")))) if s["id"] == sid)
sc["runs"] = 1
json.dump([sc], open(os.path.join(OUT, "dbg_in.json"), "w"))
env = dict(os.environ, SD_LOG="1")
subprocess.run(["node", os.path.join(HERE, "sd_turns.js"), os.path.join(HERE, "..", "showdown"), os.path.join(OUT, "dbg_in.json"), os.path.join(OUT, "dbg_out.json")], env=env, check=True)
sd = json.load(open(os.path.join(OUT, "dbg_out.json")))[sid]["results"][0]
data = GameData(connect()); eng = Engine(data)
rng = random.Random(seed)
st = eng.new_state(sc["teams"][0], sc["teams"][1], log=True, rng=rng)
for turn in sc["turns"]:
    acts = []
    for i in (0, 1):
        a = tuple(turn[i]); legal = eng.legal_actions(st, i); acts.append(a if a in legal else legal[0])
    eng.step(st, acts, rng, None)
print("── 우리 엔진 ──"); print("\n".join(st.log))
print("\n── Showdown ──"); print(sd["log"].split("|start")[-1])
