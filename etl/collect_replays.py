"""Showdown 공개 리플레이 수집 (선출 3마리 / 파티 6마리 / 리드 / 승패 / 레이팅).
- 출처: replay.pokemonshowdown.com 의 공개 검색·리플레이 JSON (robots.txt 없음, 공개 API). 요청 간격을 두고 식별 가능한 User-Agent 로 접근한다.
- 닉네임은 저장하지 않는다 (승패는 p1/p2 로만 기록).
- 원본 JSON 은 etl/cache_replays/ 에 캐시 (gitignore). 같은 리플레이는 다시 받지 않는다.
- 선출은 로그에서 실제로 필드에 나온(switch/drag) 포켓몬으로 정의한다. 3마리가 다 나오기 전에 끝난 판은 brought 가 3 미만일 수 있다.
사용: python etl/collect_replays.py [--format gen9championsbssregmc] [--max 1500] [--delay 0.7] [--min-rating 0]"""
import argparse
import datetime
import gzip
import json
import os
import re
import sys
import time
import urllib.request

import pymysql

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache_replays")
os.makedirs(CACHE, exist_ok=True)
UA = "pokemon-battle-ai-research/0.1 (personal research project; low-rate)"
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())

DDL = [
    """CREATE TABLE IF NOT EXISTS replay (
        replay_id VARCHAR(90) PRIMARY KEY, format_id VARCHAR(60) NOT NULL, uploadtime INT NOT NULL, rating INT NULL,
        turns INT NULL, winner TINYINT NULL COMMENT '0=p1 1=p2')""",
    """CREATE TABLE IF NOT EXISTS replay_mon (
        replay_id VARCHAR(90) NOT NULL, side TINYINT NOT NULL, slot TINYINT NOT NULL, species VARCHAR(60) NOT NULL,
        pokemon_id INT NULL, brought TINYINT NOT NULL, is_lead TINYINT NOT NULL, mega_form VARCHAR(60) NULL,
        PRIMARY KEY (replay_id, side, slot), KEY (species))""",
]


def load_cached(rid):
    for ext, op in ((".json.gz", gzip.open), (".json", open)):
        path = os.path.join(CACHE, rid + ext)
        if os.path.exists(path):
            with op(path, "rt", encoding="utf-8") as f:
                return json.load(f)
    return None


def save_cached(rid, r):
    with gzip.open(os.path.join(CACHE, rid + ".json.gz"), "wt", encoding="utf-8") as f:
        json.dump(r, f)


def http_json(url, delay):
    time.sleep(delay)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            return json.load(urllib.request.urlopen(req, timeout=40))
        except Exception as e:
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))


def parse(log):
    """리플레이 로그 -> dict(teams[side]=[종 이름...], brought, lead, mega, winner, turns)"""
    teams = {"p1": [], "p2": []}
    players, brought, lead, mega = {}, {"p1": [], "p2": []}, {}, {}
    winner, turns = None, 0
    for ln in log.split("\n"):
        if ln.startswith("|poke|"):
            _, _, side, det = ln.split("|")[:4]
            teams[side].append(det.split(",")[0].strip())
        elif ln.startswith("|player|"):
            parts = ln.split("|")
            if len(parts) > 3 and parts[2] in ("p1", "p2"):
                players[parts[3]] = parts[2]
        elif ln.startswith(("|switch|", "|drag|")):
            parts = ln.split("|")
            side = parts[2][:2]
            sp = parts[3].split(",")[0].strip()
            if sp not in brought[side]:
                brought[side].append(sp)
            lead.setdefault(side, sp)
        elif ln.startswith("|detailschange|"):
            parts = ln.split("|")
            side = parts[2][:2]
            form = parts[3].split(",")[0].strip()
            if "-Mega" in form:
                base = form.split("-Mega")[0]
                mega[(side, base)] = form              # 예: ('p1', 'Garchomp') -> 'Garchomp-Mega-Z'
        elif ln.startswith("|win|"):
            winner = players.get(ln.split("|", 2)[2])
        elif ln.startswith("|turn|"):
            turns = int(ln.split("|")[2])
    return dict(teams=teams, brought=brought, lead=lead, mega=mega, winner=winner, turns=turns)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", default="gen9championsbssregmc")
    ap.add_argument("--max", type=int, default=1500)
    ap.add_argument("--delay", type=float, default=0.7)
    ap.add_argument("--min-rating", type=int, default=0)
    ap.add_argument("--since", default=None, help="이 날짜(YYYY-MM-DD) 이전 리플레이에 도달하면 중단")
    a = ap.parse_args()
    db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"),
                         password=os.environ["DB_PASSWORD"], database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
    cur = db.cursor()
    for d in DDL:
        cur.execute(d)
    cur.execute("select showdown_id, pokemon_id from pokemon where showdown_id is not null")
    pid_by_sid = {k: v for k, v in cur.fetchall()}
    cur.execute("select replay_id from replay")
    have = {r[0] for r in cur.fetchall()}
    since = int(datetime.datetime.strptime(a.since, "%Y-%m-%d").timestamp()) if a.since else 0
    got, before, seen_ids = 0, None, set()
    t0 = time.time()
    while got < a.max:
        try:
            url = f"https://replay.pokemonshowdown.com/search.json?format={a.format}" + (f"&before={before}" if before else "")
            lst = http_json(url, a.delay)
        except Exception as e:
            print("검색 실패:", e)
            break
        if not lst:
            break
        for item in lst:
            rid = item["id"]
            if item["uploadtime"] < since:
                continue
            if rid in seen_ids or rid in have:
                continue
            seen_ids.add(rid)
            if item.get("private") or (item.get("rating") or 0) < a.min_rating:
                continue
            r = load_cached(rid)
            if r is None:
                try:
                    r = http_json(f"https://replay.pokemonshowdown.com/{rid}.json", a.delay)
                except Exception as e:
                    print("리플레이 실패:", rid, e)
                    continue
                save_cached(rid, r)
            p = parse(r["log"])
            if len(p["teams"]["p1"]) != 6 or len(p["teams"]["p2"]) != 6:
                continue
            winner = {"p1": 0, "p2": 1}.get(p["winner"])
            cur.execute("insert ignore into replay values (%s,%s,%s,%s,%s,%s)",
                        (rid, a.format, item["uploadtime"], item.get("rating"), p["turns"], winner))
            for side_i, side in enumerate(("p1", "p2")):
                for slot, sp in enumerate(p["teams"][side]):
                    cur.execute("insert ignore into replay_mon values (%s,%s,%s,%s,%s,%s,%s,%s)",
                                (rid, side_i, slot, sp, pid_by_sid.get(norm(sp)), int(sp in p["brought"][side]),
                                 int(p["lead"].get(side) == sp), p["mega"].get((side, sp))))
            db.commit()
            got += 1
            if got % 50 == 0:
                print(f"  {got}/{a.max} ({time.time() - t0:.0f}s)", flush=True)
            if got >= a.max:
                break
        if not lst or min(x["uploadtime"] for x in lst) <= since:
            break
        before = min(x["uploadtime"] for x in lst)
    print(f"새로 저장한 리플레이: {got}개, 경과 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
