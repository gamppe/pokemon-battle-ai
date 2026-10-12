"""싱글 배틀 턴 엔진 (v1). 데미지는 damage_calc(Showdown과 검증됨)를 그대로 쓴다.
특성/도구의 발동 효과(피격, 등장, 턴 종료, 상태이상 등)는 DB(ability_effect / item_effect)의 hook 행을 읽어서 적용한다.
구현 범위: 우선도/속도 순서, 명중/급소/난수/다단히트, 반동/흡수/회복, 상태이상, 풀죽음, 능력 단계, 날씨/필드, 벽/해저드/순풍,
방어류, 되돌아가기, 교체, 기절 후 교체, 잔여 데미지/회복, 구애류 고정, 변하는 특성 일부(변환자재/스탠스체인지/탈).
미구현(효과 없음으로 처리하고 eng.unsupported 에 센다): 대타출동, 혼란의 세부, 변신/복사, 특성 변경 기술 등.
정확도는 verify/verify_turns.py (Showdown과 분포 대조)로 검증한다."""
import copy
import math
import random
from dataclasses import dataclass, field

from .damage_calc import Field, Ctx, make_mon, speed as calc_speed, calc
from .gamedata import norm

SCREENS = ("reflect", "light_screen", "aurora_veil")
PROTECT_MOVES = {"protect", "detect", "banefulbunker", "spikyshield", "kingsshield", "burningbulwark", "silktrap", "obstruct"}
# 연속 사용 카운터(stall)를 올리는 기술. 퀵가드/와이드가드는 항상 성공하지만 카운터는 올린다
STALL_MOVES = PROTECT_MOVES | {"endure", "quickguard", "wideguard"}
CHOICE = {"choiceband", "choicespecs", "choicescarf"}
WEATHER_ROCK = {"sun": "heatrock", "rain": "damprock", "sand": "smoothrock", "snow": "icyrock"}
CONTACT_PUNISH = {"spikyshield": ("dmg", 1 / 8), "banefulbunker": ("status", "psn"), "burningbulwark": ("status", "brn"),
                  "kingsshield": ("boost", ("atk", -1)), "silktrap": ("boost", ("spe", -1)), "obstruct": ("boost", ("def", -2)),
                  "beakblast": ("status", "brn")}
STATUS_IMMUNE_TYPE = {"par": "Electric", "brn": "Fire", "frz": "Ice"}
NON_FOE_TARGETS = {"self", "allySide", "foeSide", "all", "allyTeam", "allies", "adjacentAlly", "adjacentAllyOrSelf"}
# 변신한 포켓몬에서는 효과가 꺼지는 특성 (Showdown 의 notransform 플래그)
NO_TRANSFORM = {"disguise", "iceface", "gulpmissile", "hungerswitch", "neutralizinggas", "protosynthesis", "quarkdrive", "terashift",
                "zerotohero", "embodyaspectcornerstone", "embodyaspecthearthflame", "embodyaspectteal", "embodyaspectwellspring"}
NO_TRACE = {"trace", "imposter", "illusion", "multitype", "stancechange", "schooling", "comatose", "shieldsdown", "disguise", "rkssystem", "battlebond",
            "powerconstruct", "zenmode", "gulpmissile", "iceface", "neutralizinggas", "asone", "commander", "hungerswitch", "terashift", "zerotohero",
            "flowergift", "forecast", "receiver", "poweroofalchemy", "powerofalchemy", "protosynthesis", "quarkdrive", "wonderguard", "poisonpuppeteer",
            "embodyaspectcornerstone", "embodyaspecthearthflame", "embodyaspectteal", "embodyaspectwellspring"}
NO_SWAP = {"wonderguard", "multitype", "illusion", "stancechange", "schooling", "comatose", "shieldsdown", "disguise", "rkssystem", "battlebond", "powerconstruct", "zenmode", "gulpmissile", "iceface", "neutralizinggas", "asone", "commander", "hungerswitch", "terashift", "zerotohero"}
MULTI_ACCURACY = {"tripleaxel", "triplekick"}
MOLD_BREAKERS = {"moldbreaker", "teravolt", "turboblaze"}


def _frac(v):
    """DB 의 소수 표기(0.1667 등)를 정확한 분수로"""
    for d in (3, 6, 12, 16, 8):
        for n in range(1, d + 1):
            if abs(v - n / d) < 1.5e-3:
                return n / d
    return v


@dataclass
class BMon:
    spec: dict
    maxhp: int
    hp: int
    name: str
    types: list
    sid: str = ""
    status: str | None = None
    tox: int = 0
    sleep: int = 0
    boosts: dict = field(default_factory=dict)
    item: str = ""
    ability: str = ""
    vol: set = field(default_factory=set)
    protect_n: int = 0
    met_last: str = ""                 # 메트로놈 도구: 직전에 쓴 기술 / 연속 사용 횟수
    met_n: int = 0
    hid_item: str = ""                 # 매직룸 동안 숨겨 둔 도구
    frz_n: int = 0                     # 챔피언스 얼음: 행동 시도 3번이 지나면 반드시 풀림
    busted: bool = False               # 변장이 깨진 상태 (교체해도 유지된다)
    ate_berry: bool = False            # 열매를 먹은 적이 있다 (벨치 사용 조건; 교체하면 초기화)
    charged: int = 0                   # 충전 상태 남은 턴 (전기흡수 등으로 맞으면 2, 다음 전기 기술 위력 x2)
    perish: int = 0                    # 멸망의노래 카운트 (4 에서 시작해 턴 끝마다 1 감소, 0 이 되면 쓰러짐)
    db_pending: bool = False           # Destiny Bond 가 걸려 있음 (다른 기술을 쓰려 하거나 기술이 중단되면 해제, 그 전에 또 쓰면 실패)
    disabled: str = ""                 # 봉인된 기술 / 남은 턴
    disable_n: int = 0
    active_turns: int = 0
    moves_made: int = 0
    locked: str | None = None
    abil_orig: str | None = None            # 트레이스/특성교환으로 바뀌기 전의 특성 (교체하면 복원)
    recharge: bool = False
    moved: bool = False
    confusion: int = 0
    leech_to: int = -1
    sub: int = 0
    trap: int = 0
    taunt: int = 0
    stockpile: int = 0
    healblock: int = 0
    yawn: int = 0
    rampage: int = 0
    prev_move: str = ""
    throat: int = 0
    spent: set = field(default_factory=set)         # PP 1 짜리 기술(되살리기)을 이미 쓴 경우
    trap_src: tuple | None = None
    orig: tuple | None = None            # 변신 전 (spec, sid, types, ability)
    encore: int = 0
    encore_move: str = ""              # 앙코르로 고정된 기술 (걸린 시점에 저장한다. 발버둥 등으로 '직전 기술'이 바뀌어도 유지)
    last_move: str = ""
    last_attacker: tuple | None = None
    hurt_turn: int = -1
    lowered_turn: int = -1
    raised_turn: int = -1              # 이번 턴에 능력이 올랐는가 (투명목소리/질투의불꽃 조건)
    last_failed: bool = False
    prev_failed: bool = False
    times_attacked: int = 0
    charge: str | None = None
    semi: list | None = None
    used: set = field(default_factory=set)

    @property
    def alive(self):
        return self.hp > 0

    def frac(self):
        return self.hp / self.maxhp


@dataclass
class Side:
    team: list
    active: int = 0
    hazards: dict = field(default_factory=dict)       # stealthrock / spikes(1~3) / toxicspikes(1~2) / stickyweb
    screens: dict = field(default_factory=dict)       # reflect/light_screen/aurora_veil/tailwind/safeguard -> 남은 턴
    wish: list | None = None                          # [남은 턴, 회복량]
    heal_next: str | None = None                      # healingwish / lunardance
    future: dict | None = None                        # 미래예지 등 지연 공격 {left, src(BMon), key} -- 이 슬롯이 맞는 쪽에 저장

    @property
    def mon(self):
        return self.team[self.active]

    def alive_idx(self):
        return [i for i, m in enumerate(self.team) if m.alive]


@dataclass
class State:
    sides: list
    weather: str | None = None
    weather_turns: int = 0
    terrain: str | None = None
    terrain_turns: int = 0
    trick_room: int = 0
    magic_room: int = 0
    lastmove_any: str = ""             # 전투 전체에서 마지막으로 쓰인 기술 (Copycat)
    turn: int = 0
    winner: int | None = None        # 0 / 1 / -1(무승부)
    last_hit: list = field(default_factory=lambda: [0, 0])
    last_cat: list = field(default_factory=lambda: ["", ""])
    log: list | None = None


