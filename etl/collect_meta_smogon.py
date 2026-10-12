"""Smogon 통계(Showdown 래더) -> meta_* 테이블. 챔피언스 싱글(BSS) 포맷, 레이팅 컷오프별.
사용: python collect_meta_smogon.py [--formats gen9championsbssregmc,...] [--months 2026-09,...] [--replace]
 - 월별 chaos JSON 을 etl/cache_meta/smogon/ 에 캐시(.gitignore)하고, 이미 있는 스냅샷은 건너뜀(--replace 로 갱신).
 - prob 열 = weight / (그 포켓몬의 세트 수). 세트 수 = 특성 가중치의 합. 기술의 prob 는 '세트에 그 기술이 있을 확률'이라 합이 4 근처.
 - 이 데이터는 Showdown 래더 인구이며 게임 내 래더와 다를 수 있다.
출처 이용: smogon.com/stats (robots.txt 허용, 월 1회 공개 파일). 요청은 천천히 한다."""
import argparse, datetime, json, os, re, time
import pymysql, requests

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache_meta", "smogon")
H = {"User-Agent": "Mozilla/5.0 (personal research; pokemon battle ai project)"}
CUTOFFS = (0, 1500, 1630, 1760)
TIER_LABEL = {0: "전체", 1500: "중간", 1630: "상위", 1760: "최상위"}
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())

ap = argparse.ArgumentParser()
ap.add_argument("--formats", default="gen9championsbssregma,gen9championsbssregmb,gen9championsbssregmc")
ap.add_argument("--months", default="")
ap.add_argument("--replace", action="store_true")
args = ap.parse_args()
formats = [f for f in args.formats.split(",") if f]

DDL = [
 """CREATE TABLE IF NOT EXISTS meta_snapshot (
  snapshot_id INT UNSIGNED PRIMARY KEY AUTO_INCREMENT, source VARCHAR(20) NOT NULL, format VARCHAR(50) NOT NULL,
  cutoff SMALLINT NOT NULL, period CHAR(7) NOT NULL, battles INT NULL, tier_label VARCHAR(20) NULL,
  fetched_at DATETIME NOT NULL, note VARCHAR(200) NULL, UNIQUE KEY uq_snapshot (source, format, cutoff, period))""",
 """CREATE TABLE IF NOT EXISTS meta_pokemon (
  snapshot_id INT UNSIGNED NOT NULL, pokemon_key VARCHAR(50) NOT NULL, pokemon_id SMALLINT UNSIGNED NULL,
  usage_pct DECIMAL(7,4) NOT NULL, raw_count INT NOT NULL, set_total DOUBLE NOT NULL,
  PRIMARY KEY (snapshot_id, pokemon_key), FOREIGN KEY (snapshot_id) REFERENCES meta_snapshot(snapshot_id) ON DELETE CASCADE)""",
]
for tbl, col in (("meta_ability", "ability"), ("meta_item", "item"), ("meta_move", "move")):
    DDL.append(f"""CREATE TABLE IF NOT EXISTS {tbl} (
  snapshot_id INT UNSIGNED NOT NULL, pokemon_key VARCHAR(50) NOT NULL, {col}_key VARCHAR(60) NOT NULL, {col}_id SMALLINT UNSIGNED NULL,
  weight DOUBLE NOT NULL, prob DECIMAL(8,6) NOT NULL, PRIMARY KEY (snapshot_id, pokemon_key, {col}_key),
  FOREIGN KEY (snapshot_id) REFERENCES meta_snapshot(snapshot_id) ON DELETE CASCADE)""")
