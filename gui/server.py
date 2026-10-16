"""로컬 GUI 서버: python -m gui.server  ->  http://127.0.0.1:8765
파티 입력/프리셋/선출/배틀(행동별 승률, 턴 도중 선택) API + 정적 화면(gui/static/index.html)"""
import base64
import json
import os
import random
import re
import zlib

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ai.gamedata import GameData, connect, norm
from ai.meta import Meta
from gui.dex import SP_KEYS, build_dex
from gui.session import Backend, Store

HERE = os.path.dirname(os.path.abspath(__file__))
PRESETS = os.path.join(HERE, "presets")
os.makedirs(PRESETS, exist_ok=True)

conn = connect()
DATA = GameData(conn)
DEX = build_dex(DATA, conn)
META = Meta(conn, DATA, int(os.environ.get("META_SNAP", "33")))
BACKEND = Backend(DATA, DEX)
STORE = Store(BACKEND)
MONS = {m["sid"]: m for m in DEX["mons"]}
MEGAS = {m["sid"]: m for m in DEX["megas"]}
ITEMS = {i["key"] for i in DEX["items"]}
NATURES = {n["en"] for n in DEX["natures"]}
app = FastAPI()


def check_member(spec):
    """파티원 하나의 규칙 점검 -> 경고 문자열 목록 (챔피언스: 레벨 50, SP 합 66 / 능력치당 32, 기술 4개)"""
    w = []
    p = MONS.get(spec.get("sid"))
    if not p:
        return ["알 수 없는 포켓몬"]
    sp = spec.get("sp") or {}
    if sum(sp.get(k, 0) for k in SP_KEYS) > 66:
        w.append("SP 합이 66을 넘는다")
    if any(sp.get(k, 0) > 32 or sp.get(k, 0) < 0 for k in SP_KEYS):
        w.append("능력치 하나의 SP 는 0~32")
    mv = [norm(m) for m in spec.get("moves") or []]
    if not 1 <= len(mv) <= 4:
        w.append("기술은 1~4개")
    if len(set(mv)) != len(mv):
        w.append("같은 기술이 겹친다")
    for m in mv:
        if m not in DATA.moves:
            w.append(f"챔피언스에 없는 기술: {m}")
        elif m not in p["learn"]:
            w.append(f"습득 목록에 없는 기술: {DEX['move_ko'].get(m, m)}")
    ab = [a["en"] for a in p["abilities"]]
    if spec.get("ability") and spec["ability"] not in ab:
        w.append("이 포켓몬의 특성이 아니다")
    if spec.get("item") and norm(spec["item"]) not in ITEMS:
        w.append("챔피언스에 없는 도구")
    if spec.get("nature") and spec["nature"] not in NATURES:
        w.append("알 수 없는 성격")
    return w


def clean(spec):
    sp = {k: int((spec.get("sp") or {}).get(k, 0)) for k in SP_KEYS}
    return dict(sid=spec["sid"], ability=spec.get("ability") or next(iter(DATA.pokemon[spec["sid"]]["abilities"].values()), ""),
                item=spec.get("item") or "", nature=spec.get("nature") or "Serious", sp=sp, moves=[m for m in spec.get("moves") or []])


# ── 도감 / 메타 ──
@app.get("/api/dex")
def dex():
    return DEX


def _base(sid):
    info = BACKEND.eng.mega_rev.get(norm(sid))
    return info[0] if info and info[0] in DATA.pokemon else sid


