"""배틀 세션: 엔진 상태 + 턴 진행 + 행동별 승률 분석.
- 턴 도중 추가 선택(유턴/레드카드/기절 후 교체 등)은 엔진의 switch_policy 콜백으로 들어온다.
  사람 쪽이면 미리 받은 선택 목록(choices)에서 꺼내고, 없으면 NeedChoice 를 던져 중단한다.
  그 턴은 같은 난수 시드로 처음부터 다시 돌리므로(상태는 복제본에서 진행) 선택을 하나씩 늘려 가며 재시도해도 결과가 같다."""
import os
import random
import re
import threading
import uuid

from ai.gamedata import norm
from ai.observe import ObsEngine
from ai.policy import make_switch_policy
from ai.search import candidate_actions, solve_zero_sum
from gui.narrate import Narrator
from ai.search_value import ValueEvaluator, payoff_matrix_value

CKPT = os.environ.get("VALUE_CKPT", "data/value_v3b/value_net.pt")


WX_KO = {"sun": "쾌청", "rain": "비", "sand": "모래바람", "snow": "설경", "hail": "싸라기눈"}
TERRAIN_KO = {"electric": "일렉트릭필드", "grassy": "그래스필드", "misty": "미스트필드", "psychic": "사이코필드"}
SCREEN_KO = {"reflect": "리플렉터", "light_screen": "빛의장막", "aurora_veil": "오로라베일", "tailwind": "순풍", "safeguard": "신비의부적"}
HAZARD_KO = {"stealthrock": "스텔스록", "spikes": "압정뿌리기", "toxicspikes": "독압정", "stickyweb": "끈적끈적네트"}
STAT_KO = {"atk": "공격", "def": "방어", "spa": "특공", "spd": "특방", "spe": "스피드", "acc": "명중", "eva": "회피"}
# 상태(vol) 키 -> (표시, 종류) 종류: bad=걸린 쪽에 불리 / good=유리 / neu=중립
VOL_KO = {"confusion": ("혼란", "bad"), "leechseed": ("씨뿌리기", "bad"), "torment": ("트집", "bad"), "curse": ("저주", "bad"), "octolock": ("문어꼼짝", "bad"),
          "trapped": ("교체불가", "bad"), "noretreat": ("배수의진", "neu"), "imprison": ("봉인", "good"), "focusenergy": ("급소 UP(기합)", "good"),
          "smackdown": ("떨어뜨림", "bad"), "roost": ("날개쉬기(비행 소실)", "neu"), "protecting": ("방어 중", "good"), "enduring": ("버티기", "good"),
          "destinybond": ("길동무", "good"), "flinch": ("풀죽음", "bad"), "protean": ("변환자재 사용", "neu"), "flashfire": ("불꽃 흡수", "good"),
          "glaiverush": ("글레이브러시(피격 2배)", "bad"), "beakblast": ("부리캐논 대기", "neu"), "ingrain": ("뿌리박기", "neu"), "aquaring": ("아쿠아링", "good"),
          "substitute": ("대타", "good"), "busted": ("변장 깨짐", "neu"), "spikyshield": ("니들가드", "good"), "banefulbunker": ("베인풀벙커", "good"),
          "burningbulwark": ("화염의방패", "good"), "kingsshield": ("킹실드", "good"), "silktrap": ("실트랩", "good"), "obstruct": ("블로킹", "good"),
          "quickguard": ("퀵가드", "good"), "wideguard": ("와이드가드", "good"), "bindband": ("조임밴드", "bad"), "magnetrise": ("전자부유", "good")}


