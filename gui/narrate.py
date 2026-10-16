"""엔진의 구조화된 메시지(st.msgs)를 게임 속 한국어 문장으로 바꾼다.
문구 출처: Pokémon Showdown 의 한국어 텍스트(data/text/ko). gui/ko_dump.js 로 gui/ko_text.json 을 만들어 읽는다.
 - 기본 문구(default): 교체/쓰러짐/능력치/상태이상/상성/급소/날씨/필드 등
 - 기술·특성·도구별 문구: 함정 설치, 방어, 대타, 도구 회복 등
템플릿 표기 {POKEMON:topic} 의 topic/subject/object/conjunctive/directional 은 은·는 / 이·가 / 을·를 / 와·과 / 로·으로 조사를 받침에 맞춰 붙인다."""
import json
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
KO_JSON = os.path.join(HERE, "ko_text.json")
SD_DIR = os.path.join(HERE, "..", "showdown")

STAT_KO = {"hp": "HP", "atk": "공격", "def": "방어", "spa": "특수공격", "spd": "특수방어", "spe": "스피드", "accuracy": "명중률", "evasion": "회피율"}
WEATHER_ID = {"sun": "sunnyday", "rain": "raindance", "sand": "sandstorm", "snow": "snowscape", "hail": "hail"}
TERRAIN_ID = {"electric": "electricterrain", "grassy": "grassyterrain", "misty": "mistyterrain", "psychic": "psychicterrain"}
ROOM_ID = {"trick": "trickroom", "wonder": "wonderroom", "magic": "magicroom", "gravity": "gravity"}
FIELD_ID = {"reflect": "reflect", "light_screen": "lightscreen", "aurora_veil": "auroraveil", "tailwind": "tailwind", "safeguard": "safeguard",
            "stealthrock": "stealthrock", "spikes": "spikes", "toxicspikes": "toxicspikes", "stickyweb": "stickyweb"}
WHY_ID = {"disable": "disable", "imprison_gravity": "imprison", "focuspunch": "focuspunch", "throat": "throatchop", "taunt": "taunt", "healblock": "healblock"}
HP_WHY = {"모래바람": ("sandstorm", "damage"), "독": ("psn", "damage"), "맹독": ("psn", "damage"), "화상": ("brn", "damage"), "반동": ("recoil", "damage"),
          "크래시": ("crash", "damage"), "씨뿌리기": ("leechseed", "damage"), "저주": ("curse", "damage"), "압정": ("spikes", "damage"),
          "스텔스록": ("stealthrock", "damage"), "혼란": None}


def ensure_json():
    if not os.path.exists(KO_JSON):
        subprocess.run(["node", os.path.join(HERE, "ko_dump.js"), SD_DIR, KO_JSON], check=True)
    return json.load(open(KO_JSON, encoding="utf-8"))


def _final(word):
    """마지막 한글 글자의 받침: (있는지, ㄹ받침인지)"""
    for ch in reversed(word):
        if ch.isascii() and ch.isalpha():               # 영문 글자로 끝나면 읽는 소리 기준 (X 엑스 / Y 와이 / Z 제트 는 받침 없음, L/M/N/R 은 있음)
            return ch.upper() in "LMNR", ch.upper() == "L"
        if ch.isdigit():
            return ch in "013678", ch in "178"
        if "가" <= ch <= "힣":
            j = (ord(ch) - 0xAC00) % 28
            return j != 0, j == 8
    return False, False


JOSA = {"topic": ("은", "는"), "subject": ("이", "가"), "object": ("을", "를"), "conjunctive": ("과", "와"), "directional": ("으로", "로")}


def josa(word, kind):
    has, rieul = _final(word)
    a, b = JOSA[kind]
    if kind == "directional":
        return word + (b if (not has or rieul) else a)
    return word + (a if has else b)


