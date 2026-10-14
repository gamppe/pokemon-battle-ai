"""정적 데이터 비교: Showdown(champions 모드) 덤프 vs 우리 DB(GameData, 챔피언스 적용값).
사용: node verify/sd_dump.js showdown verify/out/sd_dump.json && python -m verify.static_diff
출력: verify/out/static_diff.csv (분류,이름,필드,Showdown,우리,메타사용률) — 메타 사용 빈도 순"""
import csv
import json
import sys
from collections import Counter

from ai.gamedata import GameData, connect, norm

STATS = {"atk", "def", "spa", "spd", "spe", "accuracy", "evasion"}


def sd_effects(m):
    """Showdown 기술 -> {(trigger, kind, code, stages, chance)} (우리 move_effect 와 같은 표현으로)"""
    out = set()

    def boosts(b, trig, who, ch=100):
        for k, v in (b or {}).items():
            out.add((trig, "stat_stage", k, v, ch, who))

    def one(sec, trig):
        ch = sec.get("chance", 100)
        if sec.get("status"):
            out.add((trig, "status", sec["status"], None, ch, "target"))
        if sec.get("volatileStatus"):
            out.add((trig, "volatile", sec["volatileStatus"], None, ch, "target"))
        boosts(sec.get("boosts"), trig, "target", ch)
        if sec.get("self"):
            boosts(sec["self"].get("boosts"), trig, "self", ch)
            if sec["self"].get("volatileStatus"):
                out.add((trig, "volatile", sec["self"]["volatileStatus"], None, ch, "self"))
    for s in (m["secondaries"] or ([m["secondary"]] if m["secondary"] else [])):
        one(s, "secondary")
    if m["status"]:
        out.add(("primary", "status", m["status"], None, 100, "target"))
    if m["volatileStatus"]:
        out.add(("primary", "volatile", m["volatileStatus"], None, 100, "self" if m["target"] == "self" else "target"))
    if m["boosts"]:
        boosts(m["boosts"], "primary", "self" if m["target"] == "self" else "target")
    if m["self"]:
        boosts(m["self"].get("boosts"), "primary", "self")
        if m["self"].get("volatileStatus"):
            out.add(("primary", "volatile", m["self"]["volatileStatus"], None, 100, "self"))
    if m["selfBoost"]:
        boosts(m["selfBoost"].get("boosts"), "primary", "self")
    return out


def our_effects(mv):
    out = set()
    for e in mv["effects"]:
        if e["kind"] in ("status", "volatile", "stat_stage"):
            out.add((e["trigger_type"], e["kind"], e["code"], e["stages"] if e["kind"] == "stat_stage" else None,
                     e["chance_pct"], e["applies_to"]))
    return out


