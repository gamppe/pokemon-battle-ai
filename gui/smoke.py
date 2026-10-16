"""GUI 백엔드 스모크 테스트: python -m gui.smoke"""
import random
import time

from ai.gamedata import GameData, connect
from ai.meta import Meta
from gui.dex import build_dex
from gui.session import Backend, Store

c = connect()
d = GameData(c)
m = Meta(c, d, 33)
b = Backend(d, build_dex(d, c))
print("가치망", b.ev is not None)
rng = random.Random(3)
t0 = [m.build_set(s, rng) for s in m.top_species(6)]
t1 = [m.build_set(s, rng) for s in m.top_species(12)[6:]]
s = Store(b).new([t0, t1], [[0, 1, 2], [0, 1, 2]], ["human", "ai"], ["나", "상대"])
t = time.time()
a = s.analyze(0)
print("분석 %.1fs" % (time.time() - t))
for r in a["actions"]:
    print(r["label"], round(r["win"], 3), round(r["nash"], 2))
for _ in range(6):
    a = s.analyze(0)
    best = max(a["actions"], key=lambda r: r["win"])
    v = s.play_turn([tuple(best["act"]), None], [])
    ch = []
    while v.get("need_choice"):
        nc = v["need_choice"]
        print("선택 필요:", nc["side"], [o["name"] for o in nc["options"]], nc["hint"])
        ch.append(nc["options"][0]["idx"])
        v = s.play_turn([tuple(best["act"]), None], ch)
    print("턴", v["turn"], "승자", v["winner"], v["log"][-3:])
    if v["winner"] is not None:
        break
