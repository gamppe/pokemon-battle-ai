"""한 시나리오를 양쪽에서 많이(기본 400회) 돌려 지표별 분포를 나란히 출력 (사용: python verify/dist_turn.py s989 [지표접두어: hp|st|b|it|act|sc])"""
import collections, json, os, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ai.gamedata import GameData, connect
from ai.battle import Engine
sys.argv += [""] * 3
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "out")
sid, prefix = sys.argv[1], sys.argv[2]
RUNS = 400
sc = next(s for s in json.load(open(os.path.join(OUT, "turns_in.json"))) if s["id"] == sid)
sc["runs"] = RUNS
json.dump([sc], open(os.path.join(OUT, "dist_in.json"), "w"))
subprocess.run(["node", os.path.join(HERE, "sd_turns.js"), os.path.join(HERE, "..", "showdown"), os.path.join(OUT, "dist_in.json"), os.path.join(OUT, "dist_out.json")], check=True)
sd = json.load(open(os.path.join(OUT, "dist_out.json")))[sid]["results"]
import importlib.util
spec = importlib.util.spec_from_file_location("vt", os.path.join(HERE, "verify_turns.py"))
src = open(os.path.join(HERE, "verify_turns.py"), encoding="utf-8").read().replace("\nmain()\n", "\n")
ns = {"__file__": os.path.join(HERE, "verify_turns.py"), "__name__": "vt"}
exec(compile(src, "verify_turns.py", "exec"), ns)
eng = Engine(GameData(connect()))
mine = ns["run_ours"](eng, sc, RUNS, 1)
A = [ns["flatten"](x) for x in mine]; B = [ns["flatten"](x) for x in sd]
keys = sorted(set().union(*[d.keys() for d in A + B]))
for k in keys:
    if prefix and not k.startswith(prefix):
        continue
    va = collections.Counter(d.get(k, 0) for d in A); vb = collections.Counter(d.get(k, 0) for d in B)
    if va == vb:
        continue
    print(k, "\n   ours", sorted(va.items(), key=lambda x: -x[1])[:8], "\n   SD  ", sorted(vb.items(), key=lambda x: -x[1])[:8])
