"""GUI 에 내려 줄 도감 자료 (챔피언스 기준): 포켓몬/기술/도구/특성/성격의 한글·영문 이름과 습득 기술, 특성 목록."""
from ai.gamedata import GameData, connect, norm

SP_KEYS = ("hp", "atk", "def", "spa", "spd", "spe")
REGION_KO = {"alola": "알로라", "galar": "가라르", "hisui": "히스이", "paldea": "팔데아"}            # 지역 폼도 이름 뒤 괄호로 (이름이 맨 앞에 와야 검색 미리보기에 뜬다)
FORM_KO = {"blue-plumage": "블루 깃털", "white-plumage": "화이트 깃털", "yellow-plumage": "옐로 깃털", "green-plumage": "그린 깃털", "wash": "워시", "heat": "히트", "frost": "프로스트", "mow": "컷", "fan": "스핀", "rainy": "빗방울", "sunny": "태양", "snowy": "설운",
           "hero": "히어로", "busted": "탈 벗겨진 모습", "hangry": "배고픈 모습", "rapid-strike": "연격 스타일", "low-key": "로우 모습",
           "wellspring-mask": "우물의 가면", "hearthflame-mask": "화덕의 가면", "cornerstone-mask": "주춧돌의 가면", "paldea-combat-breed": "팔데아 컴뱃종",
           "paldea-blaze-breed": "팔데아 블레이즈종", "paldea-aqua-breed": "팔데아 워터종", "blade": "블레이드 폼", "female": "암컷", "zen": "달마 모드",
           "galar-zen": "가라르 달마 모드", "crowned": "검왕", "eternal": "영원의 꽃", "small": "작은 사이즈", "large": "큰 사이즈", "super": "특대 사이즈",
           "dusk": "황혼의 모습", "midnight": "한밤의 모습", "bloodmoon": "붉은 달", "stellar": "스텔라폼", "terastal": "테라스탈 폼", "school": "군집 모습",
           "ice": "얼음 모습", "noice": "나이스 페이스", "three-segment": "세 마디 폼", "droopy": "늘어진 폼", "stretchy": "쭉 뻗은 폼", "dada": "다다 폼",
           "family-of-three": "세 식구 폼", "pau": "파우 스타일", "pom-pom": "퐁퐁 스타일", "sensu": "하늘하늘 스타일", "original-cap": "오리지널 캡"}


def ko_label(name, form):
    if not form:
        return name
    if form in REGION_KO:
        return f"{name} ({REGION_KO[form]})"
    if form.startswith("mega"):
        return "메가" + name + {"mega-x": " X", "mega-y": " Y", "mega-z": " Z"}.get(form, "")
    return f"{name} ({FORM_KO.get(form, form)})"


def build_dex(data: GameData, conn):
    cur = conn.cursor()
    cur.execute("select showdown_id sid, name_ko, form_name from pokemon")
    ko = {r["sid"]: ko_label(r["name_ko"], r["form_name"]) for r in cur.fetchall()}
    cur.execute("select name_en, name_ko from move")
    mko = {norm(r["name_en"]): r["name_ko"] for r in cur.fetchall()}
    cur.execute("select name_en, name_ko from ability")
    ako = {norm(r["name_en"]): r["name_ko"] for r in cur.fetchall()}
    cur.execute("""select i.name_en, i.name_ko from game_item gi join game g using(game_id) join item i using(item_id) where g.code='CHAMPIONS'""")
    items = [dict(key=norm(r["name_en"]), en=r["name_en"], ko=r["name_ko"]) for r in cur.fetchall()]
    cur.execute("select name_en, name_ko, plus_stat, minus_stat from nature")
    natures = [dict(en=r["name_en"], ko=r["name_ko"], plus=r["plus_stat"], minus=r["minus_stat"]) for r in cur.fetchall()]
    mega = {r["name_en"] for r in _megas(cur)}
    ko_plain = dict(ko)                                  # 로그용: 수컷 표기 없는 이름
    for sid in [k for k in ko if k]:                     # 암컷 폼이 따로 있는 종은 기본 폼에 (수컷) 을 붙여 기본이 수컷인 것처럼 보이지 않게 한다
        if sid + "f" in data.pokemon and sid in data.pokemon:
            ko[sid] = ko[sid] + " (수컷)"
    megas = []
    cur.execute("""select pm.showdown_id mega, pb.showdown_id base, i.name_en item from mega_evolution me
                   join pokemon pm on pm.pokemon_id=me.mega_pokemon_id join pokemon pb on pb.pokemon_id=me.base_pokemon_id
                   join item i on i.item_id=me.item_id""")
    for r in cur.fetchall():
        if r["mega"] not in data.pokemon or r["base"] not in data.pokemon:
            continue
        mk, bk = ko_plain.get(r["mega"], r["mega"]), ko_plain.get(r["base"], r["base"])
        suffix = mk[len("메가" + bk):] if mk.startswith("메가" + bk) else ""
        megas.append(dict(sid=r["mega"], base=r["base"], item=r["item"], labels=[mk, f"{bk} (메가{suffix})"], stats=data.pokemon[r["mega"]]["base"]))
    mons = []
    for sid, p in data.pokemon.items():
        if sid in mega:                       # 메가 폼은 배틀 중 진화로만 등장한다
            continue
        mons.append(dict(sid=sid, ko=ko.get(sid, p["name"]), en=p["name"], types=p["types"], base=p["base"],
                         abilities=[dict(en=a, ko=ako.get(norm(a), a)) for a in dict.fromkeys(p["abilities"].values())],
                         learn=sorted(p["learn"])))
    mons.sort(key=lambda m: m["ko"])
    moves = {k: dict(key=k, en=m["name"], ko=mko.get(k, m["name"]), type=m["type"], cat=m["category"], bp=m["bp"], acc=m["accuracy"], pp=m["pp"])
             for k, m in data.moves.items() if k != "struggle"}
    return dict(ko_all={sid: ko_plain.get(sid, p["name"]) for sid, p in data.pokemon.items()}, megas=megas, mons=mons, moves=moves, items=sorted(items, key=lambda x: x["ko"]), natures=natures,
                move_ko=mko, abil_ko=ako)


def _megas(cur):
    cur.execute("select p.showdown_id name_en from mega_evolution me join pokemon p on p.pokemon_id=me.mega_pokemon_id")
    return cur.fetchall()
