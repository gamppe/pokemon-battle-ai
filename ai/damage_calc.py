"""DB 규칙만으로 계산하는 데미지 계산기 (챔피언스 싱글, 레벨 50).
정수 반올림 순서는 Pokémon Showdown의 getDamage/modifyDamage(4096 기준 연쇄 곱)와 같게 구현했다.
지원하지 않는 조건/규칙을 만나면 틀린 값을 내는 대신 result['unsupported']에 기록한다."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .gamedata import GameData, norm

LEVEL = 50
tr = lambda x: int(x)  # 양수 내림 (JS Math.trunc)

# 연쇄 곱에 쓰는 4096 기준 분자. DB에는 소수(1.3 등)로 저장돼 있어 Showdown이 쓰는 고정소수 분자로 바꿔 준다.
FIXED = {1.2: 4915, 1.3: 5325, 1.1: 4505, 1.33: 5448, 1.25: 5120, 1.5: 6144, 2.0: 8192, 0.5: 2048, 0.75: 3072, 0.25: 1024,
         0.8: 3277, 1.6667: 6827}
FIXED_BY_LABEL = {"item:Life Orb": 5324}
INFO_KEYS = {"direct", "max_mult", "max_count", "max_stacks", "ignored_by", "hits", "excluded", "not_infiltrates", "dragon_type_value"}
WEATHER_KEY = {"raindance": "rain", "sunnyday": "sun", "sandstorm": "sand", "snowscape": "snow"}


def modify(value, numerator, denominator=1):
    mod = tr(numerator * 4096 / denominator)
    return tr((tr(value * mod) + 2048 - 1) / 4096)


class Chain:
    """Showdown의 chainModify/finalModify"""

    def __init__(self):
        self.mod = 1.0

    def mul(self, value, label=None, fixed=None):
        nxt = fixed if fixed is not None else FIXED_BY_LABEL.get(label)
        if nxt is None:
            nxt = FIXED.get(round(value, 4)) if isinstance(value, float) else None
        nxt = nxt if nxt is not None else tr(value * 4096)
        prev = tr(self.mod * 4096)
        self.mod = ((prev * nxt + 2048) >> 12) / 4096

    def apply(self, v):
        return modify(v, self.mod)


@dataclass
class Mon:
    sid: str
    ability: str
    item: str
    nature: str
    sp: dict
    boosts: dict
    status: str | None
    hp_frac: float | None
    types: list = field(default_factory=list)
    base: dict = field(default_factory=dict)
    weight_hg: int = 0
    gender: str = "N"
    stats: dict = field(default_factory=dict)
    hangry: bool = False
    grounded_vol: bool = False   # 쓰러뜨리기/뿌리박기로 땅에 붙은 상태
    levitating: bool = False     # 전자부유 중
    maxhp: int = 0
    hp: int = 0
    name: str = ""

    @property
    def frac(self):
        return self.hp / self.maxhp


def make_mon(data: GameData, spec: dict) -> Mon:
    p = data.pokemon[spec["sid"]]
    m = Mon(spec["sid"], spec.get("ability", ""), spec.get("item", ""), spec.get("nature", "Serious"), spec.get("sp", {}),
            spec.get("boosts", {}), spec.get("status"), spec.get("hp_frac"), list(spec.get("types") or p["types"]), p["base"], name=p["name"])
    sp = {k: m.sp.get(k, 0) for k in ("hp", "atk", "def", "spa", "spd", "spe")}
    plus, minus = data.natures.get(norm(m.nature), (None, None))
    m.stats = {}
    for k, key in (("atk", "atk"), ("def", "def_"), ("spa", "spa"), ("spd", "spd"), ("spe", "spe")):
        s = m.base[key] + sp[k] + 20
        if plus == k:
            s = tr(tr(s * 110) % 65536 / 100)
        elif minus == k:
            s = tr(tr(s * 90) % 65536 / 100)
        m.stats[k] = s
    for k, v in (spec.get("stat_over") or {}).items():     # 파워스플릿/가드스플릿/파워트릭/스피드스왑으로 바뀐 수치
        m.stats[k] = v
    w = p["weight_hg"]                                   # 몸무게(0.1kg 단위) + 무거운금속/가벼운금속 특성
    for r in data.ability_fx.get(norm(m.ability), []):
        if r["code"] == "weight_mult":
            w = w * 2 if r["value"] == 2 else tr(w * r["value"])
    m.weight_hg = max(1, w)
    m.gender = spec.get("gender", "N")
    m.hangry = bool(spec.get("hangry"))
    m.grounded_vol, m.levitating = bool(spec.get("grounded_vol")), bool(spec.get("levitating"))
    m.maxhp = m.base["hp"] + sp["hp"] + 75
    m.hp = m.maxhp if m.hp_frac is None else max(1, math.floor(m.maxhp * m.hp_frac))
    return m


@dataclass
class Field:
    weather: str | None = None   # rain / sun / sand / snow
    terrain: str | None = None   # electric / grassy / misty / psychic
    screens: tuple = ()          # 방어 쪽 진영: reflect / light_screen / aurora_veil
    wonder: bool = False         # 원더룸: 방어/특방 수치 교환
    gravity: bool = False        # 중력: 모두 땅에 붙는다


def attacker_weather(c, F):
    """공격 쪽 기술에 적용되는 날씨 (메가솔: 쾌청으로 취급)"""
    for r in c.data.ability_fx.get(norm(c.A.ability), []):
        if r["code"] == "treat_weather_as:sun":
            return "sun"
    return F.weather


@dataclass
class Ctx:
    data: GameData
    A: Mon
    D: Mon
    move: dict
    F: Field
    crit: bool
    se: bool = False
    used: list = field(default_factory=list)
    unsupported: list = field(default_factory=list)
    base_species: dict = field(default_factory=dict)
    hit: int = 1
    proc: bool | None = None
    fail: str | None = None
    flags: frozenset = frozenset()   # 전투 진행 상태(엔진이 알려줌): target_hurt_this_turn 등

    def note_unsupported(self, why):
        if why not in self.unsupported:
            self.unsupported.append(why)


def has_item_flag(c: Ctx, mon: Mon, kind):
    return any(r["kind"] == kind for r in c.data.item_fx.get(norm(mon.item), []))


def grounded(c: Ctx, mon: Mon):
    if mon.item and any(r["code"] == "grounded" for r in c.data.item_fx.get(norm(mon.item), [])):
        return True
    if c.F.gravity or mon.grounded_vol:
        return True
    if mon.levitating:
        return False
    ab_on = ability_active(c, mon)
    balloon = norm(mon.item) == "airballoon" and item_active(c, mon)
    if "Flying" in mon.types or (ab_on and norm(mon.ability) in ("levitate", "eelevate")) or balloon:
        return False
    return True


def cond_ok(c: Ctx, cond: dict, me: Mon, foe: Mon, label: str, cat=None):
    """조건 평가. 지원하지 않는 키가 있으면 False + unsupported 기록"""
    mv = c.move
    for k, v in cond.items():
        if k in INFO_KEYS:
            continue
        if k == "move_type":
            ok = mv["type"] in v.split("|")
        elif k == "move_category":
            ok = (cat or mv["category"]) in v.split("|")
        elif k == "move_flag":
            ok = v in mv["flags"] and not (v == "contact" and norm(c.A.ability) == "longreach")
        elif k == "contact":
            ok = ("contact" in mv["flags"] and norm(c.A.ability) != "longreach") == bool(v)
        elif k == "move":
            ok = mv["name"] in v.split("|")
        elif k == "bp_max":
            ok = mv["bp_now"] <= v
        elif k == "hp_frac_max":
            lim = 1 / 3 if abs(v - 0.3333) < 1e-4 else v
            ok = me.hp <= me.maxhp * lim
        elif k == "hp_full":
            ok = me.hp >= me.maxhp
        elif k == "weather":
            ok = c.F.weather == v
        elif k == "terrain":
            ok = c.F.terrain == v
        elif k == "status_any":
            ok = me.status is not None
        elif k == "is_crit":
            ok = c.crit
        elif k == "not_crit":
            ok = not c.crit
        elif k == "super_effective":
            ok = c.se
        elif k == "converted_move":
            ok = mv.get("converted", False)
        elif k == "has_recoil":
            ok = (mv["recoil"] or 0) > 0 or bool((mv.get("extra") or {}).get("hasCrashDamage"))
        elif k == "has_secondary":
            ok = mv["has_secondary"]
        elif k == "user_grounded":
            ok = grounded(c, c.A)
        elif k == "target_grounded":
            ok = grounded(c, c.D)
        elif k == "target_type":
            ok = v in me.types
        elif k == "species":
            ok = me.name in v.split("|")
        elif k in ("same_gender", "opposite_gender"):
            both = c.A.gender in ("M", "F") and c.D.gender in ("M", "F")
            ok = both and ((c.A.gender == c.D.gender) if k == "same_gender" else (c.A.gender != c.D.gender))
        elif k in ("moves_last", "moves_after_target"):
            ok = "user_moves_after_target" in c.flags
        elif k == "target_switched_in":
            ok = "target_switched_in" in c.flags
        elif k == "flash_fire_active":
            ok = "flash_fire_active" in c.flags
        elif k == "target_side":
            ok = v in ("all", "self_and_ally")
        else:
            c.note_unsupported(f"{label}: 조건 {k}")
            return False
        if not ok:
            return False
    return True


def ability_active(c: Ctx, mon: Mon):
    """몰드브레이커는 상대(방어 쪽)의 breakable 특성을 무시한다"""
    if mon is c.D and norm(c.A.ability) == "moldbreaker" and norm(mon.ability) in c.data.breakable:
        return False
    return True


def item_active(c: Ctx, mon: Mon):
    """서투름(Klutz)이면 도구 효과 없음, 상대가 긴장감(Unnerve)이면 열매 사용 불가"""
    if not mon.item:
        return False
    if has_ability_code(c, mon, "item_disabled"):
        return False
    foe = c.D if mon is c.A else c.A
    if norm(mon.item).endswith("berry") and has_ability_code(c, foe, "foe_cannot_eat_berries"):
        return False
    return True


def fx_rows(c: Ctx, mon: Mon, hook: str):
    rows = (c.data.ability_fx.get(norm(mon.ability), []) if ability_active(c, mon) else []) +            (c.data.item_fx.get(norm(mon.item), []) if item_active(c, mon) else [])
    return [r for r in rows if r["hook"] == hook]


def has_ability_code(c: Ctx, mon: Mon, code: str):
    if not ability_active(c, mon):
        return False
    return any(r["code"] == code for r in c.data.ability_fx.get(norm(mon.ability), []))


def apply_rows(c: Ctx, chain: Chain, rows, me, foe, kinds=("mult",), cat=None):
    for r in rows:
        if r["kind"] == "special":
            if r["code"] == "consecutive_use_boost":        # 메트로놈: 연속 사용 횟수만큼 4096 분수 배율 (4915/5734/6553/7372/8192)
                n = next((int(x.split(":")[1]) for x in c.flags if x.startswith("metronome:")), 0)
                if n:
                    chain.mul(1.0, r["label"], fixed=(4096, 4915, 5734, 6553, 7372, 8192)[min(n, 5)])
                    c.used.append(r["label"])
                continue
            c.note_unsupported(f"{r['label']}: special {r['code']}")
            continue
        if r["kind"] not in kinds:
            continue
        if cond_ok(c, r["cond"], me, foe, r["label"], cat):
            val = r["value"]
            # 수확의풍미(Ripen): 열매 효과 2배 -> 반감 열매는 x0.5 대신 x0.25
            if r["label"].startswith("item:") and norm(me.item).endswith("berry") and val == 0.5 and                     has_ability_code(c, me, "berry_effect_x2"):
                val = 0.25
            chain.mul(val, r["label"])
            c.used.append(r["label"])


_FLING = None


def _fling_powers():
    """Showdown 도구 데이터(etl/cache_sd_items.json)의 던지기 위력 -- DB 표에 없는 도구를 보충한다"""
    global _FLING
    if _FLING is None:
        import json
        import os
        try:
            raw = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "etl", "cache_sd_items.json"), encoding="utf-8"))
            _FLING = {k: v["fling"]["basePower"] for k, v in raw.items() if v.get("fling")}
        except Exception:
            _FLING = {}
    return _FLING


def speed(c: Ctx, mon: Mon):
    """Showdown getStat('spe'): 능력 단계 -> ModifySpe 연쇄(특성/도구) -> 마비(속도 절반, 속보 특성은 무시)"""
    table = [1, 1.5, 2, 2.5, 3, 3.5, 4]
    b = max(-6, min(6, mon.boosts.get("spe", 0)))
    st = math.floor(mon.stats["spe"] * table[b]) if b >= 0 else math.floor(mon.stats["spe"] / table[-b])
    ch = Chain()
    foe = c.D if mon is c.A else c.A
    apply_rows(c, ch, [r for r in fx_rows(c, mon, "modify_spe")], mon, foe)
    st = ch.apply(st)
    if mon.status == "par" and norm(mon.ability) != "quickfeet":
        st = math.floor(st * 50 / 100)
    return st


def item_active_ability_ok(c):
    return True


def type_effectiveness(c: Ctx, move_type: str, defender: Mon):
    """(typeMod, immune)"""
    mod, immune = 0, False
    ign = (c.move.get("extra") or {}).get("ignoreImmunity")
    ghost_ok = has_ability_code(c, c.A, "ghost_immunity") and move_type in ("Normal", "Fighting")   # 배짱: 고스트에도 적중
    ignore_ground = c.F.gravity or c.D.grounded_vol or any(r["code"] == "ground_immunity" for r in c.data.item_fx.get(norm(c.D.item), []))
    forced = {}
    for r in c.move.get("rules", []):
        if r["type"] == "effectiveness_mod" and r["params"].get("vs_type"):
            forced[r["params"]["vs_type"]] = r["params"]["force_multiplier"]
    for t in defender.types:
        m = forced.get(t, c.data.type_chart.get((move_type, t), 1.0))
        if m == 0 and ((t == "Ghost" and ghost_ok) or ign is True or (isinstance(ign, dict) and ign.get(move_type))):
            continue
        if m == 0:
            if move_type == "Ground" and t == "Flying" and ignore_ground:
                continue
            immune = True
        elif m > 1:
            mod += 1
        elif m < 1:
            mod -= 1
    # 특성/도구의 땅 기술 무효 (Levitate/Eelevate/Air Balloon)
    if move_type == "Ground" and not grounded(c, defender) and ("Flying" not in defender.types or defender.levitating):
        immune = True
    return mod, immune


def base_power(c: Ctx):
    mv = c.move
    bp = mv["bp"]
    chain_rules = []
    for r in mv["rules"]:
        t, p = r["type"], r["params"]
        if t in ("use_condition", "sets_state", "target_immunity", "extra_effect", "charge_move", "stat_manipulation", "field_manipulation",
                 "heal_move", "type_change", "protect_move", "doubles_only", "self_cost", "fail_penalty", "trap_move", "copy_move",
                 "switch_move", "item_manipulation", "ability_change", "delayed_move", "on_hit_effect", "boost_by_condition",
                 "priority_by_condition", "accuracy_by_condition", "category_choice"):
            continue    # 위력에 영향 없음(또는 이번 계산 범위 밖)
        if t == "type_by_condition":
            continue    # 타입 변경은 move_type 단계에서 처리
        if t == "effectiveness_mod":
            continue            # type_effectiveness 에서 처리
        if t == "power_mult_if":
            w = p.get("when", {})
            ok = True
            for k, v in w.items():
                if k == "user_item_none":
                    ok &= not c.A.item
                elif k == "target_status":
                    ok &= (c.D.status is not None) if v == "any" else (c.D.status in v.split("|"))
                elif k == "user_status_not_sleep":
                    ok &= c.A.status not in (None, "slp")
                elif k == "terrain":
                    ok &= c.F.terrain == v if v != "any" else c.F.terrain is not None
                elif k == "user_grounded":
                    ok &= grounded(c, c.A)
                elif k == "target_grounded":
                    ok &= grounded(c, c.D)
                elif k == "weather_in":
                    ok &= attacker_weather(c, c.F) in v.split("|")
                elif k == "target_has_removable_item":
                    it = norm(c.D.item)
                    mega = any(x["kind"] == "mega_stone" for x in c.data.item_fx.get(it, []))
                    ok &= bool(it) and not mega
                elif k in ("target_hurt_this_turn", "user_hit_by_target_this_turn", "user_stats_lowered_this_turn",
                           "user_moves_after_target", "last_move_failed") and (c.flags or k in c.flags or True) and "progress" in c.flags:
                    ok &= k in c.flags
                elif k in ("target_hurt_this_turn", "user_hit_by_target_this_turn", "user_stats_lowered_this_turn",
                           "user_moves_after_target", "last_move_failed", "another_round_used_this_turn", "pseudo_weather"):
                    c.note_unsupported(f"{mv['name']}: 전투 진행 상태({k}) 의존")
                    ok = False
                else:
                    c.note_unsupported(f"{mv['name']}: 규칙 조건 {k}")
                    ok = False
            if ok and "chance" in p:
                if c.proc is None:
                    c.note_unsupported(f"{mv['name']}: 확률 위력")
                elif c.proc:
                    chain_rules.append(p["mult"])
                    c.used.append(f"move_rule:{mv['name']}")
            elif ok:
                if p.get("stage") in ("callback", "move"):
                    bp = math.floor(bp * p["mult"])
                else:
                    chain_rules.append(p["mult"])
                c.used.append(f"move_rule:{mv['name']}")
            continue
        if t == "power_formula":
            f = p["formula"]
            if f == "hp_ratio":
                bp = math.floor(max(1, p["base"] * c.A.hp / c.A.maxhp)) if True else bp
            elif f == "hp_tiers48":
                ratio = max(math.floor(c.A.hp * 48 / c.A.maxhp), 1)
                bp = next(v for lim, v in p["tiers"] if ratio < lim + 1) if False else (
                    200 if ratio < 2 else 150 if ratio < 5 else 100 if ratio < 10 else 80 if ratio < 17 else 40 if ratio < 33 else 20)
            elif f == "positive_boost_count":
                bp = p["base"] + p["per"] * sum(v for v in c.A.boosts.values() if v > 0)
            elif f == "target_hp_ratio":
                hp, mx = c.D.hp, c.D.maxhp
                bp = math.floor(math.floor((100 * (100 * math.floor(hp * 4096 / mx)) + 2048 - 1) / 4096) / 100) or 1
            elif f == "constant":
                bp = p["base"]
            elif f == "speed_ratio_table":       # 일렉트릭볼
                tsp = speed(c, c.D)
                ratio = math.floor(speed(c, c.A) / tsp) if tsp else 0
                bp = p["table"][min(ratio, len(p["table"]) - 1)]
            elif f == "gyro_ball":               # 자이로볼
                asp = speed(c, c.A)
                bp = min(p["cap"], math.floor(p["factor"] * speed(c, c.D) / asp) + p["add"]) if asp else 1
            elif f in ("times_attacked", "fainted_allies"):     # 분노의주먹/추도: 엔진이 flags 로 횟수를 알려줌
                n = next((int(x.split(":")[1]) for x in c.flags if x.startswith(f + ":")), 0)
                bp = min(p.get("cap", 10 ** 9), p["base"] + p["per"] * n)
            elif f == "party_atk":               # 따귀때리기: 파티원 한 마리의 기본 공격력
                n = next((int(x.split(":")[1]) for x in c.flags if x.startswith("beatup:")), c.A.base["atk"])
                bp = p["base"] + n // p["div"]
            elif f == "hit_index":               # 트리플악셀: 타수마다 위력 증가
                bp = p["per"] * c.hit
            elif f == "item_fling_power":        # 내던지기: 지닌 도구에 따라 위력
                it = c.A.item
                table = dict(_fling_powers())
                table.update({norm(k): v for k, v in p["table"].items()})
                if not it or not item_active(c, c.A) or norm(it) not in table:
                    c.fail = "fling_fail"
                else:
                    bp = table[norm(it)]
            elif f == "weight_tiers":            # 안다리걸기/풀묶기: 상대 몸무게
                w = c.D.weight_hg
                bp = next((v for thr, v in p["tiers"] if w >= thr), 20)
            elif f == "weight_ratio_tiers":      # 헤비봄버/히트스탬프: 자신 몸무게 / 상대 몸무게 배수
                bp = next((v for mult, v in p["tiers"] if c.A.weight_hg >= c.D.weight_hg * mult), 40)
            else:
                c.note_unsupported(f"{mv['name']}: 위력 공식 {f}")
            c.used.append(f"move_rule:{mv['name']}")
            continue
        c.note_unsupported(f"{mv['name']}: 규칙 {t}")
    return max(1, math.floor(bp)), chain_rules


FORM_ABILITIES = {"forecast", "stancechange", "zerotohero", "hungerswitch", "disguise", "mimicry", "protean", "libero", "trace", "imposter", "illusion",
                  "receiver", "wanderingspirit", "mummy", "skillswap"}


def calc(data: GameData, a_spec: dict, d_spec: dict, move_name: str, field_: Field | None = None, crit: bool = False,
         mega_sol_mode: str = "field_sun", hit: int = 1, proc: bool | None = None,
         flags: frozenset = frozenset()) -> dict:
    """mega_sol_mode (메가솔 해석)
       'field_sun' (기본, 사용자 확인 + Showdown 구현): 공격하는 동안 필드의 날씨를 쾌청으로 취급한다.
                   그래서 방어자의 모래바람 특방 보정/눈 방어 보정, 비의 데미지 보정은 적용되지 않고 쾌청 보정이 적용된다.
       'move_only' : 참고용(틀린 해석). 자신의 기술만 쾌청 취급하고 방어자의 날씨 보정은 그대로 둔다."""
    F = field_ or Field()
    # 확률로 위력이 바뀌는 기술(변덕레이저): proc 를 주지 않으면 두 경우를 모두 계산해 variants 로 돌려준다
    mv0 = data.moves[norm(move_name)]
    chance = next((r["params"]["chance"] for r in mv0["rules"] if r["type"] == "power_mult_if" and "chance" in r["params"]), None)
    if chance is not None and proc is None:
        r0 = calc(data, a_spec, d_spec, move_name, F, crit, mega_sol_mode, hit, proc=False, flags=flags)
        r1 = calc(data, a_spec, d_spec, move_name, F, crit, mega_sol_mode, hit, proc=True, flags=flags)
        r0["variants"] = dict(chance=chance, proc_rolls=r1["rolls"])
        return r0
    A, D = make_mon(data, a_spec), make_mon(data, d_spec)
    # 메가솔: 공격하는 동안 (양쪽 포켓몬 모두에 대한) 날씨 판정이 전부 쾌청. 날씨 무효화 특성보다 우선한다.
    megasol = any(r["code"] == "treat_weather_as:sun" for r in data.ability_fx.get(norm(A.ability), []))
    if megasol and mega_sol_mode == "field_sun":
        F = Field("sun", F.terrain, F.screens)
    # 날씨 무효화(Cloud Nine 등): 필드에 이 특성이 있으면 날씨 효과가 모두 사라진다
    elif any(r["code"] == "negate_weather" for m_ in (A, D) for r in data.ability_fx.get(norm(m_.ability), [])):
        F = Field(None, F.terrain, F.screens)
    pre_unsupported = []
    for mon in (A, D):
        if norm(mon.ability) in FORM_ABILITIES:
            pre_unsupported.append(f"ability:{mon.ability}: 폼/타입/특성 변화")
        if norm(mon.item) in ("normalgem",):
            pre_unsupported.append(f"item:{mon.item}: 사용 시에만 적용되는 소모형")
    m0 = data.moves[norm(move_name)]
    mv = dict(m0, bp_now=m0["bp"], converted=False)
    c = Ctx(data, A, D, mv, F, crit, hit=hit, proc=proc, flags=flags)
    for u in pre_unsupported:
        c.note_unsupported(u)
    if mv["category"] == "status" or (mv["bp"] == 0 and not any(r["type"] == "power_formula" for r in mv["rules"])):
        return dict(rolls=None, reason="no_damage", used=[], unsupported=[])
    # ── 타입 변환 (스킨류 등) ──
    for r in fx_rows(c, A, "modify_move_type"):
        if r["kind"] == "special" and ">" in (r["code"] or ""):
            src, dst = r["code"].split(">")
            if norm(mv["name"]) in {norm(x) for x in r["cond"].get("excluded", "").split("|")}:
                continue
            if src == "Normal" and mv["type"] == "Normal":
                mv["type"], mv["converted"] = dst, True
                c.used.append(r["label"])
            elif src == "sound" and "sound" in mv["flags"]:
                mv["type"], mv["converted"] = dst, True
                c.used.append(r["label"])
        elif r["kind"] == "special":
            c.note_unsupported(f"{r['label']}: {r['code']}")
    for r in mv["rules"]:
        if r["type"] == "type_by_condition":
            p = r["params"]
            if p.get("by") == "weather":
                t = p["table"].get(attacker_weather(c, F))
                if t: mv["type"] = t
            elif p.get("by") == "terrain":
                t = p["table"].get(F.terrain)
                if t and grounded(c, A): mv["type"] = t
            elif p.get("by") == "form":                       # 레이징불: 사용자의 폼에 따라 타입이 정해진다 (오라윌: Morpeko 모양)
                t = next((v for k_, v in p["table"].items() if norm(k_) == norm(A.sid) + ("hangry" if A.hangry else "")), None)
                if t: mv["type"] = t
            else:
                c.note_unsupported(f"{mv['name']}: 타입 규칙 {p.get('by')}")
    # ── 분류 선택 (Shell Side Arm) ──
    for r in mv["rules"]:
        if r["type"] == "category_choice":
            tb = [1, 1.5, 2, 2.5, 3, 3.5, 4]
            def bst(stat, b):
                b = max(-6, min(6, b))
                return math.floor(stat * tb[b]) if b >= 0 else math.floor(stat / tb[-b])
            pa, sa = bst(A.stats["atk"], A.boosts.get("atk", 0)), bst(A.stats["spa"], A.boosts.get("spa", 0))
            pd_, sd_ = bst(D.stats["def"], D.boosts.get("def", 0)), bst(D.stats["spd"], D.boosts.get("spd", 0))
            phys = math.floor(math.floor(math.floor(math.floor(2 * LEVEL / 5 + 2) * 90 * pa) / pd_) / 50)
            spec = math.floor(math.floor(math.floor(math.floor(2 * LEVEL / 5 + 2) * 90 * sa) / sd_) / 50)
            if phys == spec:
                c.note_unsupported(f"{mv['name']}: 물리/특수 계산값이 같아 무작위")
            elif phys > spec:
                mv["category"] = "physical"
                mv["flags"] = set(mv["flags"]) | {"contact"}
    for x_ in flags:                                  # 일렉트리파이: 이 턴 기술이 전기 타입으로
        if x_.startswith("retype:") and norm(mv["name"]) != "struggle":
            mv["type"] = x_.split(":")[1]
    # ── 면역 ──
    mod, immune = type_effectiveness(c, mv["type"], D)
    if immune:
        return dict(rolls=None, reason="immune", used=c.used, unsupported=c.unsupported)
    c.se = mod > 0
    # ── 급소 면역 (단단한껍질/전투무장) ──
    if crit and any(r["code"] == "crit" for r in fx_rows(c, D, "immunity")):
        crit = False
        c.crit = False
    # ── 위력 ──
    bp0, rule_mults = base_power(c)
    if c.fail:
        return dict(rolls=None, reason="fail", used=c.used, unsupported=c.unsupported, mid={})
    mv["bp_now"] = bp0
    ch = Chain()
    # 장판(테라인)/오라 등 필드 규칙 + 공격 측 특성/도구 (Technician처럼 위력 상한 조건이 있는 행을 먼저)
    own = [r for r in fx_rows(c, A, "modify_bp") if r["cond"].get("target_side") != "ally"]
    aura = [r for r in fx_rows(c, D, "modify_bp") if r["cond"].get("target_side") == "all"]
    aura = [r for r in aura if not any(o["label"] == r["label"] for o in own)]      # 같은 오라는 기술당 한 번만 적용 (Showdown auraBooster)
    foe_bp = fx_rows(c, D, "modify_bp_foe")
    tfx = [r for st in ([F.terrain + "_terrain"] if F.terrain else []) for r in data.state_fx.get(st, []) if r["hook"] == "modify_bp"]
    first = [r for r in own if "bp_max" in r["cond"]]
    for r in first:
        mv["bp_now"] = ch.apply(bp0)
        apply_rows(c, ch, [r], A, D)
    for m in rule_mults:
        ch.mul(m)
    if "charged" in c.flags and mv["type"] == "Electric":          # 충전(Charge/전기흡수) 상태: 다음 전기 기술 위력 x2
        ch.mul(2.0)
    if norm(c.A.ability) == "supremeoverlord" and item_active_ability_ok(c):
        n = min(5, next((int(x.split(":")[1]) for x in c.flags if x.startswith("fainted_allies:")), 0))
        if n:
            ch.mul((4096 + 410 * n if n < 2 else [4096, 4506, 4915, 5325, 5734, 6144][n]) / 4096 + 1e-6)
    mv["bp_now"] = ch.apply(bp0)
    apply_rows(c, ch, tfx, A, D)
    apply_rows(c, ch, [r for r in own if "bp_max" not in r["cond"]], A, D)
    apply_rows(c, ch, aura, D, A)
    apply_rows(c, ch, foe_bp, D, A)
    bp = ch.apply(bp0)
    bp = max(1, bp)
    # ── 공격/방어 스탯 ──
    physical = mv["category"] == "physical"
    ex = mv.get("extra") or {}
    ak = ex.get("overrideOffensiveStat") or ("atk" if physical else "spa")
    dk = ex.get("overrideDefensiveStat") or ("def" if physical else "spd")
    off_mon = D if ex.get("overrideOffensivePokemon") == "target" else A
    if F.wonder and ak in ("def", "spd"):                # 바디프레스 등: 원더룸에서는 반대쪽 능력 단계를 쓴다
        ak = "spd" if ak == "def" else "def"

    def stat_of(mon, k):                                 # 원더룸: 방어/특방 수치가 서로 바뀐다 (능력 단계는 이름 그대로)
        if F.wonder and k in ("def", "spd"):
            return mon.stats["spd" if k == "def" else "def"]
        return mon.stats[k]
    ab, db = off_mon.boosts.get(ak, 0), D.boosts.get(dk, 0)
    if has_ability_code(c, D, "foe_stat_stages"):       # 천진(Unaware): 공격 쪽 능력 변화 무시
        ab = 0
    if has_ability_code(c, A, "foe_stat_stages"):       # 공격 쪽이 천진이면 방어 쪽 능력 변화 무시
        db = 0
    if crit:
        ab = max(ab, 0)
        db = min(db, 0)
    if ex.get("ignoreDefensive"):
        db = 0
    if ex.get("ignoreOffensive"):
        ab = 0
    table = [1, 1.5, 2, 2.5, 3, 3.5, 4]
    def boosted(s, b):
        b = max(-6, min(6, b))
        return math.floor(s * table[b]) if b >= 0 else math.floor(s / table[-b])
    atk, dfn = boosted(stat_of(off_mon, ak), ab), boosted(stat_of(D, dk), db)
    # 날씨의 방어 보정(모래바람 바위 특방, 눈 얼음 방어)은 연쇄 곱 이전에 직접 적용
    dcat = "physical" if dk == "def" else "special"
    acat = "physical" if ("atk" if physical else "spa") == "atk" else "special"
    if F.weather in ("sand", "snow"):
        for r in data.state_fx.get(F.weather, []):
            if r["hook"] == "modify_def" and cond_ok(c, r["cond"], D, A, r["label"], dcat):
                dfn = modify(dfn, r["value"]); c.used.append(r["label"])
    cha = Chain()
    arows = fx_rows(c, A, "modify_atk")
    for r in [x for x in arows if x["cond"].get("direct")]:        # 즉시 적용(Hustle)
        if r["kind"] == "mult" and cond_ok(c, r["cond"], A, D, r["label"], acat):
            atk = modify(atk, r["value"]); c.used.append(r["label"])
    apply_rows(c, cha, [x for x in arows if not x["cond"].get("direct")], A, D, cat=acat)
    apply_rows(c, cha, fx_rows(c, D, "modify_atk_foe"), D, A, cat=acat)
    atk = cha.apply(atk)
    chd = Chain()
    apply_rows(c, chd, fx_rows(c, D, "modify_def"), D, A, cat=dcat)
    dfn = chd.apply(dfn)
    base = tr(tr(tr(tr(2 * LEVEL / 5 + 2) * bp * atk) / dfn) / 50)
    # ── modifyDamage ──
    base += 2
    if "pb2" in flags:                               # 부자유친 두 번째 타: modifyDamage 에서 baseDamage x0.25 (날씨·급소·난수 이전)
        base = modify(base, 0.25)
    wthr = attacker_weather(c, F)
    if wthr in ("rain", "sun"):
        wch = Chain()
        apply_rows(c, wch, [r for r in data.state_fx.get(wthr, []) if r["hook"] == "modify_dmg_dealt"], A, D)
        base = wch.apply(base)
    if crit:
        base = tr(base * 1.5)
    rolls = []
    for r in range(16):
        d = tr(tr(base * (100 - r)) / 100)
        stab_on = mv["type"] in A.types
        if stab_on:
            stab = 1.5
            for row in fx_rows(c, A, "modify_stab"):
                stab = row["value"]; c.used.append(row["label"])
            d = modify(d, stab)
        if mod > 0:
            d *= 2 ** mod
        elif mod < 0:
            for _ in range(-mod):
                d = tr(d / 2)
        if A.status == "brn" and physical and norm(A.ability) != "guts" and norm(mv["name"]) != "facade":
            d = modify(d, 0.5)
        fch = Chain()
        apply_rows(c, fch, fx_rows(c, A, "modify_dmg_dealt"), A, D)
        apply_rows(c, fch, fx_rows(c, D, "modify_dmg_taken"), D, A)
        for sc in ([] if has_ability_code(c, A, "substitute_and_screens") else F.screens):   # 침투: 벽 무시
            if sc == "aurora_veil" and (("reflect" in F.screens and mv["category"] == "physical") or ("light_screen" in F.screens and mv["category"] == "special")):
                continue                                              # 오로라베일은 같은 분류의 리플렉터/빛의장막이 있으면 따로 적용되지 않는다
            for row in data.state_fx.get(sc, []):
                if row["hook"] == "modify_dmg_taken" and cond_ok(c, row["cond"], D, A, row["label"]) \
                        and (row["cond"].get("move_category", "").split("|") and mv["category"] in row["cond"]["move_category"].split("|")):
                    fch.mul(row["value"]); c.used.append(row["label"])
        d = fch.apply(d)
        if "target_minimized" in flags and "minimize" in mv["flags"]:      # 작아지기 상태의 상대에게 몸집 기술은 2배
            d = modify(d, 2)
        if d == 0:
            d = 1
        rolls.append(d % 65536)
    seen = []
    for u in c.used:
        if u not in seen:
            seen.append(u)
    return dict(rolls=rolls, reason=None, used=seen, unsupported=c.unsupported, mid=dict(moveType=mv['type'], category=mv['category'], flags=mv['flags'], bp0=bp0, bp=bp, typeMod=mod, atk=atk, dfn=dfn))
