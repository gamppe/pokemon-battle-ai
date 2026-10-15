"""turns_mismatch.json 의 각 시나리오에서 처음 어긋나는 턴과 지표를 찾는다. 사용: python verify/dbg_first.py [json 경로]"""
import json, subprocess, sys, os
sys.path.insert(0, ".")
import verify.verify_turns as vt
from ai.gamedata import GameData, connect
from ai.battle import Engine
eng = Engine(GameData(connect()))
path = sys.argv[1] if len(sys.argv) > 1 else "verify/out/turns_mismatch.json"
vt.MIN_TV, vt.MIN_KS = 0.0, 0.0
for x in json.load(open(path, encoding="utf-8")):
    sc = dict(id=x["id"], teams=x["teams"], turns=x["turns"], key="k")
    json.dump([sc], open("verify/out/turns_in_dbg.json", "w"))
    print("==", x["id"], [(y["sid"], y["ability"], y["item"], y["moves"]) for y in x["teams"][0]], "vs", [(y["sid"], y["ability"], y["item"], y["moves"]) for y in x["teams"][1]], sc["turns"])
    for n in range(1, len(sc["turns"]) + 1):
        s = dict(sc, turns=sc["turns"][:n], runs=500, seed=9)
        json.dump([s], open("verify/out/t_in.json", "w"))
        subprocess.run(["node", "verify/sd_turns.js", "showdown", "verify/out/t_in.json", "verify/out/t_out.json"], check=True)
        sd = json.load(open("verify/out/t_out.json", encoding="utf-8"))[sc["id"]]["results"]
        bad = vt.compare(vt.run_ours(eng, s, 500, 9), sd, 1e-3)
        if bad:
            print("  첫 불일치 턴", n, [(b[0], b[2][:3], b[3][:3]) for b in bad[:5]])
            break
    else:
        print("  재현 안 됨(우연)")
