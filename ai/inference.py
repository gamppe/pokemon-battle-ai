"""상대 세트 추론기 (2단계).
메타(meta_* 분포)를 사전확률로 두고, 전투 중 드러나는 정보로 상대 한 마리의 세트(특성/도구/성격+SP/기술)를 베이즈로 좁힌다.

가설 공간: (성격+SP 배분, 특성, 도구) 조합 — 메타 주변분포의 곱을 사전확률로 쓴다. [근사: 상관 없음]
기술은 조합 대신 "기술별 포함 확률"로 따로 관리한다 (보인 기술은 확정, 나머지는 남은 칸 수에 맞춰 재정규화).

증거 종류
- 기술/특성/도구 공개: 확정 (observe_move / observe_ability / observe_item / observe_no_item)
- 속도 순서: 우선도가 같은 기술끼리 누가 먼저 움직였는지 (observe_speed)
- 데미지: 상대가 내 포켓몬에게 준 정확한 HP 감소(observe_damage_taken), 내가 상대에게 준 HP% 감소(observe_damage_dealt)
  → damage_calc 의 16개 난수 중 관측과 맞는 비율을 우도로 쓴다
- 고정 기술: 같은 기술만 반복하면 구애 아이템 우도를 올린다 (observe_repeat)"""
import math
import random
from dataclasses import dataclass

from .damage_calc import Ctx, Field, calc, make_mon, speed as calc_speed
from .gamedata import norm

CHOICE_ITEMS = ("choiceband", "choicespecs", "choicescarf")
CRIT_P = 1 / 24
EPS = 0.02          # 관측과 완전히 어긋나도 가설을 완전히 지우지 않는 최소 우도 (모델 오차/미구현 효과 대비)


@dataclass
class Hyp:
    nature: str
    sp: dict
    ability: str
    item: str
    w: float


def eff_speed(data, spec, field=None, tailwind=False, status=None, boosts=None):
    s = dict(spec, status=status, boosts=boosts or {}, hp_frac=None)
    m = make_mon(data, s)
    c = Ctx(data, m, m, {}, field or Field(), False)
    v = calc_speed(c, m)
    return v * 2 if tailwind else v


