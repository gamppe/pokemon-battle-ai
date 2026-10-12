"""PokeAPI -> etl/cache/*.json (재실행 시 캐시 재사용)"""
import json, os, re, sys, requests
from concurrent.futures import ThreadPoolExecutor

BASE = "https://pokeapi.co/api/v2"
CACHE = os.path.join(os.path.dirname(__file__), "cache")
os.makedirs(CACHE, exist_ok=True)
S = requests.Session()

def get(path):
    f = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9_.-]", "_", path.strip("/")) + ".json")
    if os.path.exists(f):
        return json.load(open(f, encoding="utf-8"))
    for i in range(5):
        try:
            r = S.get(f"{BASE}/{path.strip('/')}", timeout=30)
            if r.status_code == 200:
                d = r.json()
                json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False)
                return d
        except requests.RequestException:
            pass
    raise RuntimeError(path)

def names(kind):
    return [x["name"] for x in get(f"{kind}?limit=5000")["results"]]

def many(kind, ns):
    with ThreadPoolExecutor(16) as ex:
        list(ex.map(lambda n: get(f"{kind}/{n}"), ns))

if __name__ == "__main__":
    for kind in ["type", "ability", "move", "pokemon", "pokemon-species"]:
        ns = names(kind); print(kind, len(ns), flush=True); many(kind, ns)
    hold = get("item-attribute/holdable")["items"] + get("item-attribute/holdable-active")["items"] \
         + get("item-attribute/holdable-passive")["items"]
    ns = sorted({i["name"] for i in hold}); print("item", len(ns), flush=True); many("item", ns)
