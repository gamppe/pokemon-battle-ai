"""pokemondb.net -> cache_za/{slug}.json  (ZA 습득 기술). robots.txt Crawl-delay 2s 준수"""
import os, json, time, requests, pymysql
from bs4 import BeautifulSoup

OUT = os.path.join(os.path.dirname(__file__), "cache_za"); os.makedirs(OUT, exist_ok=True)
db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"], database=os.environ.get("POKEMON_DB", "pokemon"))
cur = db.cursor()
cur.execute("""select p.pokemon_id, p.name_en from pokemon p join game_pokemon gp using(pokemon_id)
               join game g using(game_id) where g.code='ZA'""")
targets = cur.fetchall()
from fetch import get
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (personal pokemon db project)"

def parse(html):
    tab = BeautifulSoup(html, "lxml").select_one("#tab-moves-22")
    if tab is None: return None
    res = {}
    for h in tab.select("h3"):
        t = h.find_next("table")
        key = {"level up": "level-up", "reminder": "tutor", "TM": "machine", "egg": "egg", "tutor": "tutor"}
        k = next((v for w, v in key.items() if w in h.get_text()), "other")
        for tr in t.select("tbody tr"):
            a = tr.select_one("a.ent-name")
            if not a: continue
            lv = tr.select_one("td.cell-num")
            lvl = int(lv.get_text(strip=True)) if k == "level-up" and lv and lv.get_text(strip=True).isdigit() else 0
            res.setdefault(k, []).append([a["href"].split("/")[-1], lvl])
    return res

for pid, name in targets:
    species = get(f"pokemon/{pid}")["species"]["name"]
    f = os.path.join(OUT, f"{pid}.json")
    if os.path.exists(f): continue
    for slug in (species, name.lower()):
        r = S.get(f"https://pokemondb.net/pokedex/{slug}/moves/9", timeout=30); time.sleep(2)
        if r.status_code == 200:
            data = parse(r.text)
            json.dump({"slug": slug, "moves": data}, open(f, "w", encoding="utf-8")); break
    else:
        json.dump({"slug": None, "moves": None}, open(f, "w", encoding="utf-8"))
print("done")
