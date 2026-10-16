"""진행 기록 확인용: python -m gui.smoke_log (한국어 문장 출력)"""
import io, random, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from ai.gamedata import GameData, connect
from ai.meta import Meta
from gui.dex import build_dex
from gui.session import Backend, Store

c = connect(); d = GameData(c); m = Meta(c, d, 33)
b = Backend(d, build_dex(d, c))
seed = int(sys.argv[1]) if len(sys.argv) > 1 else 3
rng = random.Random(seed)
sp = m.top_species(30)
rng.shuffle(sp)
t0 = [m.build_set(x, rng) for x in sp[:3]]
t1 = [m.build_set(x, rng) for x in sp[3:6]]
s = Store(b).new([t0, t1], [[0, 1, 2], [0, 1, 2]], ["내 쪽", "상대 쪽"] and ["ai", "ai"] and ["나", "상대"]) if False else None
from gui.session import Session
s = Session(b, [t0, t1], [[0, 1, 2], [0, 1, 2]], ["ai", "ai"], ["나", "상대"])
for _ in range(int(sys.argv[2]) if len(sys.argv) > 2 else 4):
    v = s.play_turn([None, None], [])
    if v["winner"] is not None:
        break
for l in v["log"]:
    print(("%s" % l["text"]) + ("   <%s>" % l["cls"] if l["cls"] and l["cls"] not in ("turn", "hp") else ""))