class OppModel:
    """상대 한 마리에 대한 사후분포"""

    def __init__(self, meta, data, sid, prior_floor=1e-4):
        self.meta, self.data, self.sid = meta, data, sid
        spreads = meta.spreads.get(sid) or [(("Serious", {}), 1.0)]
        abilities = meta.abilities.get(sid) or [(next(iter(data.pokemon[sid]["abilities"].values()), ""), 1.0)]
        items = meta.items.get(sid) or [("", 1.0)]
        self.hyps = []
        for (nat, sp), ps in spreads:
            for ab, pa in abilities:
                for it, pi in items:
                    w = ps * pa * pi
                    if w >= prior_floor * 1e-2:
                        self.hyps.append(Hyp(nat, sp, ab, it, w))
        self.hyps = [h for h in self.hyps if h.w >= 2e-6 * sum(x.w for x in self.hyps)]      # 극히 희박한 조합은 버려 계산량을 줄인다
        self._normalize()
        self.prior_moves = {m: p for m, p in meta.moves.get(sid, []) if m in data.moves}
        self.seen_moves = []
        self._cache = {}
        self.known_ability = None
        self.known_item = None          # None=미공개, ""=없음 확정, 이름=확정
        self.stay_last = None           # 현재 등장 중 마지막으로 쓴 기술

    # ───────── 공통 ─────────
    def _normalize(self):
        t = sum(h.w for h in self.hyps) or 1.0
        for h in self.hyps:
            h.w /= t
        self._q = None

    def _spec(self, h, **extra):
        return dict(sid=self.sid, ability=h.ability, item=h.item, nature=h.nature, sp=h.sp, **extra)

    def _update(self, likelihood):
        """likelihood(h) -> 우도. 전체가 0이면 변경하지 않는다(모델 밖 관측)"""
        new = [likelihood(h) for h in self.hyps]
        if sum(a * h.w for a, h in zip(new, self.hyps)) <= 0:
            return
        for a, h in zip(new, self.hyps):
            h.w *= max(a, 0.0)
        self._normalize()

    # ───────── 확정형 증거 ─────────
    def observe_ability(self, ability):
        self.known_ability = ability
        self._update(lambda h: 1.0 if norm(h.ability) == norm(ability) else 0.0)

    def observe_item(self, item):
        self.known_item = item
        self._update(lambda h: 1.0 if norm(h.item) == norm(item) else 0.0)

    def observe_no_item(self):
        """도구를 잃었거나 처음부터 없다고 확인된 경우 (소모 후에는 observe_item 으로 원래 도구를 알려주는 편이 낫다)"""
        self.known_item = ""

    def observe_move(self, key):
        key = norm(key)
        if key not in self.seen_moves:
            self.seen_moves.append(key)

    def left_field(self):
        """필드에서 내려갔다 (구애 고정 추적 초기화)"""
        self.stay_last = None

    def note_move(self, key):
        """상대가 기술을 썼다: 기술 공개 + (구애 고정/돌격조끼) 증거"""
        key = norm(key)
        mv = self.data.moves.get(key)
        if mv is not None:
            if mv["category"] == "status":
                self._update(lambda h: 0.0 if norm(h.item) == "assaultvest" else 1.0)
            forced = any(r["type"] == "charge_move" for r in mv["rules"]) or any(e["code"] == "lockedmove" for e in mv["effects"])                 or "recharge" in mv["flags"]
            if self.stay_last is not None and not forced and self.known_item is None:
                prev = self.data.moves.get(self.stay_last)
                prev_forced = prev is not None and (any(r["type"] == "charge_move" for r in prev["rules"])
                                                    or any(e["code"] == "lockedmove" for e in prev["effects"]) or "recharge" in prev["flags"])
                if not prev_forced:
                    if key != self.stay_last:
                        self._update(lambda h: EPS if norm(h.item) in CHOICE_ITEMS else 1.0)       # 다른 기술을 썼으니 구애 계열은 거의 아님
                    else:
                        self.observe_repeat(key)
            if not forced:
                self.stay_last = key
            else:
                self.stay_last = None
        self.observe_move(key)

    def observe_switch_in(self, triggered_abilities, weather_before=None, terrain_before=None):
        """등장 직후 발동한 특성 집합. 등장 효과가 있는 특성인데 발동하지 않았으면 우도를 크게 낮춘다"""
        trig = {norm(a) for a in triggered_abilities}

        def expects(ab):
            for r in self.data.ability_fx.get(norm(ab), []):
                if r["hook"] != "switch_in":
                    continue
                if r["kind"] == "set_weather" and r["code"] != weather_before:
                    return True
                if r["kind"] == "set_terrain" and r["code"] != terrain_before:
                    return True
                if r["kind"] == "stat_stage" and r["target"] == "foe":
                    return True
            return False
        self._update(lambda h: 1.0 if (norm(h.ability) in trig or not expects(h.ability)) else 0.05)

    def observe_repeat(self, key, turns=2, alternatives=True):
        """같은 기술을 turns 번 연속 사용 (다른 기술이 가능한 상황). 구애 계열 가설의 우도를 올린다"""
        if not alternatives:
            return
        self._update(lambda h: 1.0 if norm(h.item) in CHOICE_ITEMS else 0.5 ** (turns - 1))

    # ───────── 속도 ─────────
    def observe_speed(self, our_speed, opp_first, field=None, tailwind=False, status=None, boosts=None):
        """우선도가 같은 두 기술에서 상대가 먼저(opp_first=True)/나중에 움직였다. our_speed 는 내 실질 속도"""
        cache = {}

        def lik(h):
            k = (h.nature, tuple(sorted(h.sp.items())), h.ability, h.item)
            if k not in cache:
                cache[k] = eff_speed(self.data, self._spec(h), field, tailwind, status, boosts)
            v = cache[k]
            if v == our_speed:
                return 0.5
            return 1.0 if ((v > our_speed) == opp_first) else EPS
        self._update(lik)

    # ───────── 데미지 ─────────
    def _rolls(self, h, d_spec, move, field, crit, attacker_is_opp):
        key = (h.nature, tuple(sorted(h.sp.items())), h.ability, h.item, move, repr(sorted(d_spec.items())),
               field.weather, field.terrain, field.screens, crit, attacker_is_opp)
        r = self._cache.get(key)
        if r is None:
            if attacker_is_opp:
                r = calc(self.data, self._spec(h, boosts={}, status=None, hp_frac=None), d_spec, move, field, crit)
            else:
                r = calc(self.data, d_spec, self._spec(h, boosts={}, status=None, hp_frac=d_spec.get("_opp_hp_frac")), move, field, crit)
            self._cache[key] = r
        return r

    def observe_damage_taken(self, our_spec, move, damage, field=None, crit=False, hits=1):
        """상대가 move 로 내 포켓몬(our_spec: 그 시점의 상태 포함)에게 정확히 damage 만큼 줬다 (단발 기준)"""
        field = field or Field()
        move = self.data.moves[norm(move)]["name"]

        def lik(h):
            r = self._rolls(h, our_spec, move, field, crit, True)
            if not r["rolls"]:
                return EPS
            p = sum(1 for v in r["rolls"] if v == damage) / len(r["rolls"])
            if not crit:                        # 급소였을 가능성(1/24)도 섞는다
                rc = self._rolls(h, our_spec, move, field, True, True)
                pc = sum(1 for v in (rc["rolls"] or []) if v == damage) / len(rc["rolls"]) if rc["rolls"] else 0.0
                p = (1 - CRIT_P) * p + CRIT_P * pc
            return max(p, EPS)
        self._update(lik)

    def observe_damage_dealt(self, our_spec, move, opp_hp_frac_before, opp_pct_after, field=None, crit=False, tol=1.5):
        """내가 move 로 상대에게 줬고, 상대 HP 표시가 opp_hp_frac_before → opp_pct_after(%) 가 됐다"""
        field = field or Field()
        move = self.data.moves[norm(move)]["name"]
        base = norm(self.sid)
        pk = self.data.pokemon[self.sid]

        def lik(h):
            spec = dict(our_spec, _opp_hp_frac=opp_hp_frac_before)
            r = self._rolls(h, spec, move, field, crit, False)
            if not r["rolls"]:
                return EPS
            M = pk["base"]["hp"] + h.sp.get("hp", 0) + 75
            before = opp_hp_frac_before * M

            def frac_ok(rolls):
                return sum(1 for v in rolls if abs(max(0.0, before - v) / M * 100 - opp_pct_after) <= tol) / len(rolls)
            p = frac_ok(r["rolls"])
            if not crit:
                rc = self._rolls(h, spec, move, field, True, False)
                if rc["rolls"]:
                    p = (1 - CRIT_P) * p + CRIT_P * frac_ok(rc["rolls"])
            return max(p, EPS)
        self._update(lik)

    # ───────── 결과 ─────────
    legacy = False          # True 면 이전 방식(상한 1 로 자르기 + 가중 비복원 추첨) 으로 동작 (비교 실험용)

    def _move_probs_legacy(self):
        seen = set(self.seen_moves)
        slots = max(0, 4 - len(seen))
        rest = {m: p for m, p in self.prior_moves.items() if m not in seen}
        tot = sum(rest.values()) or 1.0
        out = {m: 1.0 for m in seen}
        for m, p in rest.items():
            out[m] = min(1.0, p * slots / tot) if slots else 0.0
        return out

    def _move_probs(self, h=None):
        if self.legacy:
            return self._move_probs_legacy()
        """보인 기술은 1, 나머지는 남은 칸 수(= 4 - 보인 수)에 맞게 포함 확률을 정한다 (합이 정확히 칸 수가 되도록 상한 1 을 고려해 비례 배분).
        h(가설)가 주어지면 구애 계열/돌격조끼처럼 변화기를 거의 안 쓰는 도구에서는 변화 기술 가중치를 낮춘다."""
        seen = set(self.seen_moves)
        slots = max(0, 4 - len(seen))
        rest = {m: p for m, p in self.prior_moves.items() if m not in seen}
        if h is not None and rest:
            q = getattr(self, "_q", None)
            if q is None:
                qc = sum(x.w for x in self.hyps if norm(x.item) in CHOICE_ITEMS)
                qv = sum(x.w for x in self.hyps if norm(x.item) == "assaultvest")
                self._q = q = (qc, qv)
            qc, qv = q
            fc, fv = 0.15, 0.0                                   # 구애 계열은 변화기 가중치 0.15배, 돌격조끼는 0
            rest_mass = 1.0 - qc - qv
            fo = (1.0 - qc * fc - qv * fv) / rest_mass if rest_mass > 1e-9 else 1.0      # 도구 전체에 걸친 기술 주변확률이 유지되도록 나머지 도구의 변화기 가중치를 올린다
            it = norm(h.item)
            f = fv if it == "assaultvest" else (fc if it in CHOICE_ITEMS else fo)
            if f != 1.0:
                rest = {m: p * (f if self.data.moves[m]["category"] == "status" else 1.0) for m, p in rest.items()}
        out = {m: 1.0 for m in seen}
        if not slots or not rest:
            for m in rest:
                out[m] = 0.0
            return out
        # 수분배: pi_i = min(1, c * w_i), sum = slots
        items = sorted(rest.items(), key=lambda kv: -kv[1])
        total = sum(rest.values())
        if total <= 0:
            return {**out, **{m: 0.0 for m in rest}}
        capped, left = 0, float(slots)
        w_left = total
        for m, w in items:
            c = left / w_left if w_left > 0 else 0.0
            if c * w >= 1.0 and capped < slots:
                out[m] = 1.0
                left -= 1.0
                w_left -= w
                capped += 1
            else:
                break
        c = left / w_left if w_left > 0 else 0.0
        for m, w in items:
            if m not in out:
                out[m] = min(1.0, c * w)
        return out

    def marginal(self, what):
        d = {}
        for h in self.hyps:
            k = {"ability": h.ability, "item": h.item}.get(what)
            if what == "spread":
                k = (h.nature, tuple(sorted(h.sp.items())))
            d[k] = d.get(k, 0.0) + h.w
        return dict(sorted(d.items(), key=lambda kv: -kv[1]))

    def summary(self, top=3):
        mp = sorted(self._move_probs().items(), key=lambda kv: -kv[1])[:6]
        return dict(ability=list(self.marginal("ability").items())[:top], item=list(self.marginal("item").items())[:top],
                    spread=list(self.marginal("spread").items())[:top], moves=mp)

    def sample_set(self, rng: random.Random):
        """사후분포에서 세트 하나를 뽑는다 (엔진의 상대 팀 구성에 사용)"""
        x = rng.random()
        h = self.hyps[-1]
        for hh in self.hyps:
            x -= hh.w
            if x <= 0:
                h = hh
                break
        probs = self._move_probs(h)
        chosen = [m for m in self.seen_moves]
        need = 4 - len(chosen)
        cand = [(m, p) for m, p in probs.items() if m not in chosen and p > 0]
        if self.legacy:
            pool = dict(cand)
            while len(chosen) < 4 and pool:
                tot = sum(pool.values())
                y = rng.random() * tot
                pick = None
                for m, p in pool.items():
                    y -= p
                    if y <= 0:
                        pick = m
                        break
                pick = pick or next(iter(pool))
                chosen.append(pick)
                pool.pop(pick)
        elif need > 0 and cand:
            if len(cand) <= need:
                chosen += [m for m, _ in cand]
            else:
                rng.shuffle(cand)                        # 체계적 표본추출(Madow): 각 기술이 정확히 포함 확률 p 로 뽑힌다
                u, cum, picked = rng.random(), 0.0, []
                for m, p in cand:
                    lo, hi = cum, cum + p
                    cum = hi
                    k = math.ceil(lo - u)                # u + k 가 (lo, hi] 안에 있으면 선택
                    if lo < u + k <= hi or (k == 0 and lo < u <= hi):
                        picked.append(m)
                chosen += picked[:need]
                if len(chosen) < 4:                      # 합이 칸 수에 못 미치면 남은 후보 중 가중 추첨으로 채운다
                    pool = {m: p for m, p in cand if m not in chosen}
                    while len(chosen) < 4 and pool:
                        tot = sum(pool.values())
                        y = rng.random() * tot
                        pick = None
                        for m, p in pool.items():
                            y -= p
                            if y <= 0:
                                pick = m
                                break
                        pick = pick or next(iter(pool))
                        chosen.append(pick)
                        pool.pop(pick)
        return dict(sid=self.sid, ability=h.ability, item=h.item, nature=h.nature, sp=dict(h.sp), moves=chosen)