DDL += [
 """CREATE TABLE IF NOT EXISTS meta_spread (
  snapshot_id INT UNSIGNED NOT NULL, pokemon_key VARCHAR(50) NOT NULL, nature VARCHAR(12) NOT NULL,
  sp_hp TINYINT UNSIGNED NOT NULL, sp_atk TINYINT UNSIGNED NOT NULL, sp_def TINYINT UNSIGNED NOT NULL,
  sp_spa TINYINT UNSIGNED NOT NULL, sp_spd TINYINT UNSIGNED NOT NULL, sp_spe TINYINT UNSIGNED NOT NULL,
  weight DOUBLE NOT NULL, prob DECIMAL(8,6) NOT NULL,
  PRIMARY KEY (snapshot_id, pokemon_key, nature, sp_hp, sp_atk, sp_def, sp_spa, sp_spd, sp_spe),
  FOREIGN KEY (snapshot_id) REFERENCES meta_snapshot(snapshot_id) ON DELETE CASCADE)""",
 """CREATE TABLE IF NOT EXISTS meta_teammate (
  snapshot_id INT UNSIGNED NOT NULL, pokemon_key VARCHAR(50) NOT NULL, mate_key VARCHAR(50) NOT NULL,
  weight DOUBLE NOT NULL, prob DECIMAL(8,6) NOT NULL, PRIMARY KEY (snapshot_id, pokemon_key, mate_key),
  FOREIGN KEY (snapshot_id) REFERENCES meta_snapshot(snapshot_id) ON DELETE CASCADE)""",
 """CREATE TABLE IF NOT EXISTS meta_counter (
  snapshot_id INT UNSIGNED NOT NULL, pokemon_key VARCHAR(50) NOT NULL, other_key VARCHAR(50) NOT NULL,
  v0 DOUBLE NOT NULL, v1 DOUBLE NOT NULL, v2 DOUBLE NOT NULL, PRIMARY KEY (snapshot_id, pokemon_key, other_key),
  FOREIGN KEY (snapshot_id) REFERENCES meta_snapshot(snapshot_id) ON DELETE CASCADE)""",
]

db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()
for q in DDL:
    cur.execute(q)

# 키 -> DB id 매핑
cur.execute("select showdown_id, pokemon_id from pokemon where showdown_id is not null")
pmap = {k: i for k, i in cur.fetchall()}
amap, imap, mmap = {}, {}, {}
for tbl, idc, m in (("ability", "ability_id", amap), ("item", "item_id", imap), ("move", "move_id", mmap)):
    cur.execute(f"select {idc}, name_en from `{tbl}`")
    for i, n in cur.fetchall():
        m.setdefault(norm(n), i)

# 사용 가능한 월/포맷
os.makedirs(CACHE, exist_ok=True)
idx = requests.get("https://www.smogon.com/stats/", headers=H, timeout=30).text
all_months = re.findall(r'href="(\d{4}-\d{2})/"', idx)
want_months = [m for m in args.months.split(",") if m] or all_months
stats = dict(snap=0, skip=0, rows=0, unmapped_p=set(), unmapped_i=set(), unmapped_m=set(), unmapped_a=set())


def fetch(month, fmt, cut):
    path = os.path.join(CACHE, month, f"{fmt}-{cut}.json")
    if os.path.exists(path):
        return path
    url = f"https://www.smogon.com/stats/{month}/chaos/{fmt}-{cut}.json"
    r = requests.get(url, headers=H, timeout=90)
    if r.status_code != 200:
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(r.content)
    time.sleep(1.0)
    return path


def insert_many(sql, rows):
    for i in range(0, len(rows), 5000):
        cur.executemany(sql, rows[i:i + 5000])


