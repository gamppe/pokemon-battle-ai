"""특성/아이템 수치화 검수용 CSV (Showdown 원문 | 우리가 만든 수치). 엑셀에서 열어 대조."""
import os, re, csv, json, pymysql
norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower().replace("’", ""))
db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()

def sd_text(path):
    t = open(path, encoding="utf-8").read(); out = {}
    for m in re.finditer(r"^\t(\w+): \{\n(.*?)^\t\},", t, re.S | re.M):
        b = m.group(2)
        d = re.search(r'^\t\tdesc: "(.*?)",\n', b, re.M); s = re.search(r'^\t\tshortDesc: "(.*?)",\n', b, re.M)
        out[m.group(1)] = (d.group(1) if d else None) or (s.group(1) if s else "")
    return out

def line(r):
    hook, kind, target, code, value, chance, cond, note = r
    p = [f"[{hook}]", kind]
    if target: p.append(f"대상={target}")
    if code: p.append(f"코드={code}")
    if value is not None: p.append(f"값={float(value):g}")
    if chance != 100: p.append(f"확률={chance}%")
    if cond: p.append("조건=" + (cond if isinstance(cond, str) else json.dumps(cond, ensure_ascii=False)))
    if note: p.append(f"({note})")
    return " ".join(p)

def export(fname, text_file, idcol, tbl, view, game_filter):
    txt = sd_text(text_file)
    cur.execute(f"""select x.{idcol}, x.name_ko, x.name_en from {tbl} x where x.{idcol} in ({game_filter}) order by x.name_en""")
    rows = cur.fetchall()
    with open(fname, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f); w.writerow(["번호", "한글명", "영문명", "원문(Showdown)", "수치화 (한 줄=효과 1개)"])
        for i, ko, en in rows:
            cur.execute(f"select hook,kind,target,code,value,chance_pct,cond,note from {view} where {idcol}=%s order by 1", (i,))
            w.writerow([i, ko, en, txt.get(norm(en), ""), "\n".join(line(r) for r in cur.fetchall())])
    print(fname, len(rows))

here = os.path.dirname(os.path.abspath(__file__))
out = os.path.join(here, "..", "review")
os.makedirs(out, exist_ok=True)
export(os.path.join(out, "review_abilities.csv"), os.path.join(here, "cache_sd_abilities_text.ts"), "ability_id", "ability",
       "v_ability_effect", "select ability_id from pokemon_ability where game_id=4")
export(os.path.join(out, "review_items.csv"), os.path.join(here, "cache_sd_items_text.ts"), "item_id", "item",
       "v_item_effect", "select item_id from game_item where game_id=4")