# ───────────────────────── 엔진 로그 → 관측 ─────────────────────────
import re

_DMG = re.compile(r"^  (.+) -(\d+) \((\d+)/(\d+)\)$")
_MOVE = re.compile(r"^\[(\d)\] (.+): (.+)$")
_AMBIGUOUS_PRIORITY = {"prankster", "galewings", "quickdraw", "stall"}


def parse_turn(lines):
    """한 턴의 엔진 로그에서 [[행동자, 기술명, [(대상HP후, 최대HP, 데미지), ...]], ...] (행동 순서)"""
    ev = []
    for ln in lines:
        m = _MOVE.match(ln)
        if m and "등장" not in ln:
            ev.append([int(m.group(1)), m.group(3), []])
            continue
        d = _DMG.match(ln)
        if d and ev:
            ev[-1][2].append((int(d.group(3)), int(d.group(4)), int(d.group(2))))
    return ev


def snapshot(eng, st, me=0):
    """한 턴을 진행하기 직전에 찍어 두는 '내 쪽에서 보이는 정보'"""
    A, D = st.sides[me].mon, st.sides[1 - me].mon
    return dict(me=me, our_spec=eng.spec_of(A), our_ability=A.ability, our_item=A.item, our_speed=eng.speed_of(st, me),
                opp_frac=D.hp / D.maxhp, opp_boosts=dict(D.boosts), opp_status=D.status,
                field_on_opp=eng.field_for(st, 1 - me), field_on_me=eng.field_for(st, me),
                opp_tailwind=st.sides[1 - me].screens.get("tailwind", 0) > 0, trick_room=bool(st.trick_room),
                opp_active=st.sides[1 - me].active)


