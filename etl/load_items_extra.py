"""Serebii의 ZA/챔피언스 지닌물건 목록 -> item, game_item (PokeAPI 이름 매칭, 없으면 신규 추가)"""
import os, re, requests, pymysql
from bs4 import BeautifulSoup
from fetch import get, names

SRC = {  # game code: (url, 지닌물건/메가스톤/열매 표 인덱스)
    "CHAMPIONS": ("https://www.serebii.net/pokemonchampions/items.shtml", [0, 1, 2]),
    "ZA":        ("https://www.serebii.net/legendsz-a/items.shtml",       [2, 5, 6]),
}
norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower().replace("é", "e"))
api = {norm(n): n for n in names("item")}
db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"], database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()
cur.execute("select game_id, code from game"); gid = {c: i for i, c in cur.fetchall()}
cur.execute("select item_id, name_en from item"); have = {norm(n): i for i, n in cur.fetchall()}
nxt = 100000; unmatched = []
for code, (url, idx) in SRC.items():
    html = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
    tabs = BeautifulSoup(html, "lxml").select("table.dextable")
    added = 0
    for i in idx:
        for tr in tabs[i].select("tr")[1:]:
            td = tr.select("td")
            if len(td) < 3: continue
            name, eff = td[1].get_text(" ", strip=True), td[2].get_text(" ", strip=True)
            k = norm(name)
            if k not in have:
                if k in api:
                    d = get(f"item/{api[k]}")
                    ko = next((n["name"] for n in d["names"] if n["language"]["name"] == "ko"), name)
                    iid = d["id"]
                else:
                    ko, iid = name, nxt; nxt += 1; unmatched.append(name)
                cur.execute("insert ignore into item (item_id,name_ko,name_en,effect_text) values (%s,%s,%s,%s)", (iid, ko, name, eff))
                have[k] = iid
            cur.execute("insert ignore into game_item (game_id,item_id) values (%s,%s)", (gid[code], have[k])); added += 1
    print(code, "items:", added)
db.commit()
print("PokeAPI 매칭 실패(영문명 사용):", unmatched)