@app.get("/api/meta_set/{sid}")
def meta_set(sid: str, random_: int = 0):
    """메타 사용률 기반 세트. 메가 종으로 집계된 통계는 메가 전 종(+메가스톤)으로 바꿔 돌려준다"""
    if sid not in DATA.pokemon:
        raise HTTPException(404, "없는 포켓몬")
    rng = random.Random() if random_ else None
    mg = MEGAS.get(sid)
    if mg:                                              # 메가 종을 검색해 고른 경우: 메가 전 종 + 메가스톤, 기술/성격은 그 메가 종의 메타 분포
        try:
            spec = META.build_set(sid, rng) if META.spreads.get(sid) else None
        except Exception:
            spec = None
        if spec is None:
            spec = dict(sid=sid, ability="", item="", nature="Serious", sp={}, moves=[])
        return dict(spec, sid=mg["base"], item=mg["item"], ability=BACKEND.eng.base_ability(mg["base"]))
    cands = [k for k in META.usage if _base(k) == sid and META.spreads.get(k)]
    try:
        if cands:
            if rng:
                pick = META._pick([(k, META.usage[k]) for k in cands], rng)
            else:
                pick = max(cands, key=lambda k: META.usage[k])
            return BACKEND.eng.demega_spec(META.build_set(pick, rng))
    except Exception:
        pass
    p = DATA.pokemon[sid]
    return dict(sid=sid, ability=next(iter(p["abilities"].values()), ""), item="", nature="Serious", sp={}, moves=[])


def _spec_of(form, spread, abil, item, moves):
    nature, sp = spread
    spec = dict(sid=form, ability=abil, item=item, nature=nature, sp=dict(sp), moves=list(moves))
    mg = MEGAS.get(form)
    if mg:                                              # 메가 종 통계 -> 메가 전 종 + 메가스톤
        spec = dict(spec, sid=mg["base"], item=mg["item"], ability=BACKEND.eng.base_ability(mg["base"]))
    return spec


@app.get("/api/meta_sets/{sid}")
def meta_sets(sid: str):
    """최신 메타 세트 후보 (최대 3개). 통계는 항목별 주변분포뿐이라 '조합'은 만들어 낸다:
    1) 사용률 가장 높은 형태(메가/기본)의 최빈 세트, 2) 다른 형태가 있으면 그 형태의 최빈 세트,
    3) 나머지는 같은 형태의 2·3위 노력치 분배(+2·3위 도구, 4번째 기술을 다음 순위로 교체)."""
    if sid not in DATA.pokemon:
        raise HTTPException(404, "없는 포켓몬")
    forms = sorted([k for k in META.usage if _base(k) == sid and META.spreads.get(k)], key=lambda k: -META.usage[k])
    if not forms:
        return []
    def ranked(form):
        sp = sorted(META.spreads[form], key=lambda x: -x[1])
        ab = sorted(META.abilities.get(form, []), key=lambda x: -x[1]) or [(next(iter(DATA.pokemon[form]["abilities"].values()), ""), 1.0)]
        it = sorted(META.items.get(form, []), key=lambda x: -x[1]) or [("", 1.0)]
        mv = sorted([(m, p) for m, p in META.moves.get(form, []) if m in DATA.moves], key=lambda x: -x[1])
        return sp, ab, it, mv
    def build(form, k):
        sp, ab, it, mv = ranked(form)
        if k >= len(sp):
            return None
        names = [m for m, _ in mv]
        moves = names[:4]
        if k and len(names) > 3 + k and mv[3 + k][1] >= 0.1:
            moves = names[:3] + [names[3 + k]]
        item = it[k][0] if k < len(it) and it[k][1] >= 0.08 else it[0][0]
        abil = ab[k][0] if k < len(ab) and ab[k][1] >= 0.2 else ab[0][0]
        return _spec_of(form, sp[k][0], abil, item, moves)
    out, seen = [], set()
    order = [(forms[0], 0)] + [(f, 0) for f in forms[1:]] + [(forms[0], 1), (forms[0], 2)]
    for form, k in order:
        spec = build(form, k)
        if spec is None:
            continue
        key = (spec["sid"], spec["item"], spec["nature"], tuple(sorted(spec["sp"].items())), tuple(spec["moves"]))
        if key in seen:
            continue
        seen.add(key)
        spec["usage"] = round(META.usage[form], 1)
        out.append(spec)
        if len(out) == 3:
            break
    return out