def feed_events(model, data, events, opp_side, opp_is_model_active, weather_before=None, terrain_before=None):
    """ObsEngine 의 사건 목록에서 상대 쪽 공개 정보(특성/도구 발동, 도구 소모, 등장 시 발동 여부)를 반영한다"""
    if not events:
        return
    last_in = max((k for k, e in enumerate(events) if e[0] == "switch_in" and e[1] == opp_side), default=None)
    for e in events:
        if e[0] == "trigger" and e[1] == opp_side:
            kind, name = e[2].split(":", 1)
            (model.observe_ability if kind == "ability" else model.observe_item)(name)
        elif e[0] == "item" and e[1] == opp_side:
            model.observe_item(e[2])
    if last_in is not None and opp_is_model_active:
        trig = []
        for e in events[last_in + 1:]:
            if e[0] == "act":
                break
            if e[0] == "trigger" and e[1] == opp_side and e[2].startswith("ability:"):
                trig.append(e[2].split(":", 1)[1])
        model.observe_switch_in(trig, weather_before, terrain_before)


def feed_turn(model, data, snap, log_lines, weather=None, terrain=None):
    """한 턴의 로그에서 공개된 정보(상대 기술, 데미지, 행동 순서)를 모델에 반영한다.
    상대는 모델이 담당하는 포켓몬이 계속 나와 있는 경우만 처리한다"""
    me = snap["me"]
    ev = parse_turn(log_lines)
    for side, mname, dmgs in ev:
        key = norm(mname)
        if key not in data.moves:
            continue
        if side == 1 - me:
            model.note_move(key)
            if len(dmgs) == 1:
                model.observe_damage_taken(snap["our_spec"], key, dmgs[0][2], snap["field_on_me"])
        elif dmgs and len(dmgs) == 1:
            h, M, _ = dmgs[0]
            model.observe_damage_dealt(snap["our_spec"], key, snap["opp_frac"], 100.0 * h / M, snap["field_on_opp"])
    used = [(s, norm(m)) for s, m, _ in ev if norm(m) in data.moves]
    if len(used) == 2 and used[0][0] != used[1][0] and not snap["trick_room"]:
        ma, mb = data.moves[used[0][1]], data.moves[used[1][1]]
        ab = model.marginal("ability")
        amb_opp = any(norm(a) in _AMBIGUOUS_PRIORITY and w > 0.02 for a, w in ab.items())
        if ma["priority"] == mb["priority"] and norm(snap["our_ability"]) not in _AMBIGUOUS_PRIORITY and not amb_opp \
                and "quickclaw" not in (norm(snap["our_item"]),) and not any(norm(i) == "quickclaw" and w > 0.02 for i, w in model.marginal("item").items()):
            model.observe_speed(snap["our_speed"], opp_first=(used[0][0] == 1 - me), field=Field(weather, terrain),
                                tailwind=snap["opp_tailwind"], status=snap["opp_status"], boosts=snap["opp_boosts"])