def main():
    sd = json.load(open("verify/out/sd_dump.json", encoding="utf-8"))
    conn = connect()
    data = GameData(conn)
    cur = conn.cursor()
    cur.execute("select m.name_en, avg(u.pct) p from meta_move u join move m using(move_id) group by m.name_en") if False else None
    use = {}
    try:
        cur.execute("select m.name_en n, sum(u.usage_pct) p from meta_move u join move m on m.move_id=u.move_id "
                    "where u.snapshot_id=33 group by m.name_en")
        use = {norm(r["n"]): float(r["p"] or 0) for r in cur.fetchall()}
    except Exception as e:
        print("사용률 조회 실패:", e, file=sys.stderr)
    rows = []

    def add(kind, name, field, a, b):
        rows.append((kind, name, field, a, b, use.get(norm(name), 0)))

    mine, theirs = data.moves, sd["moves"]
    for k, mv in mine.items():
        s = theirs.get(k)
        if not s:
            add("기술", mv["name"], "Showdown에 없음", "", "있음")
            continue
        n = mv["name"]
        chk = [("type", s["type"], mv["type"]), ("category", s["category"].lower(), mv["category"]),
               ("bp", s["bp"], mv["bp"]), ("priority", s["priority"], mv["priority"]),
               ("acc", 0 if s["acc"] is True else s["acc"], 0 if mv["accuracy"] is None else mv["accuracy"]),
               ("pp", s["pp"], mv["pp"]),
               ("crit", (s["critRatio"] or 1) - 1, mv["crit_stage"]), ("always_crit", bool(s["willCrit"]), mv["always_crit"]),
               ("ohko", bool(s["ohko"]), mv["ohko"]),
               ("self_switch", bool(s["selfSwitch"]), mv["self_switch"]), ("force_switch", bool(s["forceSwitch"]), mv["force_switch"]),
               ("self_destruct", bool(s["selfdestruct"]), mv["self_destruct"])]
        mh = s["multihit"]
        lo, hi = (mh if isinstance(mh, list) else (mh, mh)) if mh else (1, 1)
        chk += [("min_hits", lo, mv["min_hits"]), ("max_hits", hi, mv["max_hits"])]
        dr = round(100 * s["drain"][0] / s["drain"][1]) if s["drain"] else 0
        rc = round(100 * s["recoil"][0] / s["recoil"][1]) if s["recoil"] else 0
        hl = round(100 * s["heal"][0] / s["heal"][1]) if s["heal"] else 0
        chk += [("drain%", dr, mv["drain"]), ("recoil%", rc, mv["recoil"]), ("heal%", hl, mv["heal"])]
        fl = set(x for x in s["flags"])
        ours = set(mv["flags"])
        if fl != ours:
            add("기술", n, "flags", "+".join(sorted(fl - ours)) or "-", "+".join(sorted(ours - fl)) or "-")
        for f, a, b in chk:
            if a != b:
                add("기술", n, f, a, b)
        ea, eb = sd_effects(s), our_effects(mv)
        # 필드명이 달라도 같은 효과면 무시: 추가/누락만 보고
        for e in sorted(ea - eb, key=str):
            add("기술", n, "효과 누락(우리에 없음)", e, "")
        for e in sorted(eb - ea, key=str):
            add("기술", n, "효과 초과(Showdown에 없음)", "", e)
    for k in theirs:
        if k not in mine and theirs[k]["isNonstandard"] is None:
            add("기술", theirs[k]["name"], "우리에 없음", "있음", "")
    # 종: 종족값/타입
    cur.execute("select showdown_id sid, name_en, type1_id, type2_id, base_hp, base_atk, base_def, base_spa, base_spd, base_spe from pokemon")
    tn = {}
    cur.execute("select type_id, name_en from type")
    for r in cur.fetchall():
        tn[r["type_id"]] = r["name_en"]
    cur.execute("select showdown_id sid, name_en, type1_id, type2_id, base_hp, base_atk, base_def, base_spa, base_spd, base_spe from pokemon")
    for r in cur.fetchall():
        s = sd["species"].get(r["sid"] or "")
        if not s:
            continue
        b = s["base"]
        mb = dict(hp=r["base_hp"], atk=r["base_atk"], def_=r["base_def"], spa=r["base_spa"], spd=r["base_spd"], spe=r["base_spe"])
        sb = dict(hp=b["hp"], atk=b["atk"], def_=b["def"], spa=b["spa"], spd=b["spd"], spe=b["spe"])
        for st in mb:
            if mb[st] != sb[st]:
                add("종", r["name_en"], "종족값 " + st, sb[st], mb[st])
        t = sorted([tn[r["type1_id"]]] + ([tn[r["type2_id"]]] if r["type2_id"] else []))
        if t != sorted(s["types"]):
            add("종", r["name_en"], "타입", "/".join(s["types"]), "/".join(t))
    rows.sort(key=lambda x: -x[5])
    with open("verify/out/static_diff.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["분류", "이름", "필드", "Showdown", "우리", "메타사용률"])
        w.writerows(rows)
    c = Counter((r[0], r[2].split("(")[0]) for r in rows)
    print(f"차이 {len(rows)}건")
    for (k, f), n in c.most_common(30):
        print(f"  {k} / {f}: {n}")


if __name__ == "__main__":
    main()