for month in want_months:
    listing = None
    for fmt in formats:
        for cut in CUTOFFS:
            cur.execute("select snapshot_id from meta_snapshot where source='smogon' and format=%s and cutoff=%s and period=%s", (fmt, cut, month))
            old = cur.fetchone()
            if old and not args.replace:
                stats["skip"] += 1
                continue
            if listing is None:
                listing = requests.get(f"https://www.smogon.com/stats/{month}/chaos/", headers=H, timeout=30).text
            if f"{fmt}-{cut}.json" not in listing:
                continue
            path = fetch(month, fmt, cut)
            if not path:
                continue
            d = json.load(open(path, encoding="utf-8"))
            if old:
                cur.execute("delete from meta_snapshot where snapshot_id=%s", (old[0],))
            fetched = datetime.datetime.fromtimestamp(os.path.getmtime(path)).replace(microsecond=0)
            cur.execute("""insert into meta_snapshot (source,format,cutoff,period,battles,tier_label,fetched_at,note) values
                ('smogon',%s,%s,%s,%s,%s,%s,%s)""", (fmt, cut, month, d["info"]["number of battles"], TIER_LABEL[cut], fetched,
                                                       "Showdown 래더 통계. 컷오프 = 레이팅 하한"))
            sid = cur.lastrowid
            P, A, I, M, S, T, C = [], [], [], [], [], [], []
            for name, v in d["data"].items():
                pk = norm(name)
                total = sum(v["Abilities"].values()) or sum(v["Items"].values()) or 1.0
                if pk not in pmap:
                    stats["unmapped_p"].add(name)
                P.append((sid, pk, pmap.get(pk), round(v["usage"] * 100, 4), v["Raw count"], total))
                for k, w in v["Abilities"].items():
                    if norm(k) not in amap: stats["unmapped_a"].add(k)
                    A.append((sid, pk, norm(k), amap.get(norm(k)), w, round(w / total, 6)))
                for k, w in v["Items"].items():
                    if norm(k) not in imap and k != "nothing": stats["unmapped_i"].add(k)
                    I.append((sid, pk, norm(k), imap.get(norm(k)), w, round(w / total, 6)))
                for k, w in v["Moves"].items():
                    if norm(k) not in mmap and k: stats["unmapped_m"].add(k)
                    M.append((sid, pk, norm(k), mmap.get(norm(k)), w, round(w / total, 6)))
                seen = set()
                for k, w in sorted(v["Spreads"].items(), key=lambda kv: -kv[1])[:60]:
                    m = re.match(r"([A-Za-z]+):(\d+)/(\d+)/(\d+)/(\d+)/(\d+)/(\d+)", k)
                    if not m or (m.group(1), *m.groups()[1:]) in seen:
                        continue
                    seen.add((m.group(1), *m.groups()[1:]))
                    S.append((sid, pk, m.group(1), *map(int, m.groups()[1:]), w, round(w / total, 6)))
                for k, w in sorted(v["Teammates"].items(), key=lambda kv: -kv[1])[:40]:
                    T.append((sid, pk, norm(k), w, round(w / total, 6)))
                # n=상대한 횟수, p=이 포켓몬을 쓰러뜨리거나 교체시킬 확률, d=표준편차. 표본(n>=20)이 있는 것 중 p가 큰 25개
                cc = [(k, w) for k, w in v["Checks and Counters"].items() if w["n"] >= 20]
                for k, w in sorted(cc, key=lambda kv: -kv[1]["p"])[:25]:
                    C.append((sid, pk, norm(k), float(w["n"]), float(w["p"]), float(w["d"])))
            insert_many("insert into meta_pokemon values (%s,%s,%s,%s,%s,%s)", P)
            insert_many("insert into meta_ability values (%s,%s,%s,%s,%s,%s)", A)
            insert_many("insert into meta_item values (%s,%s,%s,%s,%s,%s)", I)
            insert_many("insert into meta_move values (%s,%s,%s,%s,%s,%s)", M)
            insert_many("insert into meta_spread values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", S)
            insert_many("insert into meta_teammate values (%s,%s,%s,%s,%s)", T)
            insert_many("insert into meta_counter values (%s,%s,%s,%s,%s,%s)", C)
            db.commit()
            stats["snap"] += 1
            stats["rows"] += len(P) + len(A) + len(I) + len(M) + len(S) + len(T) + len(C)
            print(f"  {month} {fmt} 컷오프 {cut}: 포켓몬 {len(P)}, 행 {len(P)+len(A)+len(I)+len(M)+len(S)+len(T)+len(C)}", flush=True)

print(f"스냅샷 새로 {stats['snap']} / 건너뜀 {stats['skip']} / 행 {stats['rows']}")
for k, label in (("unmapped_p", "DB에 없는 포켓몬"), ("unmapped_a", "DB에 없는 특성"), ("unmapped_i", "DB에 없는 아이템"), ("unmapped_m", "DB에 없는 기술")):
    v = sorted(stats[k])
    print(f"{label}: {len(v)}" + (f" {v[:15]}" if v else ""))