def mon_tags(m, mko):
    """한 포켓몬의 상태 배지 [(글, 종류)]: 능력치 단계 제외(따로 표시), 상태이상/휘발성 상태/남은 턴 카운터"""
    t = []
    for k, v in sorted(m.boosts.items()):
        if v:
            t.append((f"{STAT_KO.get(k, k)} {'+' if v > 0 else ''}{v}", "good" if v > 0 else "bad", "rank"))
    mv = lambda k: mko.get(norm(k), k)
    def add(txt, kind="neu"):
        t.append((txt, kind, "state"))
    if m.taunt: add(f"도발 {m.taunt}턴", "bad")
    if m.encore: add(f"앙코르 {m.encore}턴" + (f" ({mv(m.encore_move)})" if m.encore_move else ""), "bad")
    if m.disabled: add(f"기술봉인 {mv(m.disabled)} {m.disable_n}턴", "bad")
    if m.perish: add(f"멸망의노래 {m.perish}", "bad")
    if m.yawn: add("하품(다음 턴 졸음)", "bad")
    if m.healblock: add(f"힐블록 {m.healblock}턴", "bad")
    if m.confusion: add(f"혼란 {m.confusion}턴", "bad")
    if m.trap: add(f"속박 {m.trap}턴", "bad")
    if m.sub: add(f"대타 HP {m.sub}", "good")
    if m.magnet: add(f"전자부유 {m.magnet}턴", "good")
    if m.stockpile: add(f"비축 {m.stockpile}단계", "good")
    if m.charged: add("충전", "good")
    if m.uproar: add(f"소란 {m.uproar}턴", "neu")
    if m.throat: add(f"지옥찌르기(소리기술 봉인) {m.throat}턴", "bad")
    if m.syrup_n: add(f"물엿 {m.syrup_n}턴 (스피드 하락)", "bad")
    if m.charge: add("충전 중: " + mv(m.charge), "neu")
    if m.semi: add("공중/지중 등 이동 중", "neu")
    if m.recharge: add("반동으로 쉼", "bad")
    if m.rampage: add("난동 중", "neu")
    if m.locked: add(f"기술 고정: {mv(m.locked)}", "neu")
    if m.status == "tox" and m.tox: add(f"맹독 누적 {m.tox}", "bad")
    if m.status == "slp" and m.sleep: add(f"수면 (최대 {m.sleep}턴 남음)", "bad")
    if m.hero: add("히어로폼", "good")
    for v in sorted(x for x in m.vol if isinstance(x, str)):
        ko, kind = VOL_KO.get(v, (v, "neu"))
        if v == "confusion" and m.confusion: continue
        if v == "substitute" and m.sub: continue
        add(ko, kind)
    return [dict(text=a, kind=b, group=c) for a, b, c in t]


def side_tags(S):
    t = []
    for k, v in S.hazards.items():
        if v: t.append(dict(text=HAZARD_KO.get(k, k) + (f" x{v}" if v > 1 else ""), kind="hazard"))
    for k, v in S.screens.items():
        if v: t.append(dict(text=f"{SCREEN_KO.get(k, k)} {v}턴", kind="screen"))
    if S.wish: t.append(dict(text=f"희망사항 {S.wish[0]}턴 후 +{S.wish[1]}", kind="screen"))
    if S.heal_next: t.append(dict(text={"healingwish": "치유소원", "lunardance": "초승달춤"}.get(S.heal_next, S.heal_next) + " 대기", kind="screen"))
    if S.future: t.append(dict(text=f"미래공격 {S.future.get('left', '?')}턴 후", kind="hazard"))
    return t


def field_tags(st):
    t = []
    if st.weather: t.append(dict(text=f"{WX_KO.get(st.weather, st.weather)} {st.weather_turns}턴", kind="weather"))
    if st.terrain: t.append(dict(text=f"{TERRAIN_KO.get(st.terrain, st.terrain)} {st.terrain_turns}턴", kind="weather"))
    for v, name in ((st.trick_room, "트릭룸"), (st.magic_room, "매직룸"), (st.wonder_room, "원더룸"), (st.gravity, "중력"), (st.fairy_lock, "페어리락")):
        if v: t.append(dict(text=f"{name} {v}턴", kind="room"))
    return t


class NeedChoice(BaseException):
    def __init__(self, side, options, hint):
        self.side, self.options, self.hint = side, options, hint


class Backend:
    """엔진/가치망을 한 번만 올려 두고 세션이 공유한다"""

    def __init__(self, data, dex):
        self.data, self.dex = data, dex
        self.pko = dict(dex["ko_all"])
        self.mko = dex["move_ko"]
        self.ako = dex["abil_ko"]
        self.eng = ObsEngine(data)
        self.ev = None
        self.lock = threading.Lock()          # 엔진 인스턴스에 턴 진행 중 임시 필드가 있어 동시에 한 판만 계산한다
        if os.path.exists(CKPT):
            self.ev = ValueEvaluator(self.eng, CKPT, os.path.join(os.path.dirname(CKPT), "vocab.json"), device="cpu")


