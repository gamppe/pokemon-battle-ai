"""전투 상태 → 신경망 입력 (평가함수/정책망 공용).
한 판을 '포켓몬 토큰 6개(내 3 + 상대 3) + 전역 벡터'로 표현한다. 시점(me)에 따라 내 쪽이 앞에 온다.
토큰은 범주형 id (종, 특성, 도구, 기술 4개) 와 수치형(HP 비율, 실능력치, 상태이상, 능력 단계, 임시 상태 플래그 등)으로 이뤄진다."""
import json
import os

import numpy as np

from .damage_calc import make_mon
from .gamedata import norm

STATUSES = ("par", "brn", "psn", "tox", "slp", "frz")
BOOSTS = ("atk", "def", "spa", "spd", "spe", "accuracy", "evasion")
VOL_FLAGS = ("confusion", "leechseed", "flinch", "focusenergy", "protecting", "roost", "curse", "destinybond", "busted", "protean")
WEATHERS = ("sun", "rain", "sand", "snow")
TERRAINS = ("electric", "grassy", "misty", "psychic")
HAZARDS = ("stealthrock", "spikes", "toxicspikes", "stickyweb")
SIDE_SCREENS = ("reflect", "light_screen", "aurora_veil", "tailwind", "safeguard")
N_CAT = 7          # 종, 특성, 도구, 기술 x4
N_NUM = 6 + len(STATUSES) + len(BOOSTS) + len(VOL_FLAGS) + 8       # hp, alive, active, maxhp, 5 stats ... 아래 참조
N_GLOB = len(WEATHERS) + len(TERRAINS) + 3 + 2 * (len(HAZARDS) + len(SIDE_SCREENS)) + 1


class Vocab:
    """이름 → 정수 id. 0 은 모름/없음"""

    def __init__(self, tables):
        self.t = tables

    @staticmethod
    def build(data, conn):
        cur = conn.cursor()
        cur.execute("select name_en from item")
        items = sorted({norm(r["name_en"]) for r in cur.fetchall()})
        cur.execute("select name_en from ability")
        abil = sorted({norm(r["name_en"]) for r in cur.fetchall()})
        return Vocab({"species": ["<unk>"] + sorted(data.pokemon), "ability": ["<unk>"] + abil, "item": ["<none>"] + items,
                      "move": ["<none>"] + sorted(data.moves)})

    def idx(self, kind, name):
        d = self.__dict__.setdefault("_d", {})
        if kind not in d:
            d[kind] = {n: i for i, n in enumerate(self.t[kind])}
        return d[kind].get(norm(name), 0)

    def size(self, kind):
        return len(self.t[kind])

    def save(self, path):
        json.dump(self.t, open(path, "w", encoding="utf-8"), ensure_ascii=False)

    @staticmethod
    def load(path):
        return Vocab(json.load(open(path, encoding="utf-8")))


_STAT_CACHE = {}


def _stats(eng, bm):
    key = (bm.sid, bm.spec.get("nature"), tuple(sorted(bm.spec.get("sp", {}).items())))
    s = _STAT_CACHE.get(key)
    if s is None:
        m = make_mon(eng.data, dict(eng.spec_of(bm), boosts={}, status=None, hp_frac=None))
        s = m.stats
        _STAT_CACHE[key] = s
    return s


def _mon_token(eng, vocab, st, side, idx, bm, reveal):
    """reveal=False 이면 상대의 특성/도구/기술을 '모름' id 로 가린다 (숨은 정보 상황용)"""
    cat = np.zeros(N_CAT, dtype=np.int64)
    cat[0] = vocab.idx("species", bm.sid)
    if reveal:
        cat[1] = vocab.idx("ability", bm.ability)
        cat[2] = vocab.idx("item", bm.item)
        for k, m in enumerate(bm.spec["moves"][:4]):
            cat[3 + k] = vocab.idx("move", m)
    s = _stats(eng, bm)
    num = [bm.hp / bm.maxhp, float(bm.alive), float(idx == st.sides[side].active), bm.maxhp / 300.0,
           s["atk"] / 200.0, s["def"] / 200.0, s["spa"] / 200.0, s["spd"] / 200.0, s["spe"] / 200.0]
    num += [float(bm.status == x) for x in STATUSES]
    num += [bm.boosts.get(b, 0) / 6.0 for b in BOOSTS]
    num += [float(v in bm.vol) for v in VOL_FLAGS]
    num += [float(bm.sub > 0), float(bm.taunt > 0), float(bm.trap > 0), min(bm.active_turns, 5) / 5.0]
    return cat, np.array(num, dtype=np.float32)


def encode(eng, vocab, st, me, reveal_opp=True):
    """-> cat (6, 7) int64, num (6, N_NUM') float32, glob (G,) float32"""
    cats, nums = [], []
    for side in (me, 1 - me):
        order = [st.sides[side].active] + [i for i in range(len(st.sides[side].team)) if i != st.sides[side].active]
        for i in order:
            bm = st.sides[side].team[i]
            c, n = _mon_token(eng, vocab, st, side, i, bm, reveal_opp or side == me)
            cats.append(c)
            nums.append(n)
    g = [float(st.weather == w) for w in WEATHERS] + [float(st.terrain == t) for t in TERRAINS]
    g += [float(bool(st.trick_room)), min(st.turn, 40) / 40.0, 1.0]
    for side in (me, 1 - me):
        S = st.sides[side]
        g += [S.hazards.get(h, 0) / 3.0 for h in HAZARDS]
        g += [min(S.screens.get(k, 0), 8) / 8.0 for k in SIDE_SCREENS]
    return np.stack(cats), np.stack(nums), np.array(g, dtype=np.float32)


def dims():
    # 토큰 수치 길이는 _mon_token 에서 결정
    return dict(n_cat=N_CAT, n_tok=6)