class Engine:
    def __init__(self, data):
        self.data = data
        data.moves.setdefault("struggle", dict(
            id=-1, name="Struggle", type="Typeless", category="physical", bp=50, flags={"contact", "protect"}, rules=[], recoil=0,
            has_secondary=False, extra={}, priority=0, accuracy=None, crit_stage=0, always_crit=False, min_hits=1, max_hits=1,
            drain=0, heal=0, self_switch=False, force_switch=False, self_destruct=False, ohko=False, fixed_damage=None,
            target="randomNormal", effects=[]))
        self._landed = False
        self._pending = []
        self._sfail = False
        self._later, self._starts = [], [None, None]      # 이번 턴에 아직 행동할 쪽 (보호 계열의 '마지막이면 실패' 판정용)
        self._rng = random.Random(0)
        self._policy = None
        self._dmg_cache = {}
        self.unsupported = {}

    # ───────────────────────── 상태 만들기 ─────────────────────────
    def new_state(self, team0, team1, log=False, rng=None):
        rng = rng or random.Random(0)
        sides = []
        for team in (team0, team1):
            mons = []
            for spec in team:
                m = make_mon(self.data, dict(spec, boosts={}, status=None, hp_frac=None))
                mons.append(BMon(spec, m.maxhp, m.maxhp, m.name, list(m.types), sid=spec["sid"],
                                 item=spec.get("item", ""), ability=spec.get("ability", "")))
            sides.append(Side(mons))
        st = State(sides, log=[] if log else None)
        for i in sorted((0, 1), key=lambda i: (-self.speed_of(st, i), rng.random())):
            self._switch_in(st, i, rng)
        for s in sides:
            s.mon.active_turns = 1
        return st

    def _say(self, st, msg):
        if st.log is not None:
            st.log.append(msg)

    def _unsup(self, why):
        self.unsupported[why] = self.unsupported.get(why, 0) + 1

    # ───────────────────────── 계산 도우미 ─────────────────────────
    @staticmethod
    def types_of(bm):
        if "roost" in bm.vol and "Flying" in bm.types:
            t = [x for x in bm.types if x != "Flying"]
            return t or ["Normal"]
        return list(bm.types)

    def spec_of(self, bm: BMon):
        s = bm.spec
        return dict(sid=bm.sid, ability=bm.ability, item=bm.item, nature=s.get("nature", "Serious"), sp=s.get("sp", {}),
                    boosts=dict(bm.boosts), status=bm.status, hp_frac=bm.hp / bm.maxhp, gender=s.get("gender", "N"), types=self.types_of(bm))

    def field_for(self, st, defender_side):
        scr = tuple(k for k in SCREENS if st.sides[defender_side].screens.get(k, 0) > 0)
        return Field(st.weather, st.terrain, scr)

    def rolls(self, st, ai_, di_, move_key, crit, hit=1):
        A, D = st.sides[ai_].mon, st.sides[di_].mon
        mv = self.data.moves[move_key]
        dep = any(r["type"] in ("power_formula", "power_mult_if", "damage_formula") for r in mv["rules"])
        sa, sd = self.spec_of(A), self.spec_of(D)
        if not dep:
            for sp_, m_ in ((sa, A), (sd, D)):
                if m_.hp == m_.maxhp:
                    sp_["hp_frac"] = None
                elif m_.hp > m_.maxhp / 2:
                    sp_["hp_frac"] = 0.75
                elif m_.hp > m_.maxhp // 3:
                    sp_["hp_frac"] = 0.45
                else:
                    sp_["hp_frac"] = 0.2
        else:
            sa["hp_frac"], sd["hp_frac"] = round(sa["hp_frac"], 2) or 0.01, round(sd["hp_frac"], 2) or 0.01
        F = self.field_for(st, di_)
        fl = {"progress"}
        if D.hurt_turn == st.turn:
            fl.add("target_hurt_this_turn")
        if A.last_attacker == (st.turn, st.sides[di_].active):
            fl.add("user_hit_by_target_this_turn")
        if A.lowered_turn == st.turn:
            fl.add("user_stats_lowered_this_turn")
        if D.moved:
            fl.add("user_moves_after_target")
        if A.prev_failed:
            fl.add("last_move_failed")
        if norm(A.item) == "metronome":
            fl.add(f"metronome:{min(A.met_n, 5)}")
        if A.charged:
            fl.add("charged")
        if "flashfire" in A.vol:
            fl.add("flash_fire_active")
        fl.add(f"times_attacked:{A.times_attacked}")
        fl.add(f"fainted_allies:{sum(1 for m in st.sides[ai_].team if not m.alive)}")
        fl = frozenset(fl)
        key = (fl, repr(sorted((k, repr(v)) for k, v in sa.items())), repr(sorted((k, repr(v)) for k, v in sd.items())),
               move_key, F.weather, F.terrain, F.screens, crit, hit)
        r = self._dmg_cache.get(key)
        if r is None:
            r = calc(self.data, sa, sd, mv["name"], F, crit, hit=hit, proc=False, flags=fl)
            if len(self._dmg_cache) > 200000:
                self._dmg_cache.clear()
            self._dmg_cache[key] = r
        return r

    def _fainted_speed(self, st, i):
        """쓰러진 포켓몬의 속도: 이벤트(도구/특성/마비/순풍)는 적용되지 않고 능력 단계만 반영된다 (Showdown 은 fainted 의 핸들러를 건너뜀)"""
        bm = st.sides[i].mon
        base = make_mon(self.data, self.spec_of(bm)).stats["spe"]
        b = max(-6, min(6, bm.boosts.get("spe", 0)))
        table = [1, 1.5, 2, 2.5, 3, 3.5, 4]
        return math.floor(base * table[b]) if b >= 0 else math.floor(base / table[-b])

    def speed_of(self, st, i):
        bm = st.sides[i].mon
        m = make_mon(self.data, self.spec_of(bm))
        c = Ctx(self.data, m, m, {}, Field(st.weather, st.terrain), False)
        s = calc_speed(c, m)
        if st.sides[i].screens.get("tailwind", 0) > 0:
            s *= 2
        if norm(bm.ability) == "unburden" and not bm.item and not bm.hid_item and bm.spec.get("item"):
            s *= 2
        return s

    def hp_change(self, st, side, bm, delta, why=""):
        before = bm.hp
        if delta > 0 and bm.healblock:
            return 0
        bm.hp = max(0, min(bm.maxhp, bm.hp + delta))
        if before and not bm.hp:
            bm.status = None
            bm.boosts = {}                                  # 쓰러지면 능력 단계도 초기화된다 (Showdown clearVolatile)
            self._say(st, f"  {bm.name} 쓰러짐 ({why})")
        return bm.hp - before

    # ───────────────────────── DB hook 행 ─────────────────────────
    def rows(self, bm, hook):
        out = []
        ab = norm(bm.ability)
        for r in self.data.ability_fx.get(ab, []):
            if r["hook"] == hook:
                out.append(("ability", r))
        if bm.item and ab != "klutz" and "embargo" not in bm.vol:
            for r in self.data.item_fx.get(norm(bm.item), []):
                if r["hook"] == hook:
                    out.append(("item", r))
        return out

    def _cond_ok(self, cond, st, side, bm, mv=None, hp_before=None):
        if not cond:
            return True
        for k, v in cond.items():
            if k == "contact":
                if not mv or ("contact" in mv["flags"]) != bool(v):
                    return False
            elif k == "move_type":
                if not mv or mv["type"] not in str(v).split("|"):
                    return False
            elif k == "move_category":
                if not mv or mv["category"] not in str(v).split("|"):
                    return False
            elif k == "weather":
                if st.weather != v:
                    return False
            elif k == "terrain":
                if st.terrain != v:
                    return False
            elif k == "status":
                if bm.status not in str(v).split("|"):
                    return False
            elif k == "hp_frac_max":
                if bm.frac() > v:
                    return False
            elif k == "crosses_half_hp":
                if hp_before is None or not (hp_before > bm.maxhp / 2 >= bm.hp):
                    return False
            elif k == "hp_full":
                if (bm.hp == bm.maxhp) != bool(v):
                    return False
            elif k == "self_item_empty":
                if bool(bm.item) == bool(v):
                    return False
            elif k in ("intimidated", "opposite_gender"):
                return False
            elif k in ("species", "max_layers", "ally_type", "up", "down", "excluded", "by_foe", "ally", "target_side", "direct", "bp_max"):
                pass
            else:
                return False
        return True

    def _consume(self, st, bm):
        if norm(bm.item).endswith("berry"):
            bm.ate_berry = True
        bm.item = ""

    @staticmethod
    def _is_consumable(name):
        n = norm(name)
        return n.endswith("berry") or n.endswith("seed") or n in ("airballoon", "redcard", "ejectbutton", "whiteherb", "mentalherb")

    def apply_row(self, st, src, row, side, bm, rng, mv=None, dmg=0, foe_side=None):
        """hook 행 하나를 적용. side/bm 은 효과 소유자, foe_side 는 상대편(attacker/foe 대상)"""
        if row["chance"] is not None and row["chance"] < 100 and rng.random() * 100 >= row["chance"]:
            return False
        o = 1 - side if foe_side is None else foe_side
        foe = st.sides[o].mon
        kind, tgt, code, val = row["kind"], row["target"], row["code"], row["value"]
        tside, tm = (side, bm) if tgt in (None, "self") else (o, foe)
        applied = True
        if kind == "stat_stage":
            if code == "highest_stat":
                m = make_mon(self.data, self.spec_of(bm))
                code = max(("atk", "def", "spa", "spd", "spe"), key=lambda k: m.stats[k])
            if tm.alive:
                self.change_boost(st, tside, tm, code, int(val), src_side=(side if tside != side else None))
        elif kind == "status":
            if tm.alive:
                if code.startswith("random:"):
                    code = rng.choice(code[7:].split("|"))
                self.try_status(st, tside, tm, code, rng, src_side=side, ignore_sub=True)
        elif kind == "damage_frac":
            if tm.alive and norm(tm.ability) != "magicguard":
                d = dmg if code == "equal_to_last_damage" else max(1, math.floor(tm.maxhp * _frac(val) + 1e-9))
                self.hp_change(st, tside, tm, -d, src)
        elif kind == "heal_frac":
            if src.startswith("item:") and tm.healblock and self._is_consumable(bm.item):
                applied = False                    # 회복 열매는 힐블록 중에는 먹지 않는다 (onTryEatItem 이 TryHeal 을 확인)
            elif tm.alive:
                self.hp_change(st, tside, tm, max(1, math.floor(tm.maxhp * _frac(val) + 1e-9)), src)
        elif kind == "heal_fixed":
            if tm.alive:
                self.hp_change(st, tside, tm, int(val), src)
        elif kind == "heal_dmg_frac":
            if tm.alive and dmg:
                self.hp_change(st, tside, tm, max(1, math.floor(dmg * _frac(val))), src)
        elif kind == "set_weather":
            self._set_weather(st, code, bm)
        elif kind == "set_terrain":
            st.terrain = code
            st.terrain_turns = 8 if any(r["code"] == "extend_terrain" for r in self.data.item_fx.get(norm(bm.item), [])) else 5
            self._terrain_seeds(st, rng)
        elif kind == "cure_status":
            if bm.status and (code in ("any", None) or bm.status in code.split("|")):
                bm.status = None
        elif kind == "volatile":
            if code == "flinch" and tm.alive and not tm.moved and norm(tm.ability) != "innerfocus":
                tm.vol.add("flinch")
            elif code != "flinch":
                applied = False
                self._unsup("hook-volatile:" + str(code))
        elif kind == "special":
            if code == "pop_balloon":
                pass
            elif code == "set_toxic_spikes":
                t = st.sides[o]
                t.hazards["toxicspikes"] = min(int(row["cond"].get("max_layers", 2)), t.hazards.get("toxicspikes", 0) + int(val or 1))
            elif code == "reset_negative_stages":
                for k in list(bm.boosts):
                    if bm.boosts[k] < 0:
                        bm.boosts[k] = 0
            elif code == "force_attacker_switch":
                def red(holder=bm):
                    cand = [j for j in st.sides[o].alive_idx() if j != st.sides[o].active]
                    if cand and holder.alive and st.sides[side].mon is holder and st.sides[o].mon.alive and holder.item:   # 보유자가 이미 끌려 나갔으면 발동하지 않음
                        holder.item = ""
                        self._switch_in(st, o, self._rng, to=self._rng.choice(cand))
                self._pending.append(red)
                applied = False
            elif code == "self_switch_out":
                def eject(holder=bm):
                    cand = [j for j in st.sides[side].alive_idx() if j != st.sides[side].active]
                    if cand and holder.alive and st.sides[side].mon is holder and holder.item:
                        holder.item = ""
                        j = self._policy(st, side) if self._policy else cand[0]
                        self._switch_in(st, side, self._rng, to=j if j in cand else cand[0])
                self._pending.append(eject)
                applied = False
            elif code == "copy_foe_ability":                     # 트레이스: 등장할 때 상대 특성을 복사하고 그 특성의 등장 효과도 발동한다
                if foe.alive and foe.ability and norm(foe.ability) not in NO_TRACE:
                    bm.abil_orig = bm.abil_orig or bm.ability
                    bm.ability = foe.ability
                    self._say(st, f"  트레이스 -> {foe.ability}")
                    self._run_switch_in(st, side, bm, rng, only="ability")
                applied = False
            elif code == "transform":
                if foe.alive:
                    self._transform(st, bm, foe)
            elif code in ("aegislash_stance", "illusion", "choice_lock", "grounded", "mega_stone", "first_hit_zero_damage"):
                applied = False
            else:
                applied = False
                self._unsup(f"hook-special:{code}")
        else:
            applied = False
            self._unsup(f"hook:{kind}")
        if applied and src.startswith("item:") and self._is_consumable(bm.item):
            self._consume(st, bm)
        return applied

    def run_hook(self, st, side, bm, hook, rng, mv=None, dmg=0, hp_before=None, foe_side=None, only=None):
        for src, r in self.rows(bm, hook):
            if only and src != only:
                continue
            if not self._cond_ok(r["cond"], st, side, bm, mv, hp_before):
                continue
            if src == "item" and not bm.item:
                continue
            tag = ("item:" if src == "item" else "ability:") + r["label"].split(":", 1)[1]
            self.apply_row(st, tag, r, side, bm, rng, mv, dmg, foe_side)
            if not bm.alive and hook not in ("on_hit_dealt", "turn_end", "on_hit_taken"):
                break

    # ───────────────────────── 능력 단계 / 상태이상 ─────────────────────────
    def change_boost(self, st, side, bm, stat, n, src_side=None):
        """src_side 가 있으면 상대에게서 온 변화 (방어 특성/반격 특성 적용)"""
        ab = norm(bm.ability)
        from_foe = src_side is not None
        broken = from_foe and src_side != side and norm(st.sides[src_side].mon.ability) in MOLD_BREAKERS and ab in self.data.breakable      # 틀깨기는 방어 특성을 무시
        if broken:
            pass
        elif ab == "contrary":
            n = -n
        elif ab == "simple":
            n *= 2
        if n < 0 and from_foe and bm.sub > 0:
            return 0
        if n < 0 and from_foe and not broken:
            for r in self.data.ability_fx.get(ab, []):
                if r["hook"] == "on_stat_drop" and r["kind"] == "immune" and r["code"] in ("all", stat, {"accuracy": "acc"}.get(stat, stat)):
                    return 0
            if ab == "mirrorarmor":
                return self.change_boost(st, src_side, st.sides[src_side].mon, stat, n)
            if st.terrain == "misty" and False:
                return 0
        old = bm.boosts.get(stat, 0)
        new = max(-6, min(6, old + n))
        bm.boosts[stat] = new
        if n > 0 and new != old:
            bm.raised_turn = st.turn
        if n < 0 and new != old:
            bm.lowered_turn = st.turn
            for src, r in self.rows(bm, "on_stat_drop"):
                if r["kind"] == "stat_stage" and r["cond"].get("by_foe") and from_foe:
                    bm.boosts[r["code"]] = min(6, bm.boosts.get(r["code"], 0) + int(r["value"]))
                elif r["kind"] == "special" and r["code"] == "reset_negative_stages" and bm.item:
                    def herb(bm=bm):
                        if bm.item and any(v < 0 for v in bm.boosts.values()):
                            for k in list(bm.boosts):
                                if bm.boosts[k] < 0:
                                    bm.boosts[k] = 0
                            bm.item = ""
                    self._pending.append(herb)
        return new - old

    def try_status(self, st, side, bm, code, rng, src_side=None, ignore_sub=False):
        if bm.status or not bm.alive:
            return False
        if bm.sub > 0 and src_side is not None and src_side != side and not ignore_sub:      # 특성/접촉 반격 상태이상은 대타를 무시
            return False
        ab = norm(bm.ability)
        if "safeguard" in st.sides[side].screens and src_side != side:
            return False
        for r in self.data.ability_fx.get(ab, []):
            if r["hook"] == "immunity" and r["kind"] == "immune" and (r["code"] or "").startswith("status:"):
                s = r["code"].split(":")[1]
                if (s == code or s == "any" or (s == "psn" and code == "tox")) and self._cond_ok(r["cond"], st, side, bm):
                    return False
        if code in ("psn", "tox"):
            corrosion = src_side is not None and src_side != side and norm(st.sides[src_side].mon.ability) == "corrosion"
            if ("Poison" in bm.types or "Steel" in bm.types) and not corrosion:
                return False
        elif STATUS_IMMUNE_TYPE.get(code) in bm.types:
            return False
        if code == "frz" and st.weather == "sun":
            return False
        if code == "slp" and st.terrain == "electric" and self._grounded(bm):
            return False
        if st.terrain == "misty" and self._grounded(bm):
            return False
        if code == "slp":
            bm.sleep = rng.choice((2, 3, 3))         # 챔피언스 모드: 1/3 확률로 2턴째에 깨어남 (쉬는 턴 1~2)
        if code == "frz":
            bm.frz_n = 3
        bm.status = code
        if code == "slp":
            bm.rampage = 0                                  # 잠들면 난동부리기 잠금이 (혼란 없이) 풀린다 (lockedmove onResidual)
        bm.tox = 1 if code == "tox" else 0
        self._say(st, f"  {bm.name} → {code}")
        self._status_item_cure(st, bm, code)
        if bm.status and ab == "synchronize" and src_side is not None and src_side != side and code in ("par", "brn", "psn", "tox"):
            self.try_status(st, src_side, st.sides[src_side].mon, code, rng, src_side=side, ignore_sub=True)
        return True

    def _transform(self, st, bm, tgt):
        if bm.orig or tgt.orig or tgt.sub > 0 or not tgt.alive:
            return False
        bm.orig = (bm.spec, bm.sid, list(bm.types), bm.ability)
        ts = tgt.spec
        bm.spec = dict(ts, moves=list(ts["moves"]), item=bm.item)
        bm.sid, bm.types, bm.ability = tgt.sid, list(tgt.types), "" if norm(tgt.ability) in NO_TRANSFORM else tgt.ability
        bm.boosts = dict(tgt.boosts)
        bm.locked = None
        self._say(st, f"  {bm.name} → {tgt.name} 로 변신")
        return True

    def _confuse(self, st, bm, turns):
        bm.vol.add("confusion")
        bm.confusion = turns
        for src, r in self.rows(bm, "on_status"):
            if r["kind"] == "cure_status" and bm.item and src == "item":
                codes = (r["code"] or "").split("|")
                if "confusion" in codes:
                    bm.vol.discard("confusion")
                    if norm(bm.item).endswith("berry"):
                        bm.ate_berry = True
                    bm.item = ""
                    break

    def _status_item_cure(self, st, bm, code):
        for src, r in self.rows(bm, "on_status"):
            if r["kind"] == "cure_status" and bm.item and src == "item":
                codes = (r["code"] or "").split("|")
                if "any" in codes or code in codes or (code == "tox" and "psn" in codes):
                    bm.status = None
                    self._consume(st, bm)
                    break

    def _grounded(self, bm):
        if norm(bm.item) == "ironball":
            return True
        return "Flying" not in self.types_of(bm) and norm(bm.ability) not in ("levitate", "eelevate") and norm(bm.item) != "airballoon"

    # ───────────────────────── 교체 ─────────────────────────
    def _switch_in(self, st, side, rng, to=None, carry=False, defer=False):
        S = st.sides[side]
        passed = None
        if to is not None:
            old = S.mon
            if carry:
                passed = (dict(old.boosts), old.sub, {v for v in old.vol if v in ("leechseed", "focusenergy", "curse", "confusion")},
                          dict(taunt=old.taunt, healblock=old.healblock, perish=old.perish, confusion=old.confusion))     # Baton Pass 로 넘어가는 상태 (noCopy 가 아닌 것)
            old.boosts, old.vol, old.locked, old.protect_n, old.recharge = {}, set(), None, 0, False
            old.perish = 0
            if old.abil_orig is not None:
                old.ability, old.abil_orig = old.abil_orig, None
            old.charged = 0
            old.ate_berry = False
            old.sub, old.charge, old.semi, old.trap = 0, None, None, 0
            if old.orig:
                old.spec, old.sid, old.types, old.ability = old.orig
                old.orig = None
            for src, r in self.rows(old, "switch_out"):
                if r["kind"] == "heal_frac" and old.alive:
                    old.hp = min(old.maxhp, old.hp + math.floor(old.maxhp * _frac(r["value"]) + 1e-9))
                elif r["kind"] == "cure_status":
                    old.status = None
            if old.status == "tox":
                old.tox = 1
            if old.sid == "aegislashblade":
                old.sid = "aegislash"
            if old.sid in self.data.pokemon:                       # 프로틴/리베로 등으로 바뀐 타입은 교체하면 원래대로 돌아온다
                old.types = list(self.data.pokemon[old.sid]["types"])
            S.active = to
        bm = S.mon
        bm.active_turns, bm.moves_made, bm.moved, bm.used = 0, 0, False, set()
        bm.taunt = bm.stockpile = bm.yawn = bm.encore = bm.healblock = bm.rampage = bm.throat = bm.met_n = bm.disable_n = 0
        bm.encore_move = ""
        bm.met_last = bm.disabled = ""
        bm.db_pending = False
        bm.last_move = ""
        if passed:
            bm.boosts, bm.sub, bm.vol = passed[0], passed[1], set(passed[2])
            for k_, v_ in passed[3].items():
                setattr(bm, k_, v_)
        self._say(st, f"[{side}] {bm.name} 등장")
        if S.heal_next and (bm.hp < bm.maxhp or bm.status):          # 체력이 가득하고 상태이상도 없으면 효과를 남겨 두었다가 다음 교체 대상에게 쓴다
            bm.hp, bm.status = bm.maxhp, None
            S.heal_next = None
        def effects():                                      # 해저드 + 등장 효과 (Showdown 의 runSwitch)
            if not self._item_is(bm, "heavydutyboots"):
                if S.hazards.get("stealthrock"):
                    eff = 1.0
                    for t in bm.types:
                        eff *= self.data.type_chart.get(("Rock", t), 1.0)
                    self.hp_change(st, side, bm, -math.floor(bm.maxhp * eff / 8), "스텔스록")
                if self._grounded(bm) and bm.alive:
                    if S.hazards.get("spikes"):
                        self.hp_change(st, side, bm, -math.floor(bm.maxhp / {1: 8, 2: 6, 3: 4}[S.hazards["spikes"]]), "압정")
                    if S.hazards.get("toxicspikes"):
                        if "Poison" in bm.types:
                            S.hazards.pop("toxicspikes")
                        else:
                            self.try_status(st, side, bm, "tox" if S.hazards["toxicspikes"] >= 2 else "psn", rng)
                    if S.hazards.get("stickyweb"):
                        self.change_boost(st, side, bm, "spe", -1, src_side=1 - side)
            if not bm.alive:
                return
            self._run_switch_in(st, side, bm, rng)
        if defer:                                           # 동시에 교체되면 등장 효과는 모두 나온 뒤 현재 속도 순으로 처리된다
            return effects
        effects()

    def _flush_pending(self):
        pend, self._pending = self._pending, []
        for fn in pend:
            fn()

    def _run_switch_in(self, st, side, bm, rng, only=None):
        foe = st.sides[1 - side].mon
        for src, r in self.rows(bm, "switch_in"):
            if only and src != only:
                continue
            if not self._cond_ok(r["cond"], st, side, bm):
                continue
            if src == "item" and not bm.item:
                continue
            if r["kind"] == "info" or (r["kind"] == "heal_frac" and r["target"] == "ally"):
                continue
            if r["kind"] == "stat_stage" and r["target"] == "foe":
                if not foe.alive or "substitute" in foe.vol:
                    continue
                if r["label"].endswith("Intimidate"):
                    if any(r2["hook"] == "immunity" and r2["code"] == "ability:intimidate" for r2 in self.data.ability_fx.get(norm(foe.ability), [])):
                        continue
                self.change_boost(st, 1 - side, foe, r["code"], int(r["value"]), src_side=side)
                if r["label"].endswith("Intimidate") and foe.alive:
                    for src2, r2 in self.rows(foe, "immunity") + self.rows(foe, "on_hit_taken"):
                        if r2["cond"].get("intimidated") and r2["kind"] == "stat_stage":
                            self.change_boost(st, 1 - side, foe, r2["code"], int(r2["value"]))
                continue
            self.apply_row(st, ("item:" if src == "item" else "ability:") + r["label"].split(":", 1)[1], r, side, bm, rng)
        self._flush_pending()
        if bm.alive and norm(bm.item) == "whiteherb" and any(v < 0 for v in bm.boosts.values()):      # 배턴터치로 받은 능력 하락 등 (onStart)
            for k in list(bm.boosts):
                if bm.boosts[k] < 0:
                    bm.boosts[k] = 0
            bm.item = ""
        if bm.alive and bm.item:                                  # 등장하자마자 HP 조건을 만족하면 열매를 먹는다 (시트러스 등, Update 이벤트)
            self.run_hook(st, side, bm, "on_damage_taken_hp", rng, only="item")

    def _terrain_seeds(self, st, rng):
        for i in (0, 1):
            bm = st.sides[i].mon
            if bm.alive and bm.item:
                for src, r in self.rows(bm, "switch_in"):
                    if src == "item" and bm.item and r["kind"] == "stat_stage" and self._cond_ok(r["cond"], st, i, bm):
                        self.apply_row(st, "item:" + r["label"].split(":", 1)[1], r, i, bm, rng)

    @staticmethod
    def _item_is(bm, name):
        return norm(bm.item) == name

    def _set_weather(self, st, w, bm):
        st.weather = w
        rock = WEATHER_ROCK.get(w)
        st.weather_turns = 8 if rock and norm(bm.item) == rock else 5

    # ───────────────────────── 선택지 ─────────────────────────
    def legal_actions(self, st, side):
        S = st.sides[side]
        bm = S.mon
        if bm.recharge:
            return [("r", 0)]
        moves = bm.spec["moves"]
        acts = []
        no_revive = {k for k, m in enumerate(moves) if norm(m) in bm.spent}
        no_sound = {k for k, m in enumerate(moves) if bm.throat and "sound" in self.data.moves[norm(m)]["flags"]}
        if bm.moves_made >= 1:           # 등장 직후 한 번만 쓸 수 있는 기술(猫だまし 등)은 선택 불가
            first_only = {k for k, m in enumerate(moves) if any(
                r["type"] == "use_condition" and r["params"].get("requires") == "first_turn_after_switch_in"
                for r in self.data.moves[norm(m)]["rules"])}
        else:
            first_only = set()
        first_only |= no_revive | no_sound
        if bm.charge:
            return [("m", next(k for k, m in enumerate(moves) if norm(m) == bm.charge))]       # 두 턴 기술의 충전 중에는 교체 불가 (Showdown 에서 확인)
        if bm.rampage and bm.last_move:
            ks = [k for k, m in enumerate(moves) if norm(m) == bm.last_move]
            if ks:
                return [("m", ks[0])]
        if bm.encore and bm.encore_move:
            ks = [k for k, m in enumerate(moves) if norm(m) == bm.encore_move]
            if ks:
                k0 = ks[0]
                unusable = k0 in first_only or norm(moves[k0]) == bm.disabled or (bm.taunt and self.data.moves[norm(moves[k0])]["category"] == "status")
                acts = [("t", 0)] if unusable else [("m", k0)]        # 앙코르로 고정된 기술을 쓸 수 없으면 발버둥
                if self._can_switch(st, side):
                    acts += [("s", j) for j in S.alive_idx() if j != S.active]
                return acts
        if bm.locked and bm.locked in moves and norm(bm.item) in CHOICE:
            ks = [moves.index(bm.locked)]
        else:
            ks = list(range(len(moves)))
        if bm.healblock:                                    # 힐블록: 회복 기술은 고를 수 없다
            ks = [k for k in ks if "heal" not in self.data.moves[norm(moves[k])]["flags"]]
        if bm.taunt:
            ok = [k for k in ks if self.data.moves[norm(moves[k])]["category"] != "status" and k not in first_only and norm(moves[k]) != bm.disabled]
            acts = [("m", k) for k in ok] or [("t", 0)]               # 도발로 쓸 수 있는 기술이 없으면 발버둥
            if self._can_switch(st, side):
                acts += [("s", j) for j in S.alive_idx() if j != S.active]
            return acts
        ks = [k for k in ks if norm(moves[k]) != bm.disabled]
        acts += [("m", k) for k in ks if k not in first_only] or [("t", 0)]
        if self._can_switch(st, side):
            acts += [("s", j) for j in S.alive_idx() if j != S.active]
        return acts

    def _switch_acts(self, st, side):
        S = st.sides[side]
        return [("s", j) for j in S.alive_idx() if j != S.active] if self._can_switch(st, side) else []

    def _can_switch(self, st, side):
        """교체 가능 여부: 도구 '벗어난껍질'과 고스트 타입은 속박/그림자밟기에 잡히지 않는다 (Showdown: trapped 면역)"""
        bm = st.sides[side].mon
        if norm(bm.item) == "shedshell" or "Ghost" in self.types_of(bm):
            return True
        if bm.trap:
            return False
        return norm(st.sides[1 - side].mon.ability) != "shadowtag" or norm(bm.ability) == "shadowtag"

    # ───────────────────────── 턴 진행 ─────────────────────────
    def step(self, st, acts, rng, switch_policy=None):
        """한 턴 진행. acts = [행동0, 행동1], 행동 = ('m', 기술번호) | ('s', 교체번호) | ('r', 0)"""
        if st.winner is not None:
            return st
        self._rng, self._policy, self._acts = rng, switch_policy, acts
        st.turn += 1
        st.last_hit = [0, 0]
        st.last_cat = ["", ""]
        for i in (0, 1):
            m = st.sides[i].mon
            m.vol.discard("flinch")
            m.vol.discard("protecting")
            m.vol.discard("enduring")
            m.vol.discard("quickguard")
            m.vol.discard("wideguard")
            for k in list(m.vol):
                if k in CONTACT_PUNISH:
                    m.vol.discard(k)
            m.moved = False
        self._say(st, f"== 턴 {st.turn} ==")
        sw = [i for i in (0, 1) if acts[i][0] == "s"]
        for i in sorted(sw, key=lambda i: ((1 if st.trick_room else -1) * self.speed_of(st, i), rng.random())):
            self._switch_in(st, i, rng, to=acts[i][1])
        movers = []
        for i in (0, 1):
            if acts[i][0] in ("m", "r", "t"):
                bm = st.sides[i].mon
                mv = self.data.moves[norm(bm.spec["moves"][acts[i][1]])] if acts[i][0] == "m" else (
                    self.data.moves["struggle"] if acts[i][0] == "t" else None)
                if mv and mv["name"].lower().replace(" ", "") == "beakblast":
                    bm.vol.add("beakblast")      # 행동 전 대기 중 접촉 공격을 받으면 공격자를 화상 (턴 시작 시 설정)
                pr_ = self._priority(st, i, mv) if mv else 0
                if mv and norm(bm.item) == "quickclaw" and pr_ <= 0 and rng.random() < 0.2:      # 선제공격손톱: 20% 확률로 같은 우선도 안에서 먼저 움직인다
                    pr_ += 0.1
                movers.append((i, pr_, self.speed_of(st, i), rng.random()))
        movers.sort(key=lambda x: (-x[1], (x[2] if st.trick_room else -x[2]), x[3]))
        starts = [st.sides[0].active, st.sides[1].active]
        for n, (i, pr, spd, _) in enumerate(movers):
            if st.sides[i].active != starts[i]:
                continue
            if st.winner is not None:
                break
            if not st.sides[i].mon.alive or acts[i][0] == "s":
                continue
            self._later, self._starts = [m_[0] for m_ in movers[n + 1:]], starts
            self._do_action(st, i, acts[i], acts, rng, switch_policy)
            pend, self._pending = self._pending, []
            for fn in pend:
                fn()
            self._check_winner(st)
        if st.winner is None:
            self._end_of_turn(st, rng)
            self._check_winner(st)
        for _ in range(6):      # 교체해 들어오자마자 해저드로 쓰러지면 바로 다음 포켓몬을 낸다
            self._check_winner(st)
            dead = [i for i in (0, 1) if st.winner is None and not st.sides[i].mon.alive and st.sides[i].alive_idx()]
            if not dead:
                break
            if len(dead) == 2:      # 동시에 쓰러졌으면 쓰러진 포켓몬의 속도가 빠른 쪽이 먼저 나온다 (나중에 나온 쪽의 날씨/필드 특성이 이김)
                dead.sort(key=lambda i: ((1 if st.trick_room else -1) * self._fainted_speed(st, i), rng.random()))
            if len(dead) == 2:
                effs = [self._replace(st, i, rng, switch_policy, defer=True) for i in dead]
                order = sorted(zip(dead, effs), key=lambda x: ((1 if st.trick_room else -1) * self.speed_of(st, x[0]), rng.random()))
                for _, fn in order:
                    if fn:
                        fn()
                continue
            for i in dead:
                self._replace(st, i, rng, switch_policy)
        for i in (0, 1):
            st.sides[i].mon.active_turns += 1
        self._check_winner(st)
        return st

    def _replace(self, st, i, rng, switch_policy, defer=False):
        alive = st.sides[i].alive_idx()
        if not alive:
            return
        j = switch_policy(st, i) if switch_policy else alive[0]
        if j not in alive:
            j = alive[0]
        return self._switch_in(st, i, rng, to=j, defer=defer)

    def _check_winner(self, st):
        dead = [not st.sides[i].alive_idx() for i in (0, 1)]
        if dead[0] and dead[1]:
            st.winner = -1
        elif dead[0]:
            st.winner = 1
        elif dead[1]:
            st.winner = 0

    def _priority(self, st, i, mv):
        bm = st.sides[i].mon
        p = mv["priority"]
        ab = norm(bm.ability)
        if ab == "prankster" and mv["category"] == "status":
            p += 1
        if ab == "galewings" and mv["type"] == "Flying" and bm.hp == bm.maxhp:
            p += 1
        if norm(mv["name"]) == "grassyglide" and st.terrain == "grassy" and self._grounded(bm):
            p += 1
        return p

    # ───────────────────────── 행동 수행 ─────────────────────────
    def _confusion_damage(self, bm, rng):
        """혼란 자해: 위력 40 의 무속성 물리 공식 (공격/방어 스탯과 단계만 반영, 난수 85~100%) -- Showdown getConfusionDamage"""
        m = make_mon(self.data, self.spec_of(bm))

        def stage(v, b):
            return v * (2 + b) // 2 if b >= 0 else v * 2 // (2 - b)
        atk, dfn = stage(m.stats["atk"], bm.boosts.get("atk", 0)), stage(m.stats["def"], bm.boosts.get("def", 0))
        base = 22 * 40 * atk // dfn // 50 + 2
        return max(1, base * (100 - rng.randrange(16)) // 100)

    def _can_act(self, st, i, bm, rng):
        if bm.status == "slp":
            bm.sleep -= 1
            if bm.sleep <= 0:
                bm.status = None
                self._say(st, f"  {bm.name} 일어남")
            else:
                return False
        if bm.status == "frz":                       # 챔피언스: 시도마다 카운트 -1, 0 이 되거나 25% 확률로 해동
            bm.frz_n -= 1
            if bm.frz_n <= 0 or rng.random() < 0.25:
                bm.status = None
            else:
                return False
        if "flinch" in bm.vol:
            for src, r in self.rows(bm, "on_flinch"):
                if r["kind"] == "stat_stage":
                    self.change_boost(st, i, bm, r["code"], int(r["value"]))
            return False
        if "confusion" in bm.vol:
            bm.confusion -= 1
            if bm.confusion <= 0:
                bm.vol.discard("confusion")
            elif rng.random() < 0.33:                       # Showdown: randomChance(33, 100)
                self.hp_change(st, i, bm, -min(bm.hp, self._confusion_damage(bm, rng)), "혼란")
                return False
        if bm.status == "par" and rng.random() < 0.125:       # 챔피언스: 행동 불가 1/8
            return False
        return True

    def _do_action(self, st, i, act, acts, rng, switch_policy):
        S = st.sides[i]
        bm = S.mon
        if act[0] == "r" or bm.recharge:
            bm.recharge = False
            return
        mname = "struggle" if act[0] == "t" else bm.spec["moves"][act[1]]
        if bm.rampage and bm.last_move:
            mname = next((m for m in bm.spec["moves"] if norm(m) == bm.last_move), mname)
        if bm.encore and bm.encore_move and act[0] != "t" and norm(mname) != bm.encore_move:
            mname = next((m for m in bm.spec["moves"] if norm(m) == bm.encore_move), mname)
        mv = self.data.moves[norm(mname)]
        self._say(st, f"[{i}] {bm.name}: {mv['name']}")
        if bm.disabled and norm(mname) == bm.disabled:         # 봉인: 이미 고른 기술도 쓰지 못하고 턴을 잃는다
            self._say(st, "  봉인으로 사용 불가")
            self._rampage_abort(st, bm, rng)
            return
        bm.moves_made += 1
        bm.vol.discard("beakblast")                         # 기술이 나가는 순간 대기 상태가 끝난다
        bm.vol.discard("glaiverush")
        bm.vol.discard("destinybond")
        if norm(mname) != "destinybond":
            bm.db_pending = False
        bm.prev_failed, bm.last_failed = bm.last_failed, True            # 성공 지점에서 False 로 바꾼다 (자폭/심술/고집 등 '직전 기술 실패' 조건용)
        if not self._can_act(st, i, bm, rng):
            bm.db_pending = False                           # 기술이 중단되면 Destiny Bond 도 풀린다 (onMoveAborted)
            if mv["type"] == "Electric":
                bm.charged = 0                              # 충전도 전기 기술이 중단되면 해제된다 (onMoveAborted)
            if norm(bm.item) not in CHOICE:
                bm.locked = None
            bm.charge, bm.semi = None, None
            self._rampage_abort(st, bm, rng)
            return
        if norm(mname) == "focuspunch" and bm.hurt_turn == st.turn:      # 행동 전에 공격을 받으면 집중이 흐트러져 기술을 쓰지 못한다 (BeforeMove 중단)
            self._say(st, "  집중이 흐트러졌다")
            bm.db_pending = False
            if norm(bm.item) not in CHOICE:
                bm.locked = None
            return
        if bm.throat and "sound" in mv["flags"]:
            self._say(st, "  지옥찌르기로 소리 기술 사용 불가")
            return
        if bm.taunt and mv["category"] == "status":
            self._say(st, "  도발로 사용 불가")
            return
        if bm.healblock and "heal" in mv["flags"]:
            self._say(st, "  힐블록으로 사용 불가")
            return
        # 스탠스체인지: 기술을 실제로 쓰게 된 뒤에 바뀐다 (풀죽음/수면 등으로 움직이지 못하면 폼 그대로). 공격하면 블레이드폼, 킹실드는 실드폼
        if norm(bm.ability) == "stancechange" and bm.sid in ("aegislash", "aegislashblade") and not bm.orig:
            if norm(mv["name"]) == "kingsshield":
                bm.sid = "aegislash"
            elif mv["category"] != "status":
                bm.sid = "aegislashblade"
        if norm(bm.item) in CHOICE and norm(mname) != "struggle":      # 발버둥은 고정 기술을 바꾸지 않는다 (쓸 수 없는 기술에 고정되면 계속 발버둥)
            bm.locked = mname
        if norm(bm.item) != "metronome":
            bm.met_n, bm.met_last = 0, ""
        elif "callsMove" not in mv["flags"]:                 # Showdown 메트로놈 도구의 onTryMove: 같은 기술을 직전에 성공했으면 연속 횟수 +1
            if bm.met_last == norm(mv["name"]) and not bm.prev_failed:
                bm.met_n += 1
            else:
                bm.met_n = 0
            bm.met_last = norm(mv["name"])
        bm.moved = True
        bm.prev_move = bm.last_move
        bm.last_move = norm(mname)             # 앙코르도 마지막 기술로 기록된다 (그 직후의 앙코르는 대상의 마지막 기술이 앙코르라서 실패)
        if norm(mname) == "revivalblessing":
            if norm(bm.item) == "leppaberry":                      # PP 1 이 0 이 되면 Leppa 열매가 PP 를 회복한다 (이후 다시 쓸 수 있음)
                bm.item = ""
            else:
                bm.spent.add("revivalblessing")
        chg = next((r["params"] for r in mv["rules"] if r["type"] == "charge_move"), None)
        if chg is not None:
            if bm.charge == norm(mname):                      # 두 번째 턴: 공격
                bm.charge, bm.semi = None, None
            elif str(chg.get("skip_if", "")) == "weather:" + str(
                    "sun" if any(r["code"] == "treat_weather_as:sun" for r in self.data.ability_fx.get(norm(bm.ability), [])) else st.weather):
                for k, v in (chg.get("charge_boost") or {}).items():       # 날씨 조건으로 즉시 발동(능력 상승은 그대로)
                    self.change_boost(st, i, bm, k, int(v))
            else:                                             # 첫 턴: 충전
                bm.charge = norm(mname)
                for k, v in (chg.get("charge_boost") or {}).items():
                    self.change_boost(st, i, bm, k, int(v))
                if chg.get("evasion_max") in ("flying", "underground", "underwater", "shadow"):
                    bm.semi = [norm(x) for x in chg.get("hit_by_moves", [])]
                self._say(st, "  충전")
                return
        self._run_move(st, i, mv, mname, acts, rng, switch_policy)
        if mv["type"] == "Electric" and bm.charged:                 # 전기 기술을 쓰고 나면 충전 해제 (onAfterMove)
            bm.charged = 0
        st.lastmove_any = norm(mname)                       # Copycat 용: 전투 전체에서 마지막으로 쓰인 기술
        for S_ in st.sides:                                 # 구애 아이템을 잃으면(트릭 등) 기술 고정도 풀린다 (choicelock 볼라타일은 아이템이 바뀌면 사라짐)
            if S_.mon.locked and norm(S_.mon.item) not in CHOICE:
                S_.mon.locked = None

    def _run_move(self, st, i, mv, mname, acts, rng, switch_policy):
        """기술 실행 단계 (사용 조건 확인 이후). Copycat 처럼 다른 기술을 불러 쓰는 기술도 이 함수를 다시 호출한다"""
        S = st.sides[i]
        bm = S.mon
        bm.used.add(norm(mname))
        if norm(mv["name"]) not in STALL_MOVES:
            bm.protect_n = 0
        if not self._use_condition_ok(st, i, mv, acts):
            return
        if norm(mv["name"]) in ("futuresight", "doomdesire"):   # 지연 공격: 쓴 턴에는 피해가 없고, 2턴 뒤 턴 종료 때 상대 슬롯을 때린다 (이미 걸려 있으면 실패)
            if st.sides[1 - i].future is None:
                st.sides[1 - i].future = dict(left=3, src=bm, key=norm(mv["name"]))
                self._say(st, "  미래공격 예약")
                bm.last_failed = False
            else:
                self._say(st, "  실패")
            return
        counter_fail = norm(mv["name"]) in ("counter", "mirrorcoat", "metalburst") and not st.last_hit[i]
        if norm(bm.ability) in ("protean", "libero") and "protean" not in bm.vol and not counter_fail and bm.types != [mv["type"]] \
                and (mv["target"] in NON_FOE_TARGETS or st.sides[1 - i].mon.alive):      # 대상이 없으면 변환기 계열 특성은 발동하지 않는다
            bm.vol.add("protean")
            bm.types = [mv["type"]]
        o = 1 - i
        target_is_self = mv["target"] in NON_FOE_TARGETS or (norm(mv["name"]) == "curse" and "Ghost" not in bm.types)
        D = st.sides[o].mon
        foe_target = not target_is_self
        if foe_target and not D.alive:
            self._say(st, "  대상 없음")
            self._self_destruct_fail(st, i, mv)
            self._rampage_abort(st, bm, rng)
            return
        if foe_target and D.semi is not None and norm(bm.ability) != "noguard" and norm(D.ability) != "noguard" and norm(mv["name"]) not in D.semi:
            self._say(st, "  빗나감(반무적 상태)")
            return
        if foe_target and st.terrain == "psychic" and self._grounded(D) and self._priority(st, i, mv) > 0:
            self._say(st, "  사이코필드가 선공기를 막음")
            return
        if foe_target and self._ability_blocks(st, i, o, mv, rng):
            return
        if foe_target and "protect" in mv["flags"] and (
                ("quickguard" in D.vol and self._priority(st, i, mv) > 0) or
                ("wideguard" in D.vol and mv["target"] in ("allAdjacent", "allAdjacentFoes"))):
            self._say(st, "  막혔다")
            bm.last_failed = False                  # 막힌 기술은 실패가 아니다 (NOT_FAIL) -> Temper Flare 등의 '직전 기술 실패' 조건이 아님
            self._self_destruct_fail(st, i, mv)
            return
        if "protecting" in D.vol and "protect" in mv["flags"] and foe_target and not (
                mv["category"] == "status" and any(k in D.vol for k in ("kingsshield", "silktrap", "obstruct"))):
            self._say(st, "  막혔다")
            bm.last_failed = False
            self._self_destruct_fail(st, i, mv)
            self._contact_punish(st, i, o, mv, rng)
            self._rampage_abort(st, bm, rng)
            for r in mv["rules"]:
                if r["type"] == "self_cost" and r["params"].get("hp_frac") and mv["category"] != "status" and bm.alive:
                    self.hp_change(st, i, bm, -math.floor(bm.maxhp * r["params"]["hp_frac"] + 0.5), mv["name"])
                elif r["type"] == "fail_penalty" and r["params"].get("hp_frac") and bm.alive:
                    self.hp_change(st, i, bm, -math.floor(bm.maxhp * r["params"]["hp_frac"]), "크래시")
            return
        if foe_target and not self._chart_immune(mv, D) and any(r["type"] == "extra_effect" and r["params"].get("effect") == "shatter_screens" for r in mv["rules"]):
            for k in ("reflect", "light_screen", "aurora_veil"):         # onTryHit: 명중/면역/대타보다 먼저 상대 진영의 벽을 부순다
                if st.sides[o].screens.pop(k, None):
                    self._say(st, f"  {k} 파괴")
        if mv["category"] == "status" and mv["bp"] == 0:
            self._status_move(st, i, mv, rng)
            bm.last_failed = self._sfail
            return
        imm_first = (mv["category"] != "status" and foe_target and not mv["ohko"] and not mv["fixed_damage"]
                     and self.rolls(st, i, o, norm(mv["name"]), False)["reason"] == "immune")      # 타입 면역은 명중 판정보다 먼저 (빗나감/반동이 아니라 효과 없음)
        if not imm_first and norm(mv["name"]) not in MULTI_ACCURACY and not self._hits(st, i, o, mv, rng, target_is_self):
            self._say(st, "  빗나감")
            self._rampage_abort(st, bm, rng)
            self._self_destruct_fail(st, i, mv)
            if mv["name"].lower() in ("jump kick", "high jump kick"):
                self.hp_change(st, i, bm, -bm.maxhp // 2, "크래시")
            for r in mv["rules"]:
                if r["type"] == "self_cost" and r["params"].get("hp_frac") and mv["category"] != "status" and bm.alive:
                    self.hp_change(st, i, bm, -math.floor(bm.maxhp * r["params"]["hp_frac"] + 0.5), mv["name"])
            return
        self._damage_move(st, i, o, mv, rng, switch_policy)
        if self._landed:
            bm.last_failed = False
        if any(e["code"] == "lockedmove" for e in mv["effects"]) and bm.rampage > 1 and not self._landed:
            bm.rampage = 0                      # 잠긴 채로 쓴 기술이 실패하면(면역 등) 잠금만 풀린다. 혼란은 남은 지속이 1 이하일 때만
        elif any(e["code"] == "lockedmove" for e in mv["effects"]) and (bm.rampage or self._landed):
            if not bm.rampage:
                bm.rampage = rng.choice([2, 3])         # 이 턴 포함 남은 횟수 (이미 시작된 뒤에는 무효여도 계속)
            bm.rampage -= 1
            if bm.rampage == 0 and bm.alive and norm(bm.ability) != "owntempo" and "confusion" not in bm.vol:
                self._confuse(st, bm, rng.randint(2, 5))
        elif bm.rampage:
            bm.rampage = 0

    def _rampage_abort(self, st, bm, rng):
        """난동부리기류가 막히거나 빗나갔을 때: 잠금 지속이 이번 턴으로 끝나는 경우(남은 1)에는 혼란, 아니면 잠금만 풀린다"""
        if bm.rampage == 1 and bm.alive and norm(bm.ability) != "owntempo" and "confusion" not in bm.vol:
            self._confuse(st, bm, rng.randint(2, 5))
        bm.rampage = 0

    def _chart_immune(self, mv, D):
        t = mv["type"]
        if any(self.data.type_chart.get((t, x), 1.0) == 0 for x in self.types_of(D)):
            return not (t == "Ground" and any(r["code"] == "ground_immunity" for r in self.data.item_fx.get(norm(D.item), [])))
        return t == "Ground" and not self._grounded(D)

    def _ability_blocks(self, st, i, o, mv, rng):
        """상대 특성이 기술을 무효화/흡수하는 경우 (DB immunity 행). True 면 기술은 더 진행하지 않는다"""
        A, D = st.sides[i].mon, st.sides[o].mon
        if norm(A.ability) in MOLD_BREAKERS and norm(D.ability) in self.data.breakable:
            return False
        if mv["category"] != "status":
            r_ = self.rolls(st, i, o, norm(mv["name"]), False)
            if r_.get("mid", {}).get("moveType"):
                mv = dict(mv, type=r_["mid"]["moveType"])
        for r in self.data.ability_fx.get(norm(D.ability), []):
            if r["hook"] != "immunity":
                continue
            code = r["code"] or ""
            if r["kind"] == "absorb" and code == mv["type"]:
                if r["value"]:
                    self.hp_change(st, o, D, max(1, math.floor(D.maxhp * _frac(r["value"]))), "흡수")
                else:
                    D.vol.add("flashfire")
                self._say(st, f"  {D.name} 흡수")
                return True
            if r["kind"] == "immune" and code == "type:" + mv["type"] and mv["type"] != "Ground":
                for r2 in self.data.ability_fx.get(norm(D.ability), []):
                    if r2["hook"] == "on_hit_taken" and r2["kind"] == "stat_stage" and mv["type"] in str(r2["cond"].get("move_type", "")).split("|"):
                        self.change_boost(st, o, D, r2["code"], int(r2["value"]))
                return True
            if r["kind"] == "immune" and code == "priority_moves" and self._priority(st, i, mv) > 0:
                return True
            if r["kind"] == "immune" and code == "move_class:status" and mv["category"] == "status":
                return True
        return False

    def _use_condition_ok(self, st, i, mv, acts):
        bm = st.sides[i].mon
        for r in mv["rules"]:
            if r["type"] != "use_condition":
                continue
            p = r["params"]
            req = p.get("requires", "")
            if req == "first_turn_after_switch_in" and bm.moves_made != 1:
                return False
            if req == "target_has_item" and not st.sides[1 - i].mon.item:
                return False
            if req == "user_ate_berry" and not bm.ate_berry:
                return False
            if req == "user_asleep" and bm.status != "slp":
                return False
            if req == "weather:snow" and st.weather != "snow":
                return False
            if req == "terrain_active" and not st.terrain:
                return False
            if req.startswith("user_has_type:") and req.split(":")[1] not in bm.types:
                return False
            if req in ("target_will_use_priority_attacking_move", "target_will_use_attacking_move") and \
                    st.sides[1 - i].active != self._starts[1 - i]:
                return False                      # 이번 턴 도중에 교체해 들어온 포켓몬은 행동이 없다 (Sucker Punch 실패)
            if req == "target_will_use_priority_attacking_move":
                o = 1 - i
                a = acts[o]
                if a[0] != "m" or st.sides[o].mon.moved:
                    return False
                m2 = self.data.moves[norm(st.sides[o].mon.spec["moves"][a[1]])]
                if m2["category"] == "status" or self._priority(st, o, m2) <= 0:
                    return False
            if req == "target_will_use_attacking_move":
                o = 1 - i
                a = acts[o]
                if a[0] != "m" or st.sides[o].mon.moved or self.data.moves[norm(st.sides[o].mon.spec["moves"][a[1]])]["category"] == "status":
                    return False
            for tok in p.get("fails_if", "").split("|"):
                if tok == "user_full_hp" and bm.hp == bm.maxhp:
                    return False
                if tok == "user_asleep" and bm.status == "slp":
                    return False
                if tok.startswith("target_has_type:") and tok.split(":")[1] in st.sides[1 - i].mon.types:
                    return False
                if tok.startswith("user_hp_frac<=") and bm.frac() <= float(tok.split("<=")[1]):
                    return False
        return True

    def _hits(self, st, i, o, mv, rng, target_is_self):
        A, D = st.sides[i].mon, st.sides[o].mon
        acc = mv["accuracy"]
        if acc is None or target_is_self:
            return True
        aab, dab = norm(A.ability), norm(D.ability)
        if aab in ("nolimit", "noguard") or dab == "noguard" or "glaiverush" in D.vol:
            return True
        if norm(mv["name"]) == "toxic" and "Poison" in A.types:        # 독 타입이 쓰는 맹독은 반드시 명중한다
            return True
        if mv["ohko"]:
            return rng.random() < 0.3
        a = acc
        if aab == "compoundeyes":
            a = a * 1.3
        if norm(A.item) == "widelens":
            a = a * 1.1
        if norm(D.item) == "brightpowder":
            a = a * 0.9
        if (st.weather == "sand" and dab == "sandveil") or (st.weather == "snow" and dab == "snowcloak"):
            a = a * 0.8
        if aab == "hustle" and mv["category"] == "physical":
            a = a * 0.8
        if mv["name"].lower() in ("thunder", "hurricane") and st.weather == "rain":
            return True
        if mv["name"].lower() == "blizzard" and st.weather == "snow":
            return True
        stage = max(-6, min(6, A.boosts.get("accuracy", 0) - (0 if dab == "unaware" else D.boosts.get("evasion", 0))))
        ratio = (3 + stage) / 3 if stage >= 0 else 3 / (3 - stage)
        return rng.random() * 100 < math.floor(a * ratio)

    def _crit(self, mv, A, D, rng):
        if norm(D.ability) in ("battlearmor", "shellarmor"):
            return False
        if mv["always_crit"]:
            return True
        stage = mv["crit_stage"] + (1 if norm(A.item) in ("scopelens", "razorclaw") else 0) + (2 if "focusenergy" in A.vol else 0)
        if norm(A.ability) == "superluck":
            stage += 1
        return rng.random() < [1 / 24, 1 / 8, 1 / 2, 1, 1][min(stage, 4)]

    def _damage_move(self, st, i, o, mv, rng, switch_policy):
        A, D = st.sides[i].mon, st.sides[o].mon
        key = norm(mv["name"])
        hit_rule = next((r["params"].get("hits") for r in mv["rules"] if r["type"] == "power_formula" and r["params"].get("formula") == "hit_index"), None)
        nhits = hit_rule if hit_rule else mv["max_hits"] if mv["min_hits"] == mv["max_hits"] else (
            rng.choices([2, 3, 4, 5], [35, 35, 15, 15])[0] if (mv["min_hits"], mv["max_hits"]) == (2, 5) else rng.randint(mv["min_hits"], mv["max_hits"]))
        if norm(A.ability) == "skilllink" and mv["max_hits"] == 5:
            nhits = 5
        total, landed = 0, 0
        self._raised_pre = D.raised_turn == st.turn        # 부가효과 판정은 이 기술의 피격 반응(스태미나 등) 이전의 능력 상승만 본다
        eff_mv = mv
        berry_used = False
        self._landed = False
        late_item = False
        hit_sub = False
        deferred = None
        for h in range(1, nhits + 1):
            if not D.alive or not A.alive:
                break
            if key in MULTI_ACCURACY and norm(A.ability) != "skilllink" and not self._hits(st, i, o, mv, rng, False):
                if h == 1:
                    self._say(st, "  빗나감")
                break
            if mv["fixed_damage"] or key in ("seismictoss", "nightshade"):
                if self._chart_immune(mv, D):
                    self._say(st, "  효과 없음")
                    return
                dmg, crit = mv["fixed_damage"] or 50, False
            elif mv["ohko"]:
                imm = self.rolls(st, i, o, key, False)
                if imm["reason"] == "immune" or self._chart_immune(mv, D):
                    self._say(st, "  효과 없음")
                    return
                dmg, crit = D.hp, False
            elif key in ("counter", "mirrorcoat", "metalburst", "comeuppance"):
                last, cat = st.last_hit[i], st.last_cat[i]
                need = {"counter": "physical", "mirrorcoat": "special"}.get(key)
                if not last or (need and cat != need) or self._chart_immune(mv, D):
                    return
                dmg, crit = max(1, math.floor(last * (2.0 if key in ("counter", "mirrorcoat") else 1.5))), False
            elif key == "finalgambit":
                if self._chart_immune(mv, D):
                    self._say(st, "  효과 없음")
                    return
                dmg, crit = A.hp, False
            elif key == "superfang":
                if self._chart_immune(mv, D):
                    return
                dmg, crit = max(1, D.hp // 2), False
            elif key == "endeavor":
                if self._chart_immune(mv, D) or A.hp >= D.hp:
                    return
                dmg, crit = D.hp - A.hp, False
            else:
                crit = self._crit(mv, A, D, rng)
                r = self.rolls(st, i, o, key, crit, hit=h)
                if r["rolls"] is None:
                    if r["reason"] in ("immune", "fail"):
                        for rr in mv["rules"]:
                            if rr["type"] == "fail_penalty" and rr["params"].get("hp_frac"):
                                self.hp_change(st, i, A, -math.floor(A.maxhp * rr["params"]["hp_frac"]), "크래시")
                    if r["reason"] == "immune":
                        self._say(st, "  효과 없음")
                    elif r["reason"] == "fail":
                        self._say(st, "  실패")
                    self._self_destruct_fail(st, i, mv)
                    return
                dmg = rng.choice(r["rolls"])
                if r.get("mid", {}).get("moveType"):
                    eff_mv = dict(mv, type=r["mid"]["moveType"])
                if D.item and norm(D.item).endswith("berry") and "item:" + D.item in r.get("used", []):
                    berry_used = True
                if "glaiverush" in D.vol:
                    dmg *= 2
            hp_before = D.hp
            if D.sub > 0 and "bypasssub" not in mv["flags"] and norm(A.ability) != "infiltrator":
                d = min(dmg, D.sub)
                D.sub -= d
                if norm(D.item) == "airballoon":            # 대타가 깨지지 않아도 기술로 피해를 주면 풍선이 터진다 (onAfterSubDamage)
                    D.item = ""
                total += d
                landed += 1
                hit_sub = True
                self._say(st, f"  대타 -{d}")
                if mv["drain"] and A.alive and d:
                    self.hp_change(st, i, A, max(1, math.floor(d * _frac(mv["drain"] / 100) + 0.5)), "흡수")
                continue
            if not D.busted and norm(D.ability) == "disguise" and D.sid == "mimikyu" and norm(A.ability) not in MOLD_BREAKERS:      # 탈 (첫 피격 무효, 최대 HP의 1/8 손해)
                D.busted = True
                self.hp_change(st, o, D, -max(1, D.maxhp // 8), "탈")
                self._say(st, "  탈 벗겨짐")
                landed += 1
                late_item = True
                continue
            if "gem" in self._gem_flag(A, mv):
                A.item = ""
            if "enduring" in D.vol and dmg >= D.hp:
                dmg = D.hp - 1
            if (D.hp == D.maxhp and dmg >= D.hp) and (norm(D.item) == "focussash" or norm(D.ability) == "sturdy"):
                dmg = D.hp - 1
                if norm(D.item) == "focussash" and norm(D.ability) != "sturdy":
                    self._consume(st, D)
            if norm(D.item) == "focusband" and dmg >= D.hp and rng.random() < 0.1:       # 기합의머리띠: 10% 확률로 HP 1 로 버틴다 (소모되지 않음)
                dmg = D.hp - 1
            dmg = min(dmg, D.hp)
            self.hp_change(st, o, D, -dmg, mv["name"])
            st.last_hit[o] = dmg
            st.last_cat[o] = mv["category"]
            D.hurt_turn = st.turn
            D.last_attacker = (st.turn, st.sides[i].active)
            D.times_attacked += 1
            total += dmg
            landed += 1
            self._say(st, f"  {D.name} -{dmg} ({D.hp}/{D.maxhp})")
            if mv["drain"] and A.alive and dmg:
                heal = max(1, math.floor(dmg * _frac(mv["drain"] / 100) + 0.5))
                if norm(D.ability) == "liquidooze":
                    self.hp_change(st, i, A, -heal, "해감액")
                else:
                    if norm(A.item) == "bigroot":
                        heal = math.floor(heal * 1.3)
                    self.hp_change(st, i, A, heal, "흡수")
            if key == "knockoff" and D.item and any(r["hook"] == "on_damage_taken_hp" for r in self.data.item_fx.get(norm(D.item), []))                     and norm(D.ability) != "stickyhold":
                D.item = ""
            if berry_used and D.item:
                D.item = ""
                berry_used = False
            if key in ("bugbite", "pluck") and A.alive and D.item and norm(D.item).endswith("berry") \
                    and norm(D.ability) != "stickyhold":                # 벌레먹기/쪼기: 상대의 열매를 빼앗아 바로 먹고 효과를 얻는다
                berry, own = D.item, A.item
                D.item, A.item = "", berry
                for hook_ in ("on_damage_taken_hp", "on_status"):         # 먹은 즉시 열매의 효과가 나온다 (HP 조건은 보지 않는다)
                    for src_, r_ in self.rows(A, hook_):
                        if src_ == "item" and A.item == berry:
                            self.apply_row(st, "item:" + r_["label"].split(":", 1)[1], r_, i, A, rng)
                A.ate_berry = True
                A.item = own
            deferred = (eff_mv, dmg, hp_before) if nhits == 1 else None
            self._on_hit(st, i, o, eff_mv, rng, dmg, hp_before, crit, defer=nhits == 1)
        if not landed:
            return
        self._landed = True
        if late_item and D.alive:
            for src, r in self.rows(D, "on_hit_taken"):
                if src == "item" and D.item and self._cond_ok(r["cond"], st, o, D, mv):
                    self.apply_row(st, "item:" + r["label"].split(":", 1)[1], r, o, D, rng, mv, 0, i)
        self._primary_self_effects(st, i, mv, rng)
        if mv["recoil"] and A.alive and total and norm(A.ability) not in ("rockhead", "magicguard"):
            self.hp_change(st, i, A, -max(1, math.floor(total * _frac(mv["recoil"] / 100) + 0.5)), "반동")
        if A.alive and landed:
            self.run_hook(st, i, A, "on_hit_dealt", rng, mv=mv, dmg=total, foe_side=o, only="ability")
        self._secondary(st, i, o, mv, rng, hit_sub)      # 대타는 상대에게 걸리는 부가효과만 막고, 자신에게 걸리는 효과(불꽃의charge 등)는 그대로 적용
        if deferred and D.alive and st.sides[o].mon is D:                  # 열매 등 HP 조건 효과: 부가효과(힐블록 등)가 끝난 뒤에 판단
            self.run_hook(st, o, D, "on_damage_taken_hp", rng, mv=deferred[0], dmg=deferred[1], hp_before=deferred[2], foe_side=i)
        if not hit_sub:
            if key == "knockoff" and D.item and norm(D.ability) != "stickyhold" and not (
                    any(r["kind"] == "mega_stone" for r in self.data.item_fx.get(norm(D.item), [])) and "mega" in D.sid):
                D.item = ""
        if D.alive:
            if not hit_sub:
                for e in mv["effects"]:
                    if e["trigger_type"] == "primary" and e["applies_to"] == "target" and e["kind"] == "volatile":
                        self._apply_effect(st, i, o, e, rng)
                if key == "clearsmog":
                    D.boosts = {}
        else:
            self._on_faint(st, i, o, mv, rng, total)
            if "destinybond" in D.vol and A.alive:
                self.hp_change(st, i, A, -A.hp, "길동무")
        if mv["self_destruct"] and A.alive:
            self.hp_change(st, i, A, -A.hp, "자폭")
        if "recharge" in mv["flags"]:
            A.recharge = True
        for r in mv["rules"]:
            if r["type"] == "self_cost" and r["params"].get("hp_frac") and mv["category"] != "status" and A.alive and total:
                self.hp_change(st, i, A, -math.floor(A.maxhp * r["params"]["hp_frac"] + 0.5), mv["name"])
            elif r["params"].get("effect") == "clear_terrain" and landed and st.terrain:       # 스틸롤러/아이스스피너: 맞히면 필드를 없앤다 (대타 포함)
                st.terrain, st.terrain_turns = None, 0
            elif r["type"] == "field_manipulation" and r["params"].get("effect") == "set_hazard":      # 대타를 때려도 깐다 (onAfterSubDamage)
                self._side_condition(st, o, {"stealth_rock": "stealthrock"}.get(r["params"]["hazard"], r["params"]["hazard"]), swap=True)
        if mv["force_switch"] and not mv["self_switch"] and D.alive and not hit_sub and D.sub == 0 and norm(D.ability) != "suctioncups":
            cand = [j for j in st.sides[o].alive_idx() if j != st.sides[o].active]        # 드래곤테일 등: 끌어내기가 레드카드/탈출버튼보다 먼저
            if cand:
                self._switch_in(st, o, rng, to=rng.choice(cand))
        pend, self._pending = self._pending, []
        for fn in pend:
            fn()
        if key == "struggle" and A.alive:
            self.hp_change(st, i, A, -max(1, math.floor(A.maxhp / 4 + 0.5)), "발버둥")        # Showdown: Math.round(maxhp / 4)
        if A.alive and landed and st.sides[i].mon is A:
            self.run_hook(st, i, A, "on_damage_taken_hp", rng)
        if A.alive and landed and st.sides[i].mon is A:           # 생명의구슬/조개껍질방울은 낙오카드 등이 끝난 뒤
            self.run_hook(st, i, A, "on_hit_dealt", rng, mv=mv, dmg=total, foe_side=o, only="item")
        if key in ("doubleshock", "burnup") and A.alive:
            lost = "Electric" if key == "doubleshock" else "Fire"
            if lost in A.types:
                A.types = [t for t in A.types if t != lost] or ["Typeless"]
        if key in ("rapidspin", "mortalspin", "tidyup") and A.alive:
            st.sides[i].hazards.clear()
            A.vol.discard("leechseed")
            A.trap = 0
            A.vol.discard("bind"); A.vol.discard("bindband")
        if mv["self_switch"] and A.alive and st.winner is None and st.sides[i].mon is A:
            cand = [j for j in st.sides[i].alive_idx() if j != st.sides[i].active]
            if cand:
                j = switch_policy(st, i) if switch_policy else cand[0]
                if j not in cand:
                    j = cand[0]
                self._switch_in(st, i, rng, to=j)

    @staticmethod
    def _gem_flag(A, mv):
        if A.item and norm(A.item).endswith("gem") and mv["category"] != "status" and mv["type"] == A.item[:-4].strip():
            return {"gem"}
        return set()

    def _on_hit(self, st, i, o, mv, rng, dmg, hp_before, crit, defer=False):
        """피격 후 처리: 방어자의 on_hit_taken / on_damage_taken_hp / (급소) on_crit_taken.
        defer=True 면 HP 조건 효과(열매 등)는 부가효과 뒤로 미룬다 (Showdown 은 열매를 Update 에서 먹는다)"""
        D = st.sides[o].mon
        if norm(D.item) == "airballoon":
            D.item = ""
        if norm(D.ability) in ("electromorphosis", "windpower"):      # 맞으면 충전 상태 (onDamagingHit -> addVolatile('charge'))
            D.charged = 2
        if "beakblast" in D.vol and "contact" in mv["flags"] and st.sides[i].mon.alive:      # 부리캐논 대기 중 접촉 -> 공격자 화상 (타마다)
            self.try_status(st, i, st.sides[i].mon, "brn", rng, src_side=o, ignore_sub=True)
        self.run_hook(st, o, D, "on_hit_taken", rng, mv=mv, dmg=dmg, foe_side=i)
        if D.alive:
            if not defer:
                self.run_hook(st, o, D, "on_damage_taken_hp", rng, mv=mv, dmg=dmg, hp_before=hp_before, foe_side=i)
            if crit:
                self.run_hook(st, o, D, "on_crit_taken", rng, mv=mv, dmg=dmg, foe_side=i)

    def _on_faint(self, st, i, o, mv, rng, dmg):
        A, D = st.sides[i].mon, st.sides[o].mon
        self.run_hook(st, o, D, "on_faint", rng, mv=mv, dmg=dmg, foe_side=i)
        if A.alive:
            self.run_hook(st, i, A, "on_ko", rng, mv=mv, dmg=dmg, foe_side=o)

    def _contact_punish(self, st, i, o, mv, rng):
        if "contact" not in mv["flags"]:
            return
        A = st.sides[i].mon
        D = st.sides[o].mon
        for k in list(D.vol):
            if k in CONTACT_PUNISH:
                kind, v = CONTACT_PUNISH[k]
                if kind == "dmg":
                    self.hp_change(st, i, A, -max(1, math.floor(A.maxhp * v)), k)
                elif kind == "status":
                    self.try_status(st, i, A, v, rng, src_side=o, ignore_sub=True)
                else:
                    self.change_boost(st, i, A, v[0], v[1], src_side=o)

    # ───────────────────────── 부가효과 ─────────────────────────
    def _secondary(self, st, i, o, mv, rng, hit_sub=False):
        A, D = st.sides[i].mon, st.sides[o].mon
        if norm(A.ability) == "sheerforce":
            return
        if norm(mv["name"]) == "sparklingaria" and not hit_sub and D.alive and D.status == "brn" and norm(D.ability) != "shielddust":     # 상대의 화상을 치료한다
            D.status = None
            self._say(st, f"  {D.name} 화상 치료")
        mult = 2 if norm(A.ability) == "serenegrace" else 1
        need_raised = norm(mv["name"]) in ("alluringvoice", "burningjealousy")        # 상대가 이번 턴 능력이 올랐을 때만 (onHit 코드 조건)
        for e in mv["effects"]:
            if e["trigger_type"] != "secondary":
                continue
            if need_raised and e["applies_to"] == "target" and not self._raised_pre:
                continue
            if e["applies_to"] == "target":
                if hit_sub or not D.alive or norm(D.ability) == "shielddust" or norm(D.item) == "covertcloak":
                    continue
            elif not A.alive:
                continue
            if rng.random() * 100 >= (e["chance_pct"] or 100) * mult:
                continue
            self._apply_effect(st, i, o, e, rng)

    def _primary_self_effects(self, st, i, mv, rng):
        A = st.sides[i].mon
        for e in mv["effects"]:
            if e["trigger_type"] == "primary" and e["applies_to"] == "self":
                if e["kind"] == "stat_stage" and A.alive:
                    self.change_boost(st, i, A, e["code"], e["stages"] or 0)
                elif e["kind"] == "volatile" and e["code"] == "mustrecharge":
                    A.recharge = True
                elif e["kind"] == "volatile" and e["code"] == "glaiverush":
                    A.vol.add("glaiverush")

    def _apply_effect(self, st, i, o, e, rng):
        tgt_side = o if e["applies_to"] == "target" else i
        tgt = st.sides[tgt_side].mon
        k, code = e["kind"], e["code"]
        if k == "status":
            if code.startswith("random("):
                code = rng.choice(code[7:-1].split("|"))
            self.try_status(st, tgt_side, tgt, code, rng, src_side=i)
        elif k == "stat_stage":
            self.change_boost(st, tgt_side, tgt, code, e["stages"] or 0, src_side=(i if tgt_side != i else None))
        elif k == "volatile":
            if code == "flinch":
                if not tgt.moved and norm(tgt.ability) != "innerfocus":
                    tgt.vol.add("flinch")
            elif code == "confusion":
                if norm(tgt.ability) != "owntempo" and "confusion" not in tgt.vol:
                    self._confuse(st, tgt, rng.randint(2, 5))
            elif code == "leechseed":
                if "Grass" not in tgt.types:
                    tgt.vol.add("leechseed")
                    tgt.leech_to = i
            elif code == "focusenergy":
                tgt.vol.add("focusenergy")
            elif code == "taunt":
                immune = any((r["code"] or "").startswith("volatile:") and "taunt" in r["code"]
                             for r in self.data.ability_fx.get(norm(tgt.ability), []) if r["hook"] == "immunity")
                if tgt.taunt == 0 and not immune:
                    tgt.taunt = 3 + (1 if tgt.active_turns and tgt.moved else 0)
                    self._mental_herb(tgt)
            elif code == "throatchop":
                tgt.throat = tgt.throat or 2          # 이미 걸려 있으면 갱신되지 않는다
            elif code == "healblock":
                if not tgt.healblock:                                # 이미 걸려 있으면 지속 시간을 갱신하지 않는다
                    tgt.healblock = 5 if e["trigger_type"] == "primary" else 2
                    self._mental_herb(tgt)
            elif code == "destinybond":
                tgt.vol.add("destinybond")
            elif code == "stockpile":
                if tgt.stockpile < 3:
                    tgt.stockpile += 1
                    self.change_boost(st, tgt_side, tgt, "def", 1)
                    self.change_boost(st, tgt_side, tgt, "spd", 1)
            elif code == "partiallytrapped":
                if not tgt.trap and tgt.sub == 0:
                    tgt.trap = 8 if norm(st.sides[i].mon.item) == "gripclaw" else rng.choice([5, 6])       # Showdown: random(5, 7) / 조임손톱 8
                    tgt.trap_src = (i, st.sides[i].active)
                    tgt.vol.add("bindband" if norm(st.sides[i].mon.item) == "bindingband" else "bind")
            elif code not in PROTECT_MOVES:
                self._unsup("volatile:" + code)
        else:
            self._unsup(f"{k}:{code}")

    def _future_hit(self, st, tgt_side, fut, rng):
        """미래예지/파멸의소원 적중: 맞는 시점의 상태로 피해를 계산한다 (쓴 포켓몬이 쓰러졌거나 교체됐어도 맞는다)"""
        mv = self.data.moves[fut["key"]]
        src, D = fut["src"], st.sides[tgt_side].mon
        F = self.field_for(st, tgt_side)
        sa, sd = self.spec_of(src), self.spec_of(D)
        r = calc(self.data, sa, sd, mv["name"], F, False, hit=1, proc=False, flags=frozenset({"progress"}))
        if not r["rolls"]:
            self._say(st, "  미래공격: 효과 없음")
            return
        if rng.random() < 1 / 24:
            r = calc(self.data, sa, sd, mv["name"], F, True, hit=1, proc=False, flags=frozenset({"progress"}))
        dmg = rng.choice(r["rolls"])
        if D.hp == D.maxhp and dmg >= D.hp and (norm(D.item) == "focussash" or norm(D.ability) == "sturdy"):
            dmg = D.hp - 1
            if norm(D.item) == "focussash" and norm(D.ability) != "sturdy":
                D.item = ""
        dmg = min(dmg, D.hp)
        self._say(st, f"  미래공격 {D.name} -{dmg}")
        self.hp_change(st, tgt_side, D, -dmg, mv["name"])
        if D.alive:
            self.run_hook(st, tgt_side, D, "on_damage_taken_hp", rng)

    def _magic_end(self, st):
        st.magic_room = 0
        for S_ in st.sides:
            for m_ in S_.team:
                if m_.hid_item:
                    if not m_.item:
                        m_.item = m_.hid_item
                    m_.hid_item = ""

    def _mental_herb(self, bm):
        """멘탈허브: 도발/앙코르/힐블록 등이 걸리면 곧바로 풀고 소모한다 (onUpdate)"""
        if bm.alive and norm(bm.item) == "mentalherb" and (bm.taunt or bm.encore or bm.healblock or bm.disabled):
            bm.taunt = bm.encore = bm.healblock = bm.disable_n = 0
            bm.encore_move = ""
            bm.disabled = ""
            bm.item = ""

    def _self_destruct_fail(self, st, i, mv):
        """자폭 기술(Explosion 등)은 막히거나 빗나가거나 면역이어도 쓰는 순간 쓰러진다 (Showdown selfdestruct: 'always')"""
        A = st.sides[i].mon
        if mv["self_destruct"] and mv["category"] != "status" and A.alive and norm(mv["name"]) != "finalgambit":      # 아슬아슬한승부는 맞았을 때만 (selfdestruct: ifHit)
            self.hp_change(st, i, A, -A.hp, "자폭")

    def _will_act(self, st, i):
        return any(j != i and st.sides[j].mon.alive and st.sides[j].active == self._starts[j] for j in self._later)

    def _status_move(self, st, i, mv, rng, bounced=False):
        A, D = st.sides[i].mon, st.sides[1 - i].mon
        o = 1 - i
        key = norm(mv["name"])
        self._sfail = False                         # 실패하면 True -> 직전 기술 실패 조건(Temper Flare 등)과 Stomping Tantrum 에 쓴다
        if key == "copycat":                        # 전투 전체에서 직전에 쓰인 기술을 그대로 쓴다 (불러 쓸 수 없는 기술이면 실패)
            lm = st.lastmove_any
            if lm and lm in self.data.moves and "failcopycat" not in self.data.moves[lm]["flags"] and lm != "copycat":
                self._say(st, f"  따라하기 -> {self.data.moves[lm]['name']}")
                self._run_move(st, i, self.data.moves[lm], lm, self._acts, rng, self._policy)
            else:
                self._sfail = True
            return
        if key in ("endure", "quickguard", "wideguard") or key in PROTECT_MOVES:
            if not self._will_act(st, i):            # 이번 턴에 뒤에 행동할 상대가 없으면 실패. stall 이 갱신되지 않으므로 다음 턴엔 카운터가 사라진다
                self._say(st, "  실패 (마지막 행동)")
                A.protect_n = 0
                self._sfail = True
                return
        if key in ("quickguard", "wideguard"):
            A.vol.add(key)
            A.protect_n += 1
            return
        if key == "endure":
            if rng.random() < 1 / (3 ** min(A.protect_n, 5)):
                A.vol.add("enduring")
                A.protect_n += 1
            else:
                A.protect_n = 0
                self._sfail = True
            return
        if key in PROTECT_MOVES or any(e["kind"] == "volatile" and e["code"] in PROTECT_MOVES for e in mv["effects"]):
            if rng.random() < 1 / (3 ** min(A.protect_n, 5)):
                A.vol.add("protecting")
                for e in mv["effects"]:
                    if e["code"] in CONTACT_PUNISH:
                        A.vol.add(e["code"])
                A.protect_n += 1
            else:
                A.protect_n = 0
                self._sfail = True
            return
        tself = mv["target"] in NON_FOE_TARGETS
        if "reflectable" in mv["flags"] and D.alive and norm(D.ability) == "magicbounce" and not bounced and mv["target"] in ("normal", "foeSide"):
            self._say(st, "  반사")
            self._status_move(st, o, mv, rng, bounced=True)
            return
        if not tself:
            if "powder" in mv["flags"] and ("Grass" in D.types or norm(D.ability) == "overcoat" or norm(D.item) == "safetygoggles"):
                return
            if norm(A.ability) == "prankster" and "Dark" in D.types:
                return
            if D.sub > 0 and "bypasssub" not in mv["flags"] and norm(A.ability) != "infiltrator":
                return
            for r in mv["rules"]:
                if r["type"] == "target_immunity":
                    p_ = r["params"]
                    if any(t in self.types_of(D) for t in p_.get("immune_types", [])):
                        return
                    if p_.get("type_chart_applies") and self._chart_immune(mv, D):
                        return
                    if norm(D.ability) in {norm(x) for x in p_.get("immune_abilities", [])}:
                        return
            if not self._hits(st, i, o, mv, rng, False):
                self._say(st, "  빗나감")
                return
        handled = False
        if key in ("soak", "magicpowder", "forestscurse", "trickortreat"):                 # 대상의 타입 변경 (이미 같은 상태면 실패)
            if D.sub > 0:
                self._sfail = True
                return
            new_t, add = {"soak": ("Water", False), "magicpowder": ("Psychic", False), "forestscurse": ("Grass", True), "trickortreat": ("Ghost", True)}[key]
            if (add and new_t in D.types) or (not add and D.types == [new_t]) or D.sid in ("arceus", "silvally") or norm(D.ability) == "rkssystem":
                self._sfail = True
                return
            D.types = ([t for t in D.types if t != "Typeless"] + [new_t]) if add else [new_t]
            return
        if key == "reflecttype":
            if not D.types or D.sid in ("arceus", "silvally"):
                self._sfail = True
                return
            A.types = list(D.types)
            return
        if key == "strengthsap":                            # 상대의 (단계 반영한) 공격 스탯만큼 회복하고 상대 공격을 1단계 내린다
            if D.sub > 0:
                self._sfail = True
                return

            def stage_(v, b_):
                return v * (2 + b_) // 2 if b_ >= 0 else v * 2 // (2 - b_)
            atk = stage_(make_mon(self.data, self.spec_of(D)).stats["atk"], D.boosts.get("atk", 0))
            gained = self.hp_change(st, i, A, atk, "힘흡수")
            before = D.boosts.get("atk", 0)
            self.change_boost(st, o, D, "atk", -1, src_side=i)
            if not gained and D.boosts.get("atk", 0) == before:
                self._sfail = True
            return
        if key == "perishsong":                              # 필드의 모든 포켓몬에게 카운트를 건다 (방음은 면역)
            hit = False
            for S_ in st.sides:
                m_ = S_.mon
                if m_.alive and not m_.perish and norm(m_.ability) != "soundproof":
                    m_.perish, hit = 4, True
            if not hit:
                self._sfail = True
            return
        if key == "substitute":
            cost = A.maxhp // 4
            if A.sub == 0 and A.hp > cost:
                self.hp_change(st, i, A, -cost, "대타출동")
                A.sub = cost
                A.trap = 0                                    # 대타를 만들면 걸려 있던 속박이 풀린다 (Showdown: substitute onStart 에서 partiallytrapped 제거)
                A.vol.discard("bind"); A.vol.discard("bindband")
            return
        if key == "curse":
            if "Ghost" in A.types:
                if "curse" not in D.vol and A.hp > 1:                  # bypasssub: 대타가 있어도 걸린다
                    self.hp_change(st, i, A, -(A.maxhp // 2), "저주")
                    D.vol.add("curse")
            else:
                self.change_boost(st, i, A, "spe", -1)
                self.change_boost(st, i, A, "atk", 1)
                self.change_boost(st, i, A, "def", 1)
            return
        if (mv["heal"] or any(r["type"] == "heal_move" and "table" in r["params"] for r in mv["rules"]))                 and A.hp == A.maxhp and key not in ("rest",) and mv["target"] == "self":
            self._sfail = True
            return
        if key == "destinybond":
            if A.db_pending:                                # 연속으로 쓰면 실패하고 (onPrepareHit 가 상태를 지운다) 다음 시도는 성공한다
                A.db_pending = False
                self._sfail = True
                return
            A.db_pending = True
        if key == "revivalblessing":
            dead = [m for m in st.sides[i].team if not m.alive]
            if dead:
                m = dead[0]
                m.hp = max(1, m.maxhp // 2)             # Showdown: 최대 HP 의 절반을 내림 (151 -> 75)
                m.status = None
            return
        if key == "skillswap":
            if D.sub == 0 or "bypasssub" in mv["flags"]:
                if norm(A.ability) not in NO_SWAP and norm(D.ability) not in NO_SWAP:
                    A.abil_orig, D.abil_orig = A.abil_orig or A.ability, D.abil_orig or D.ability
                    A.ability, D.ability = D.ability, A.ability
                    for sd_, m_ in ((i, A), (o, D)):                 # 바꿔 받은 특성의 등장 효과가 바로 발동한다 (사이코메이커, 위협 등)
                        if m_.alive:
                            self._run_switch_in(st, sd_, m_, rng, only="ability")
            return
        if key == "courtchange":
            a, b = st.sides[i], st.sides[1 - i]
            for k in ("spikes", "toxicspikes", "stealthrock", "stickyweb"):
                va, vb = a.hazards.pop(k, None), b.hazards.pop(k, None)
                if va is not None:
                    b.hazards[k] = va
                if vb is not None:
                    a.hazards[k] = vb
            for k in ("reflect", "light_screen", "aurora_veil", "safeguard", "tailwind"):
                va, vb = a.screens.pop(k, None), b.screens.pop(k, None)
                if va is not None:
                    b.screens[k] = va
                if vb is not None:
                    a.screens[k] = vb
            return
        if key == "magicroom":                  # 매직룸: 5턴 동안 모든 도구 효과가 사라진다 (다시 쓰면 해제). 도구를 숨겼다가 끝나면 되돌린다
            if st.magic_room:
                self._magic_end(st)
            else:
                st.magic_room = 5
                for S_ in st.sides:
                    for m_ in S_.team:
                        if m_.item:
                            m_.hid_item, m_.item = m_.item, ""
            return
        if key == "trickroom":
            st.trick_room = 0 if st.trick_room else 5
            return
        if key == "transform":
            if D.alive and not self._transform(st, A, D):
                pass
            return
        if key == "memento":
            if (D.sub == 0 or "bypasssub" in mv["flags"]):
                self.change_boost(st, o, D, "atk", -2, src_side=i)
                self.change_boost(st, o, D, "spa", -2, src_side=i)
            self.hp_change(st, i, A, -A.hp, "메멘토")
            return
        if key == "yawn":
            if (D.sub == 0 or "bypasssub" in mv["flags"]) and not D.yawn and not D.status and not (st.terrain in ("electric", "misty") and self._grounded(D)):
                if not any(r["hook"] == "immunity" and (r["code"] or "").startswith("status:slp") for r in self.data.ability_fx.get(norm(D.ability), [])):
                    D.yawn = 2
            return
        if key == "disable":
            if D.alive and not D.disabled and D.last_move and D.last_move != "struggle":
                D.disabled, D.disable_n = D.last_move, (5 if D.moved else 4)
                self._mental_herb(D)
            else:
                self._sfail = True
            return
        if key == "encore":
            if (D.sub == 0 or "bypasssub" in mv["flags"]) and not D.encore and D.last_move and D.last_move not in ("encore",) and \
                    D.last_move not in D.spent and "failencore" not in self.data.moves[D.last_move]["flags"]:        # PP 가 0 인 기술(되살리기)에는 실패
                D.encore = 4 if D.moved else 3                    # 이번 턴에 이미 움직인 상대는 1턴 더 (Showdown: willMove 가 아니면 duration++)
                D.encore_move = D.last_move
                self._mental_herb(D)
            else:
                self._sfail = True
            return
        if key == "haze":
            A.boosts, D.boosts = {}, {}
            return
        if key == "bellydrum":
            if A.hp > A.maxhp // 2 and A.boosts.get("atk", 0) < 6:
                self.hp_change(st, i, A, -(A.maxhp // 2), "배북")
                A.boosts["atk"] = 6
            return
        if key in ("trick", "switcheroo"):
            def locked(m):
                return bool(m.item) and any(r["kind"] == "mega_stone" for r in self.data.item_fx.get(norm(m.item), [])) and "mega" in m.sid
            if norm(D.ability) != "stickyhold" and (A.item or D.item) and not locked(A) and not locked(D) and D.sub == 0:
                A.item, D.item = D.item, A.item
                A.locked = D.locked = None                      # 아이템이 새로 들어오면 구애 고정 볼라타일은 사라진다 (같은 아이템끼리 바꿔도)
                for sd_, m_ in ((i, A), (o, D)):                 # 받은 열매는 조건이 되면 바로 먹는다 (HP 절반 이하의 시트러스 등)
                    if m_.alive and m_.item:
                        self.run_hook(st, sd_, m_, "on_damage_taken_hp", rng, only="item")
            return
        if key == "painsplit":
            if (D.sub == 0 or "bypasssub" in mv["flags"]):
                avg = (A.hp + D.hp) // 2
                A.hp, D.hp = min(A.maxhp, avg), min(D.maxhp, avg)
            return
        if key == "defog":
            if (D.sub == 0 or "bypasssub" in mv["flags"]):
                self.change_boost(st, o, D, "evasion", -1, src_side=i)
            for sd in (st.sides[o], st.sides[i]):
                for h in ("spikes", "toxicspikes", "stealthrock", "stickyweb"):
                    sd.hazards.pop(h, None)
            for k in ("reflect", "light_screen", "aurora_veil", "safeguard"):
                st.sides[o].screens.pop(k, None)
            st.terrain = None
            return
        if key == "partingshot":
            before = (D.boosts.get("atk", 0), D.boosts.get("spa", 0))
            self.change_boost(st, o, D, "atk", -1, src_side=i)
            self.change_boost(st, o, D, "spa", -1, src_side=i)
            if (D.boosts.get("atk", 0), D.boosts.get("spa", 0)) != before or norm(D.ability) == "mirrorarmor":
                self._self_switch(st, i, rng, False)
            return
        if key == "wish":
            if st.sides[i].wish is None:
                st.sides[i].wish = [2, max(1, A.maxhp // 2)]
            return
        if key in ("healingwish", "lunardance"):
            if len(st.sides[i].alive_idx()) > 1:
                self.hp_change(st, i, A, -A.hp, key)
                st.sides[i].heal_next = key
            return
        if mv["force_switch"]:
            cand = [j for j in st.sides[o].alive_idx() if j != st.sides[o].active]
            if cand and D.alive and norm(D.ability) not in ("suctioncups",):
                self._switch_in(st, o, rng, to=rng.choice(cand))
            return
        for e in mv["effects"]:
            if e["trigger_type"] != "primary":
                continue
            handled = True
            if (e["chance_pct"] or 100) < 100 and rng.random() * 100 >= e["chance_pct"]:
                continue
            kind = e["kind"]
            if kind == "weather":
                w = {"sunnyday": "sun", "raindance": "rain", "sandstorm": "sand", "snowscape": "snow", "hail": "snow"}.get(e["code"].lower())
                if w and st.weather != w:
                    self._set_weather(st, w, A)
            elif kind == "terrain":
                t = e["code"].replace("terrain", "")
                if st.terrain != t:
                    st.terrain = t
                    st.terrain_turns = 8 if any(r["code"] == "extend_terrain" for r in self.data.item_fx.get(norm(A.item), [])) else 5
                    self._terrain_seeds(st, rng)
            elif kind == "side_condition":
                self._side_condition(st, i, e["code"])
            elif kind in ("status", "stat_stage", "volatile"):
                if kind == "volatile" and e["code"] in PROTECT_MOVES:
                    continue
                if e["applies_to"] == "self" and kind == "stat_stage":
                    self.change_boost(st, i, A, e["code"], e["stages"] or 0)
                elif e["applies_to"] == "self" and kind == "volatile":
                    if e["code"] == "focusenergy":
                        A.vol.add("focusenergy")
                    elif e["code"] == "roost":
                        A.vol.add("roost")
                    elif e["code"] in ("stockpile", "destinybond"):
                        self._apply_effect(st, i, i, dict(e, applies_to="self"), rng)
                    elif e["code"] not in ("protect",):
                        self._unsup("volatile:" + e["code"])
                elif not (kind == "status" and "substitute" in D.vol):
                    self._apply_effect(st, i, o, e, rng)
            else:
                self._unsup(f"{kind}:{e['code']}")
        table = next((r["params"]["table"] for r in mv["rules"] if r["type"] == "heal_move" and "table" in r["params"]), None)
        if (mv["heal"] or table) and A.alive:
            if table:       # 날씨에 따라 비율이 바뀌는 회복(아침햇살 등): Showdown 의 modify -- 4096 기준 고정소수점, 0.5 는 내림
                w_ = "sun" if any(r["code"] == "treat_weather_as:sun" for r in self.data.ability_fx.get(norm(A.ability), [])) else st.weather
                frac = table.get(w_ or "default", table["default"])
                if abs(frac - 0.667) < 1e-3:
                    frac = 0.667
                mod = math.floor(frac * 4096)
                amount = (math.floor(A.maxhp * mod) + 2047) // 4096
            else:           # 고정 비율 회복(회복 등): Math.round (0.5 는 올림)
                amount = math.floor(A.maxhp * mv["heal"] / 100 + 0.5)
            self.hp_change(st, i, A, amount, "회복")
        for r in mv["rules"]:
            if r["type"] == "extra_effect" and r["params"].get("effect") == "full_heal_and_sleep":
                sleepless = norm(A.ability) in ("insomnia", "vitalspirit", "sweetveil") or (
                    st.terrain in ("electric", "misty") and self._grounded(A))
                if A.status != "slp" and A.hp < A.maxhp and not sleepless:
                    A.hp, A.status, A.sleep = A.maxhp, "slp", 3
                    self._status_item_cure(st, A, "slp")
                handled = True
        if key == "shedtail":
            cost = A.maxhp // 2
            if A.hp > cost and len(st.sides[i].alive_idx()) > 1 and A.sub == 0:
                self.hp_change(st, i, A, -cost, "꼬리자르기")
                A.sub = A.maxhp // 4
                self._self_switch(st, i, rng, True)
            return
        if mv["self_switch"] and A.alive and key not in ("partingshot", "revivalblessing"):
            self._self_switch(st, i, rng, key == "batonpass")
        if not handled and not mv["heal"] and not table and not mv["self_switch"] and not any(r["type"] in ("extra_effect", "heal_move") for r in mv["rules"]):
            self._unsup("move:" + mv["name"])

    def _self_switch(self, st, i, rng, carry):
        cand = [j for j in st.sides[i].alive_idx() if j != st.sides[i].active]
        if not cand or st.winner is not None:
            return
        j = self._policy(st, i) if self._policy else cand[0]
        self._switch_in(st, i, rng, to=j if j in cand else cand[0], carry=carry)

    def _side_condition(self, st, i, code, swap=False):
        """swap=True 면 i 가 '해저드를 받는 쪽'(기술 사용자의 상대)"""
        S, T = (st.sides[1 - i], st.sides[i]) if swap else (st.sides[i], st.sides[1 - i])
        if code in ("reflect", "lightscreen", "auroraveil"):
            k = {"reflect": "reflect", "lightscreen": "light_screen", "auroraveil": "aurora_veil"}[code]
            if S.screens.get(k, 0) <= 0:
                S.screens[k] = 8 if norm(S.mon.item) == "lightclay" else 5
        elif code == "tailwind":
            if S.screens.get("tailwind", 0) <= 0:                 # 이미 불고 있으면 실패 (지속 시간은 그대로)
                S.screens["tailwind"] = 4
        elif code == "stealthrock":
            T.hazards["stealthrock"] = 1
        elif code == "spikes":
            T.hazards["spikes"] = min(3, T.hazards.get("spikes", 0) + 1)
        elif code == "toxicspikes":
            T.hazards["toxicspikes"] = min(2, T.hazards.get("toxicspikes", 0) + 1)
        elif code == "stickyweb":
            T.hazards["stickyweb"] = 1
        elif code == "safeguard":
            S.screens["safeguard"] = 5
        else:
            self._unsup("side_condition:" + code)

    # ───────────────────────── 턴 종료 ─────────────────────────
    def _end_of_turn(self, st, rng):
        order = sorted((0, 1), key=lambda i: ((1 if st.trick_room else -1) * self.speed_of(st, i), rng.random()))
        if st.trick_room:
            st.trick_room -= 1
        if st.weather:
            st.weather_turns -= 1
            if st.weather_turns <= 0:
                st.weather = None
        for i in order:
            bm = st.sides[i].mon
            if bm.alive and st.weather == "sand" and not any(t in ("Rock", "Ground", "Steel") for t in bm.types) and \
                    norm(bm.ability) not in ("magicguard", "overcoat", "sandveil", "sandrush", "sandforce") and norm(bm.item) != "safetygoggles":
                self.hp_change(st, i, bm, -max(1, bm.maxhp // 16), "모래바람")
            fut = st.sides[i].future
            if fut:                                              # 미래예지: 3 -> 0 이 되는 턴 끝에 적중 (쓰러진 슬롯이면 사라진다)
                fut["left"] -= 1
                if fut["left"] <= 0:
                    st.sides[i].future = None
                    if bm.alive:
                        self._future_hit(st, i, fut, rng)
            S_ = st.sides[i]
            if S_.wish:                                          # 슬롯에 걸린 효과라서 쓰러진 턴에도 카운트가 진행된다 (대상이 없으면 사라짐)
                S_.wish[0] -= 1
                if S_.wish[0] <= 0:
                    if bm.alive:
                        self.hp_change(st, i, bm, S_.wish[1], "희망사항")
                    S_.wish = None
            if not bm.alive:
                continue
            if st.terrain == "grassy" and bm.alive and self._grounded(bm):
                self.hp_change(st, i, bm, max(1, bm.maxhp // 16), "그래스필드")
            if bm.alive:
                for src, r in self.rows(bm, "turn_end"):
                    if not self._cond_ok(r["cond"], st, i, bm):
                        continue
                    if r["label"].endswith("Speed Boost") and bm.active_turns == 0:
                        continue
                    if r["kind"] in ("heal_frac", "damage_frac", "cure_status", "stat_stage"):
                        self.apply_row(st, r["label"], r, i, bm, rng)
                        if not bm.alive:
                            break
            if bm.alive and norm(bm.item) == "blacksludge":
                self.hp_change(st, i, bm, max(1, bm.maxhp // 16) if "Poison" in bm.types else -max(1, bm.maxhp // 8), "검은진흙")
            if bm.alive and "leechseed" in bm.vol and norm(bm.ability) != "magicguard" and st.sides[1 - i].mon.alive:    # 씨를 뿌린 쪽이 쓰러졌으면 피해 없음
                d = max(1, bm.maxhp // 8)
                self.hp_change(st, i, bm, -d, "씨뿌리기")
                src = st.sides[1 - i].mon
                if src.alive:
                    self.hp_change(st, 1 - i, src, d, "씨뿌리기 흡수")
            if bm.alive and bm.status in ("psn", "tox", "brn") and norm(bm.ability) != "magicguard":
                if bm.status == "psn" and norm(bm.ability) != "poisonheal":
                    self.hp_change(st, i, bm, -max(1, bm.maxhp // 8), "독")
                elif bm.status == "tox":
                    if norm(bm.ability) != "poisonheal":
                        self.hp_change(st, i, bm, -max(1, bm.maxhp // 16) * bm.tox, "맹독")
                    bm.tox = min(15, bm.tox + 1)
                elif bm.status == "brn":
                    self.hp_change(st, i, bm, -max(1, bm.maxhp // (32 if norm(bm.ability) == "heatproof" else 16)), "화상")
        for i in order:              # Showdown 은 효과 종류별 순서(씨뿌리기 8, 독 9, 화상 10, 저주 12, 조임 13 ...)로 모든 포켓몬을 처리한다 -> 두 번째 패스
            bm = st.sides[i].mon
            if bm.taunt:
                bm.taunt -= 1
            if bm.healblock:
                bm.healblock -= 1
            if bm.encore:
                bm.encore -= 1
                if not bm.encore:
                    bm.encore_move = ""
            if bm.charged:
                bm.charged -= 1
            if bm.disable_n:
                bm.disable_n -= 1
                if not bm.disable_n:
                    bm.disabled = ""
            if bm.throat:
                bm.throat -= 1
            if bm.yawn:
                bm.yawn -= 1
                if bm.yawn == 0 and bm.alive:
                    self.try_status(st, i, bm, "slp", rng)
            if bm.alive and "curse" in bm.vol and norm(bm.ability) != "magicguard":
                self.hp_change(st, i, bm, -max(1, bm.maxhp // 4), "저주")
            if bm.alive and bm.trap and bm.trap_src and (
                    st.sides[bm.trap_src[0]].active != bm.trap_src[1] or not st.sides[bm.trap_src[0]].mon.alive):
                bm.trap = 0
                bm.vol.discard("bind"); bm.vol.discard("bindband")
            if bm.alive and bm.trap:
                bm.trap -= 1
                if bm.trap <= 0:
                    bm.vol.discard("bind"); bm.vol.discard("bindband")
                elif norm(bm.ability) != "magicguard":
                    self.hp_change(st, i, bm, -max(1, math.floor(bm.maxhp * (1 / 6 if "bindband" in bm.vol else 1 / 8))), "속박")
            if bm.alive:
                self.run_hook(st, i, bm, "on_damage_taken_hp", rng)
            if bm.alive and norm(bm.item) in ("toxicorb", "flameorb") and not bm.status:
                self.try_status(st, i, bm, "tox" if norm(bm.item) == "toxicorb" else "brn", rng, src_side=i)
            if bm.alive and bm.perish:                           # 멸망의노래: 카운트가 0 이 되면 쓰러진다
                bm.perish -= 1
                if bm.perish == 0:
                    self.hp_change(st, i, bm, -bm.hp, "멸망의노래")
        for i in (0, 1):
            st.sides[i].mon.vol.discard("roost")
        for i in (0, 1):
            S = st.sides[i]
            for k in list(S.screens):
                S.screens[k] -= 1
                if S.screens[k] <= 0:
                    del S.screens[k]
        if st.terrain:
            st.terrain_turns -= 1
            if st.terrain_turns <= 0:
                st.terrain = None
        if st.magic_room:
            st.magic_room -= 1
            if not st.magic_room:
                self._magic_end(st)

    # ───────────────────────── 편의 ─────────────────────────
    def clone(self, st):
        c = copy.deepcopy(st)
        c.log = None
        return c
