"""외부 원본을 내려받아 etl/ 아래에 캐시한다 (이미 있으면 건너뜀). 사용: python download_sources.py
출처
  - PokeAPI (https://pokeapi.co)                : 도감/기술/특성/아이템/한글명 -> etl/cache/ (fetch.py)
  - Pokémon Showdown (smogon/pokemon-showdown)  : 챔피언스 모드 데이터, 기술/특성/아이템 설명, 상성표
  - 파생 파일                                   : breakable_abilities.json, champ_items_effective.json
이 파일들은 제3자 자료라 저장소에 포함하지 않는다(.gitignore). 각 출처의 이용 조건을 지킬 것."""
import json, os, re, subprocess, sys, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = "https://raw.githubusercontent.com/smogon/pokemon-showdown/master"
PLAY = "https://play.pokemonshowdown.com/data"
UA = {"User-Agent": "Mozilla/5.0 (pokemon db project; personal use)"}

FILES = {  # 저장 이름 -> URL
    "cache_sd_moves.json": f"{PLAY}/moves.json",
    "cache_sd_pokedex.json": f"{PLAY}/pokedex.json",
    "cache_sd_items.js": f"{PLAY}/items.js",
    "cache_sd_abilities.js": f"{PLAY}/abilities.js",
    "cache_sd_moves.ts": f"{RAW}/data/moves.ts",
    "cache_sd_abilities_base.ts": f"{RAW}/data/abilities.ts",
    "cache_sd_typechart.ts": f"{RAW}/data/typechart.ts",
    "cache_sd_abilities_text.ts": f"{RAW}/data/text/abilities.ts",
    "cache_sd_items_text.ts": f"{RAW}/data/text/items.ts",
    "cache_sd_formats.ts": f"{RAW}/config/formats.ts",
}
for name in ("abilities", "conditions", "formats-data", "items", "learnsets", "rulesets", "scripts", "moves"):
    FILES[f"cache_sd_champ_{name}.ts"] = f"{RAW}/data/mods/champions/{name}.ts"


def download():
    for fname, url in FILES.items():
        path = os.path.join(HERE, fname)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            continue
        r = requests.get(url, headers=UA, timeout=60)
        r.raise_for_status()
        open(path, "wb").write(r.content)
        print("받음", fname, len(r.content))
        time.sleep(0.3)


def js_to_json(js_name, json_name, export, picks):
    """Showdown 의 *.js(자바스크립트 객체)를 node 로 읽어 JSON 으로 저장"""
    out = os.path.join(HERE, json_name)
    if os.path.exists(out):
        return
    code = (f"const fs=require('fs');const exports={{}};eval(fs.readFileSync({json.dumps(os.path.join(HERE, js_name))},'utf8'));"
            f"const o={{}};for(const [k,v] of Object.entries(exports.{export})){{o[k]={{{picks}}}}}"
            f"fs.writeFileSync({json.dumps(out)},JSON.stringify(o));")
    subprocess.run(["node", "-e", code], check=True)
    print("변환", json_name)


def derive():
    # 몰드브레이커가 무시하는 특성(breakable)
    out = os.path.join(HERE, "breakable_abilities.json")
    if not os.path.exists(out):
        ab = open(os.path.join(HERE, "cache_sd_abilities_base.ts"), encoding="utf-8").read()
        names = []
        for m in re.finditer(r"^\t(\w+): \{\n(.*?)^\t\},", ab, re.S | re.M):
            if re.search(r"breakable: 1", m.group(2)):
                nm = re.search(r'name: "([^"]+)"', m.group(2))
                names.append(nm.group(1) if nm else m.group(1))
        json.dump(names, open(out, "w", encoding="utf-8"), ensure_ascii=False)
        print("생성 breakable_abilities.json", len(names))
    # 챔피언스에서 사용 가능한 아이템 id (기본 isNonstandard + 챔피언스 모드 덮어쓰기)
    out = os.path.join(HERE, "champ_items_effective.json")
    if not os.path.exists(out):
        base = json.load(open(os.path.join(HERE, "cache_sd_items.json"), encoding="utf-8"))
        ov = {}
        for m in re.finditer(r"^\t(\w+): \{\n(.*?)^\t\},", open(os.path.join(HERE, "cache_sd_champ_items.ts"), encoding="utf-8").read(), re.S | re.M):
            x = re.search(r'isNonstandard: (null|"\w+")', m.group(2))
            ov[m.group(1)] = None if (x and x.group(1) == "null") else (x.group(1).strip('"') if x else "inherit")
        eff = []
        for k, v in base.items():
            ns = v["isNonstandard"]
            if k in ov and ov[k] != "inherit":
                ns = ov[k]
            if ns is None:
                eff.append(k)
        json.dump(sorted(eff), open(out, "w", encoding="utf-8"))
        print("생성 champ_items_effective.json", len(eff))


if __name__ == "__main__":
    download()
    js_to_json("cache_sd_items.js", "cache_sd_items.json", "BattleItems",
               "name:v.name,isNonstandard:v.isNonstandard||null,gen:v.gen,megaStone:v.megaStone||null,"
               "desc:v.shortDesc||v.desc||null,fling:v.fling||null,naturalGift:v.naturalGift||null")
    js_to_json("cache_sd_abilities.js", "cache_sd_abilities.json", "BattleAbilities",
               "name:v.name,short:v.shortDesc||v.desc||null,ns:v.isNonstandard||null")
    derive()
    if "--pokeapi" in sys.argv:       # PokeAPI 전체 캐시(수백 MB, 수 분)
        import fetch
        for kind in ["type", "ability", "move", "pokemon", "pokemon-species", "nature", "pokedex"]:
            ns = fetch.names(kind)
            print("PokeAPI", kind, len(ns), flush=True)
            fetch.many(kind, ns)
    print("완료")