class Narrator:
    def __init__(self, backend, names):
        self.T = ensure_json()
        self.b, self.names = backend, names
        self.ako = backend.dex["abil_ko"]
        self.iko = {i["key"]: i["ko"] for i in backend.dex["items"]}

    # ── 이름 ──
    def mon(self, sid, side, viewer, plain=False):
        n = self.b.pko.get(sid, sid)
        return n if (side == viewer or side is None or plain) else "상대 " + n

    def trainer(self, side, viewer):
        return "나" if side == viewer else "상대"

    def team(self, side, viewer):
        return self.T["default"]["default"].get("team", "우리 편") if side == viewer else self.T["default"]["default"].get("opposingTeam", "상대")

    def fill(self, tpl, **v):
        def sub(m):
            key, mod = m.group(1), m.group(2)
            val = v.get(key)
            if val is None:
                val = ""
            if mod is None and key in ("POKEMON", "NICKNAME") and m.end() < len(tpl) and tpl[m.end()] == " " and val != "":
                mod = "topic"                                 # 조사가 빠진 문구("{POKEMON} 방어 태세에...")는 은/는 을 붙인다
            return josa(str(val), mod) if mod in JOSA and val != "" else str(val)
        return re.sub(r"\{(\w+)(?::(\w+))?\}", sub, tpl)

    def default(self, key, grp="default"):
        return self.T["default"].get(grp, {}).get(key)

    def ability_name(self, en):
        return self.ako.get("".join(c for c in (en or "").lower() if c.isalnum()), en or "")

    def item_name(self, en):
        return self.iko.get("".join(c for c in (en or "").lower() if c.isalnum()), en or "")

    # ── 메시지 하나 -> [(문장, 종류)] ──
    def one(self, m, viewer, st):
        k, s, sid = m["k"], m.get("s"), m.get("sid")
        mon = self.mon(sid, s, viewer) if sid else ""
        D = lambda key, grp="default": self.default(key, grp)
        out = []

        def add(tpl, cls="", **kw):
            if tpl:
                base = dict(POKEMON=mon, NICKNAME=mon)
                base.update(kw)
                out.append((self.fill(tpl.strip(), **base).replace("**", "").replace("말았다!!", "말았다!"), cls))

        mvname = lambda key: self.b.mko.get(key, key)
        if k == "in":
            plain = self.mon(sid, s, viewer, plain=True)
            if m.get("drag"):
                add(D("drag"), FULLNAME=mon)
            elif s == viewer:
                add(D("switchInOwn"), FULLNAME=plain)
            else:
                add(D("switchIn"), TRAINER=self.trainer(s, viewer), FULLNAME=plain)
        elif k == "out":
            plain = self.mon(sid, s, viewer, plain=True)
            tpl = D("switchOutOwn") if s == viewer else D("switchOut")
            if s == viewer:
                tpl = tpl.replace("{NICKNAME} ", "{NICKNAME}, ")
            add(tpl, TRAINER=self.trainer(s, viewer), NICKNAME=plain, POKEMON=plain)
        elif k == "use":
            add(D("move"), MOVE=mvname(m["move"]))
        elif k == "faint":
            add(D("faint"))
        elif k == "hp":
            self._hp(m, mon, s, viewer, out, add)
        elif k == "boost":
            n = m["n"]
            key = ("boost" if n > 0 else "unboost") + ({1: "", 2: "2"}.get(abs(n), "3"))
            add(D(key), "boost" if n > 0 else "unboost", STAT=STAT_KO.get(m["stat"], m["stat"]))
        elif k == "nomore":
            add(D("boost0" if m["up"] else "unboost0"), STAT=STAT_KO.get(m["stat"], m["stat"]))
        elif k == "status":
            add(D("start", m["code"]))
        elif k == "cure":
            add(D("end", m["code"]))
        elif k == "wake":
            add(D("end", "slp"))
        elif k == "thaw":
            add(D("end", "frz"))
        elif k == "confuse":
            add(D("start", "confusion"))
        elif k == "cant":
            self._cant(m, mon, add, mvname)
        elif k == "crit":
            add(D("crit"), "crit")
        elif k == "eff":
            mod = m["mod"]
            add(D("extremelyEffective" if mod >= 2 else "superEffective") if mod > 0 else D("mostlyIneffective" if mod <= -2 else "resisted"))
        elif k == "hits":
            add(D("hitCount"), NUMBER=m["n"])
        elif k == "miss":
            add(D("missNoPokemon"), SOURCE=mon)
        elif k == "fail":
            add(D("fail"))
        elif k == "noeffect":
            add(D("immune"))
        elif k == "protected":
            add(self.T["moves"].get("protect", {}).get("block"))
        elif k == "psyterrain_block":
            add(D("block", "psychicterrain"))
        elif k == "sub_hit":
            add(self.T["moves"].get("substitute", {}).get("end" if m.get("broke") else "activate", "대타가 공격을 대신 받았다!"))
        elif k == "mega":
            info = self.b.eng.mega_rev.get("".join(c for c in m["to"].lower() if c.isalnum()))
            base_sid = info[0] if info else m["to"]
            nm = self.mon(base_sid, s, viewer)
            out.append((self.fill("{POKEMON:topic} " + josa(self.b.pko.get(m["to"], m["to"]), "directional") + " 메가진화했다!", POKEMON=nm), "mega"))
        elif k == "transform":
            add(D("transform"))
        elif k == "weather":
            add(D("start", WEATHER_ID.get(m["w"], m["w"])))
        elif k == "weather_end":
            add(D("end", WEATHER_ID.get(m["w"], m["w"])))
        elif k == "terrain":
            add(D("start", TERRAIN_ID.get(m["t"], m["t"])))
        elif k == "terrain_end":
            add(D("end", TERRAIN_ID.get(m["t"], m["t"])))
        elif k == "room":
            who = self.mon(self._last_user(st), self._last_side, viewer) if getattr(self, "_last_side", None) is not None else ""
            add(D("start" if m["on"] else "end", ROOM_ID[m["r"]]), POKEMON=who)
        elif k in ("field_set", "field_end"):
            mid = FIELD_ID.get(m["code"], m["code"])
            tpl = self.T["moves"].get(mid, {}).get("start" if k == "field_set" else "end")
            add(tpl, TEAM=self.team(s, viewer))
        elif k == "trigger":
            self._trigger(m, mon, add)
        elif k == "trace":
            add(self.T["abilities"].get("trace", {}).get("changeAbility"), SOURCE="상대", ABILITY=self.ability_name(m["ability"]))
        elif k == "status_ok":
            user = self.mon(self._last_sid, m["user"], viewer) if m["user"] is not None else ""
            add(self.T["moves"].get(m["move"], {}).get("start"), SOURCE=user, TARGET=mon)
        elif k == "charge":
            add(self.T["moves"].get(m["move"], {}).get("prepare"))
        elif k == "future_set":
            add(self.T["moves"].get(m["move"], {}).get("start"))
        elif k == "future_hit":
            add(self.T["moves"].get(m.get("move") or "futuresight", {}).get("activate"), TARGET=mon)
        return out

    def _hp(self, m, mon, s, viewer, out, add):
        why, d = m.get("why") or "", m["delta"]
        T = self.T
        if why.startswith("item:") or why.startswith("ability:"):
            grp = "items" if why.startswith("item:") else "abilities"
            ident = "".join(c for c in why.split(":", 1)[1].lower() if c.isalnum())
            e = T[grp].get(ident, {})
            tpl = e.get("heal" if d > 0 else "damage")
            if tpl:
                add(tpl)
        elif why in HP_WHY and HP_WHY[why]:
            grp, key = HP_WHY[why]
            tpl = T["default"].get(grp, {}).get(key) or T["moves"].get(grp, {}).get(key)
            add(tpl)
        elif why == "생명의구슬":
            add(T["items"].get("lifeorb", {}).get("damage"))
        elif why == "검은진흙":
            add(T["items"].get("blacksludge", {}).get("heal" if d > 0 else "damage"))
        elif why == "흡수" and d > 0:
            foe = self.mon(self._cur.get(1 - s), 1 - s, viewer) if self._cur.get(1 - s) else "상대"
            add(T["default"].get("drain", {}).get("heal"), SOURCE=foe)
        elif why == "그래스필드":
            add(T["default"].get("grassyterrain", {}).get("heal"))
        elif why == "회복" or why == "치유파동":
            add(T["default"]["default"].get("heal"))
        elif why == "희망사항":
            add(T["moves"].get("wish", {}).get("heal"))
        elif why in ("aquaring", "ingrain"):
            add(T["moves"].get(why, {}).get("heal") or T["default"]["default"].get("heal"))
        elif why == "멸망의노래":
            return
        out.append((f"{mon}  HP {m['hp']}/{m['maxhp']}  ({d:+d})", "hpl"))

    def _cant(self, m, mon, add, mvname):
        why, T = m["why"], self.T
        if why == "sleep":
            add(T["default"]["slp"]["cant"])
        elif why == "freeze":
            add(T["default"]["frz"]["cant"])
        elif why == "paralysis":
            add(T["default"]["par"]["cant"])
        elif why == "flinch":
            add(T["default"]["flinch"]["cant"])
        elif why == "confusion":
            add(T["default"]["confusion"]["activate"])
            add(T["default"]["confusion"]["damage"])
        elif why in WHY_ID:
            tpl = T["moves"].get(WHY_ID[why], {}).get("cant") or T["default"]["default"]["cant"]
            add(tpl, MOVE=mvname(m.get("move", "")))
        else:
            add(T["default"]["default"]["cant"], MOVE=mvname(m.get("move", "")))

    def _trigger(self, m, mon, add):
        grp, name = m["src"].split(":", 1)
        ident = "".join(c for c in name.lower() if c.isalnum())
        tbl = self.T["abilities" if grp == "ability" else "items"].get(ident, {})
        disp = self.ability_name(name) if grp == "ability" else self.item_name(name)
        kind = m.get("rk")
        for key in ("activate", "start", "block", "end"):           # 회복/피해 문구는 HP 변화 메시지가 이미 낸다
            if key in tbl:
                if grp == "ability":
                    add(self.T["default"]["default"]["abilityActivation"], ABILITY=disp)
                add(tbl[key], ABILITY=disp, ITEM=disp)
                return
        if grp == "ability":
            add(self.T["default"]["default"]["abilityActivation"], ABILITY=disp)
        elif kind not in ("heal_frac", "damage_frac", "heal", "damage") and not any(k in tbl for k in ("heal", "damage")):
            add("{POKEMON:topic} " + josa(disp, "directional") + " 효과를 발휘했다!")

    # ── 전체 ──
    @staticmethod
    def order(msgs):
        """게임 속 표시 순서에 맞게 다듬는다: 행동 불가는 '기술 사용' 문구를 대신하고, 눈뜸/해동은 기술 문구보다 먼저, 쓰러짐은 급소/상성 문구 뒤"""
        out = []
        for m in msgs:
            if m["k"] == "cant" and out and out[-1]["k"] == "use" and out[-1].get("s") == m.get("s") and not out[-1].get("via"):
                out.pop()
            elif m["k"] in ("wake", "thaw") and out and out[-1]["k"] == "use" and out[-1].get("s") == m.get("s"):
                out.insert(len(out) - 1, m)
                continue
            out.append(m)
        i = 0
        merged = []
        seq = out
        while i < len(seq):
            m = seq[i]
            if m["k"] == "faint":
                j = i + 1
                tail = []
                while j < len(seq) and seq[j]["k"] in ("crit", "eff", "hits") and seq[j].get("s") == m.get("s"):
                    tail.append(seq[j])
                    j += 1
                merged += tail + [m]
                i = j
            else:
                merged.append(m)
                i += 1
        return merged

    def render(self, msgs, viewer, st):
        msgs = self.order(msgs)
        lines = []
        self._last_side = None
        self._cur = {}
        for m in msgs:
            if m.get("sid") and m.get("s") is not None:
                self._cur[m["s"]] = m["sid"]
            if m["k"] == "use":
                self._last_side, self._last_sid = m.get("s"), m.get("sid")
            if m.get("turn") is not None and (not lines or lines[-1].get("turn") != m["turn"]):
                lines.append(dict(text=f"── 턴 {m['turn']} ──" if m["turn"] > 0 else "── 배틀 시작 ──", cls="turn", turn=m["turn"], head=True))
            for text, cls in self.one(m, viewer, st):
                lines.append(dict(text=text, cls=cls, turn=m["turn"]))
        return lines

    def _last_user(self, st):
        return getattr(self, "_last_sid", None)
