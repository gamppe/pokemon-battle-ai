"""상태를 거는 기술/분말 기술 -> 어떤 타입·특성에 막히는지 move_rule(target_immunity)로 자동 연결.
- 변화 기술은 기본적으로 타입 상성표(0배)를 무시한다(ignoreImmunity=true). 예외: Thunder Wave(false).
- 상태이상 면역은 type_immunity(par/brn/psn/tox/frz), 분말 기술은 type_immunity(powder: 풀) + 방진 특성."""
import os, json, pymysql

db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()
cur.execute("delete from move_rule where rule_type='target_immunity'")

cur.execute("select t.name_en, i.immunity_key from type_immunity i join type t using(type_id) where i.kind='condition'")
by_key = {}
for tname, key in cur.fetchall():
    by_key.setdefault(key, []).append(tname)

# 챔피언스 특성 중 해당 상태/분말을 막는 특성
cur.execute("""select a.name_en, e.code from ability_effect e join ability a using(ability_id)
    where e.kind='immune' and (e.code like 'status:%%' or e.code='flag:powder')
    and a.ability_id in (select ability_id from pokemon_ability where game_id=4)""")
ab_by_key = {}
for name, code in cur.fetchall():
    if code == "flag:powder":
        ab_by_key.setdefault("powder", []).append(name)
    else:
        for k in code.split(":", 1)[1].split("|"):
            ab_by_key.setdefault(k, []).append(name)

# 대상: 챔피언스 기술 중 (a) 대상에게 거는 기본(primary) 상태이상 효과가 있거나 (b) powder 플래그가 있는 기술
cur.execute("""select distinct m.move_id, m.name_en, m.category, t.name_en,
       (select group_concat(distinct e.code) from move_effect e where e.move_id=m.move_id and e.game_id=0
          and e.trigger_type='primary' and e.kind='status' and e.applies_to='target') statuses,
       exists(select 1 from move_flag f where f.move_id=m.move_id and f.flag='powder' and f.game_id=0) is_powder
  from game_move g join move m using(move_id) join type t on t.type_id=m.type_id
  where g.game_id=4""")
n = 0
for mid, name, cat, mtype, statuses, is_powder in cur.fetchall():
    keys = []
    for s in (statuses or "").split(","):
        if s in ("psn", "tox"):
            keys += ["psn", "tox"]
        elif s in ("par", "brn", "frz"):
            keys.append(s)
    if is_powder:
        keys.append("powder")
    if not keys:
        continue
    keys = sorted(set(keys))
    immune_types = sorted({tp for k in keys for tp in by_key.get(k, [])})
    immune_abilities = sorted({a for k in keys for a in ab_by_key.get(k, [])} | ({"Overcoat"} if is_powder else set()))
    chart = name == "Thunder Wave"  # ignoreImmunity=false 인 기술만 타입 상성표(0배)가 적용
    cur.execute("select dt.name_en from type_efficacy e join type dt on dt.type_id=e.defense_type_id "
                "join type at on at.type_id=e.attack_type_id where at.name_en=%s and e.multiplier=0", (mtype,))
    chart_immune = sorted(r[0] for r in cur.fetchall()) if chart else []
    params = dict(status_keys=[k for k in keys if k != "powder"], powder=bool(is_powder), immune_types=immune_types,
                  immune_abilities=immune_abilities, type_chart_applies=chart, type_chart_immune_types=chart_immune,
                  phase_no=4)
    note = "상태/분말 면역 자동 연결. 변화 기술은 타입 상성표 0배를 무시(ignoreImmunity)"
    if chart:
        note = "Thunder Wave는 예외로 타입 상성표가 적용됨(땅 타입 무효)와 전기 타입 마비 면역 모두 적용"
    cur.execute("insert into move_rule (move_id,rule_type,params,note) values (%s,'target_immunity',%s,%s)",
                (mid, json.dumps(params, ensure_ascii=False), note))
    n += 1
db.commit()
print("target_immunity rules", n)