@app.get("/api/meta_top")
def meta_top(n: int = 30):
    out = []
    for k in META.top_species(n * 2):
        b = _base(k)
        if b not in out and b in MONS:
            out.append(b)
    return out[:n]


class Team(BaseModel):
    team: list


@app.post("/api/check")
def check(t: Team):
    return [check_member(m) for m in t.team]


# ── 프리셋 ──
PREFIX = "PCP1-"


@app.post("/api/preset/encode")
def preset_encode(t: Team):
    raw = json.dumps([clean(m) for m in t.team], ensure_ascii=False, separators=(",", ":")).encode()
    return dict(code=PREFIX + base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode().rstrip("="))


class Code(BaseModel):
    code: str


@app.post("/api/preset/decode")
def preset_decode(c: Code):
    s = c.code.strip()
    if not s.startswith(PREFIX):
        raise HTTPException(400, "프리셋 코드 형식이 아니다")
    b = s[len(PREFIX):]
    try:
        team = json.loads(zlib.decompress(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4))))
        return dict(team=[clean(m) for m in team])
    except Exception:
        raise HTTPException(400, "프리셋 코드를 읽을 수 없다")


def _pname(n):
    n = re.sub(r"[^0-9A-Za-z가-힣 _-]", "", n).strip()[:40]
    if not n:
        raise HTTPException(400, "이름이 비었다")
    return os.path.join(PRESETS, n + ".json")


class Named(BaseModel):
    name: str
    team: list = []


@app.get("/api/presets")
def presets():
    return sorted(f[:-5] for f in os.listdir(PRESETS) if f.endswith(".json"))


@app.post("/api/presets/save")
def preset_save(n: Named):
    json.dump([clean(m) for m in n.team], open(_pname(n.name), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return dict(ok=True)


@app.get("/api/presets/{name}")
def preset_load(name: str):
    p = _pname(name)
    if not os.path.exists(p):
        raise HTTPException(404, "없는 프리셋")
    return dict(team=json.load(open(p, encoding="utf-8")))


@app.delete("/api/presets/{name}")
def preset_del(name: str):
    p = _pname(name)
    if os.path.exists(p):
        os.remove(p)
    return dict(ok=True)


# ── 배틀 ──
class NewBattle(BaseModel):
    teams: list
    picks: list
    modes: list = ["human", "ai"]
    names: list = ["나", "상대"]


@app.post("/api/battle/new")
def battle_new(b: NewBattle):
    for side in (0, 1):
        if len(b.picks[side]) != 3 or len(set(b.picks[side])) != 3:
            raise HTTPException(400, "각 파티에서 서로 다른 3마리를 골라야 한다")
        for i in b.picks[side]:
            w = check_member(b.teams[side][i])
            bad = [x for x in w if "습득" not in x]
            if bad:
                raise HTTPException(400, f"{side + 1}번 파티 {i + 1}번째: " + ", ".join(bad))
    teams = [[clean(m) for m in t] for t in b.teams]
    s = STORE.new(teams, b.picks, b.modes, b.names)
    return s.view()


def _get(bid):
    s = STORE.sessions.get(bid)
    if not s:
        raise HTTPException(404, "없는 배틀")
    return s


@app.get("/api/battle/{bid}")
def battle_get(bid: str):
    return _get(bid).view()


class Analyze(BaseModel):
    side: int = 0


@app.post("/api/battle/{bid}/analyze")
def battle_analyze(bid: str, a: Analyze):
    try:
        return _get(bid).analyze(a.side)
    except RuntimeError as e:
        raise HTTPException(503, str(e))


class Turn(BaseModel):
    acts: list
    choices: list = []


@app.post("/api/battle/{bid}/turn")
def battle_turn(bid: str, t: Turn):
    try:
        return _get(bid).play_turn([None if a is None else tuple(a) for a in t.acts], t.choices)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("GUI_PORT", "8765")))