def act_label(b, st, side, a):
    eng, bm = b.eng, st.sides[side].mon
    k, x = a
    if k in ("m", "M"):
        key = norm(bm.spec["moves"][x])
        return ("메가진화+" if k == "M" else "") + b.mko.get(key, eng.data.moves[key]["name"])
    if k == "s":
        t = st.sides[side].team[x]
        return "교체 → " + b.pko.get(t.sid, t.name)
    if k == "t":
        return "발버둥"
    return "반동으로 쉼"


class Session:
    def __init__(self, backend, teams, picks, modes, names, seed=None):
        self.b, self.eng = backend, backend.eng
        self.id = uuid.uuid4().hex[:10]
        self.base = seed if seed is not None else random.randrange(10 ** 9)
        self.modes = modes
        self.names = names
        full = [[dict(t[i]) for i in p] for t, p in zip(teams, picks)]
        rng = random.Random(self.base)
        self.st = self.eng.new_state(full[0], full[1], log=True, rng=rng)
        self.log = list(self.st.log)
        self.st.log = []
        self.msgs = list(getattr(self.st, "msgs", None) or [])
        self.st.msgs = []
        self.viewer = next((i for i in (0, 1) if modes[i] == "human"), 0)
        self.narr = Narrator(backend, names)
        self.turn_logs = []                    # [(턴, [줄])]
        self.cache = {}

    def localize(self, lines):
        """진행 기록의 영문 이름(포켓몬/기술)을 한글로, [0]/[1] 을 플레이어 이름으로 바꾼다"""
        names = {}
        for S in self.st.sides:
            for m in S.team:
                names[m.name] = self.b.pko.get(m.sid, m.name)
                for mv in m.spec["moves"]:
                    d = self.eng.data.moves.get(norm(mv))
                    if d:
                        names[d["name"]] = self.b.mko.get(norm(mv), d["name"])
        names = {k: v for k, v in names.items() if k and k != v}
        rx = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(k) for k in sorted(names, key=len, reverse=True)) + r")(?![A-Za-z0-9])") if names else None
        out = []
        for ln in lines:
            ln = re.sub(r"^\[(\d)\]", lambda m: f"[{self.names[int(m.group(1))]}]", ln)
            if rx:
                ln = rx.sub(lambda m: names[m.group(1)], ln)
            out.append(ln)
        return out

    # ── 직렬화 ──
    def view(self, partial=None):
        st, eng = self.st, self.eng
        sides = []
        for i in (0, 1):
            S = st.sides[i]
            team = []
            for j, m in enumerate(S.team):
                team.append(dict(idx=j, sid=m.sid, name=self.b.pko.get(m.sid, m.name), hp=m.hp, maxhp=m.maxhp, status=m.status, item=m.item, ability=self.b.ako.get(norm(m.ability), m.ability),
                                 active=(j == S.active), alive=m.alive, types=eng.types_of(m),
                                 boosts={k: v for k, v in m.boosts.items() if v}, tags=mon_tags(m, self.b.mko),
                                 moves=[dict(key=norm(mv), name=self.b.mko.get(norm(mv), eng.data.moves[norm(mv)]["name"]), type=eng.data.moves[norm(mv)]["type"],
                                             cat=eng.data.moves[norm(mv)]["category"], pp=(m.pp[k] if k < len(m.pp) else None))
                                        for k, mv in enumerate(m.spec["moves"])]))
            acts = []
            if st.winner is None:
                for a in eng.legal_actions(st, i):
                    acts.append(dict(act=list(a), label=act_label(self.b, st, i, a)))
            sides.append(dict(team=team, acts=acts, tags=side_tags(S),
                              mega_used=S.mega_used, mode=self.modes[i], name=self.names[i]))
        return dict(id=self.id, turn=st.turn, winner=st.winner, sides=sides,
                    field=dict(tags=field_tags(st)),
                    log=self.narr.render(self.msgs + list(partial or []), self.viewer, self.st)[-600:])

    # ── 분석(행동별 승률) ──
    def analyze(self, me, samples=4):
        """me 시점에서 합법 행동 전부의 승률. 상대는 후보 행동 중 내시 균형 혼합으로 움직인다고 보고,
        내 행동 i 의 값 = 그 혼합에 대한 평균. (두 파티가 모두 알려진 완전 정보 가정, 가치망 1턴 탐색)"""
        key = (self.st.turn, me)
        if key in self.cache:
            return self.cache[key]
        if self.b.ev is None:
            raise RuntimeError("가치망 체크포인트가 없어 승률을 계산할 수 없다: " + CKPT)
        eng, st, opp = self.eng, self.st, 1 - me
        with self.b.lock:
            my_acts = eng.legal_actions(st, me)
            opp_acts = candidate_actions(eng, st, opp, 2)
            rng = random.Random(self.base * 7 + st.turn)
            M = payoff_matrix_value(eng, self.b.ev, st, me, my_acts, opp_acts, samples, rng, make_switch_policy(eng, rng))
        x, v = solve_zero_sum(M)
        y, _ = solve_zero_sum(1.0 - M.T)
        rows = []
        for i, a in enumerate(my_acts):
            rows.append(dict(act=list(a), label=act_label(self.b, st, me, a), win=float(M[i] @ y), worst=float(M[i].min()), nash=float(x[i])))
        out = dict(me=me, value=float(v), actions=rows)
        self.cache[key] = out
        return out

    def ai_action(self, me):
        a = self.analyze(me)
        best = max(a["actions"], key=lambda r: (r["nash"], r["win"]))
        return tuple(best["act"])

    # ── 턴 진행 ──
    def play_turn(self, acts, choices):
        """acts: [행동 | None, 행동 | None] (None 이면 AI 모드 쪽이 정한다). choices: 사람 쪽 턴 도중 선택(교체 번호) 목록.
        반환: view + (필요하면) need_choice"""
        eng, st = self.eng, self.st
        if st.winner is not None:
            return self.view()
        final = []
        for i in (0, 1):
            if acts[i] is None:
                if self.modes[i] != "ai":
                    raise ValueError(f"{i} 번 플레이어의 행동이 필요하다")
                final.append(self.ai_action(i))
            else:
                a = tuple(acts[i])
                if a not in eng.legal_actions(st, i):
                    raise ValueError(f"불가능한 행동: {a}")
                final.append(a)
        queue = list(choices or [])
        base_pol = make_switch_policy(eng, random.Random(0))

        def pol(s, side):
            if self.modes[side] == "ai":
                return base_pol(s, side)
            options = [j for j in s.sides[side].alive_idx() if j != s.sides[side].active or not s.sides[side].mon.alive]
            if queue:
                j = queue.pop(0)
                if j not in options:
                    raise ValueError(f"고를 수 없는 포켓몬: {j}")
                return j
            raise NeedChoice(side, [dict(idx=j, name=self.b.pko.get(s.sides[side].team[j].sid, s.sides[side].team[j].name), hp=s.sides[side].team[j].hp, maxhp=s.sides[side].team[j].maxhp) for j in options],
                             list(s.log[-3:]) if s.log else [])

        with self.b.lock:
            s = eng.clone(st)
            s.log = []
            s.msgs = []
            try:
                eng.step(s, [final[0], final[1]], random.Random(self.base * 31 + st.turn), pol)
            except NeedChoice as nc:
                v = self.view(partial=s.msgs)
                v["need_choice"] = dict(side=nc.side, options=nc.options, hint=[x for x in self.narr.render(s.msgs, self.viewer, s)], acts=[list(x) for x in final])
                return v
        self.log += s.log
        self.msgs += s.msgs
        self.turn_logs.append((s.turn, list(s.log)))
        s.log = []
        s.msgs = None
        self.st = s
        self.cache.clear()
        return self.view()


class Store:
    def __init__(self, backend):
        self.b, self.sessions = backend, {}

    def new(self, teams, picks, modes, names):
        s = Session(self.b, teams, picks, modes, names)
        self.sessions[s.id] = s
        return s
