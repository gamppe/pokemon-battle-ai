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
TYPES = ["Normal", "Fire", "Water", "Electric", "Grass", "Ice", "Fighting", "Poison", "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost",
         "Dragon", "Dark", "Steel", "Fairy"]
CATS = ("physical", "special", "status")
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


def _move_static(eng, key, cache={}):
    """기술의 정적 특징: 타입 원-핫(18) + 위력/150 + 분류(3) + 우선도/5 + 명중/100 + 반동/흡수/회복 플래그"""
    v = cache.get(key)
    if v is None:
        mv = eng.data.moves.get(norm(key))
        v = np.zeros(18 + 1 + 3 + 1 + 1 + 3, dtype=np.float32)
        if mv:
            if mv["type"] in TYPES:
                v[TYPES.index(mv["type"])] = 1.0
            v[18] = (mv["bp"] or 0) / 150.0
            v[19 + CATS.index(mv["category"])] = 1.0
            v[22] = mv["priority"] / 5.0
            v[23] = (mv["accuracy"] if mv["accuracy"] is not None else 100) / 100.0
            v[24], v[25], v[26] = float(bool(mv["recoil"])), float(bool(mv["drain"])), float(bool(mv["heal"]))
        cache[key] = v
    return v


def _expected_dmg(eng, st, a_side, d_side):
    """a_side 의 활성 포켓몬 기술 4개가 d_side 활성 포켓몬에게 줄 평균 데미지/상대 최대 HP (최대 HP 비율로 자름)"""
    A, D = st.sides[a_side].mon, st.sides[d_side].mon
    out = []
    for m in (A.spec["moves"] + [""] * 4)[:4]:
        key = norm(m)
        mv = eng.data.moves.get(key)
        if not mv or (mv["category"] == "status" and not mv["bp"]):
            out.append(0.0)
            continue
        r = eng.rolls(st, a_side, d_side, key, False)
        out.append(min(sum(r["rolls"]) / len(r["rolls"]), D.hp) / D.maxhp if r["rolls"] else 0.0)
    return out


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
    base = eng.data.pokemon[bm.sid]["base"] if bm.sid in eng.data.pokemon else {}
    ty = np.zeros(18, dtype=np.float32)
    for t in bm.types:
        if t in TYPES:
            ty[TYPES.index(t)] = 1.0
    num += list(ty) + [base.get(k, 0) / 150.0 for k in ("hp", "atk", "def_", "spa", "spd", "spe")]
    mvf = []
    for k in range(4):
        m = bm.spec["moves"][k] if (k < len(bm.spec["moves"]) and reveal) else ""
        mvf += list(_move_static(eng, m)) if m else [0.0] * 27
    num += mvf
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
    # 활성 대면: 서로에게 줄 수 있는 기술별 기대 데미지(최대 HP 비율)와 속도 우열
    opp = 1 - me
    g += _expected_dmg(eng, st, me, opp) + _expected_dmg(eng, st, opp, me)
    sm, so = eng.speed_of(st, me), eng.speed_of(st, opp)
    g += [float(sm > so), float(sm == so), min(sm, 600) / 600.0, min(so, 600) / 600.0]
    return np.stack(cats), np.stack(nums), np.array(g, dtype=np.float32)


def dims():
    # 토큰 수치 길이는 _mon_token 에서 결정
    return dict(n_cat=N_CAT, n_tok=6)
